"""Web Terminal browser WebSocket endpoint.

Issues short-lived single-use tickets to authenticated browsers and
relays PTY I/O between the browser and the agent via session_id-keyed
routing in :mod:`services.terminal_router`.

Auth model:
- ``POST /workspaces/terminal/ticket`` — JWT (cookie/Bearer) required,
  admin-only, agent ownership verified. Returns a 30s ticket.
- ``WS /workspaces/terminal/ws?ticket=...`` — ticket consumed on accept.
  Origin allowlist checked BEFORE accept (CSWSH defense).
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel

from .....core.config import settings
from .....core.deps import get_current_user
from .....models import User
from .....models.remote import RemoteAgent
from .....services.agent_manager import (
    AgentOfflineError,
    agent_manager,
)
from .....services.terminal_router import terminal_router

logger = logging.getLogger(__name__)

router = APIRouter()


# In-memory ticket store: ticket -> (user_id, agent_id, expires_at_monotonic).
# Single-use, 30s TTL: long enough for a slow page load, short enough to
# be useless for replay. Single-process — multi-worker would need Redis.
TICKET_TTL_SECONDS = 30
_tickets: dict[str, tuple[str, str, float]] = {}


def _purge_expired_tickets() -> None:
    now = time.monotonic()
    stale = [t for t, (_, _, exp) in _tickets.items() if exp <= now]
    for t in stale:
        _tickets.pop(t, None)


class TicketRequest(BaseModel):
    agent_id: str


class TicketResponse(BaseModel):
    ticket: str
    expires_in: int


@router.post("/terminal/ticket", response_model=TicketResponse)
async def issue_terminal_ticket(
    body: TicketRequest,
    user: User = Depends(get_current_user),
) -> TicketResponse:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin required",
        )
    agent = await RemoteAgent.get(body.agent_id)
    if not agent or agent.owner_id != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    _purge_expired_tickets()
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (
        str(user.id),
        body.agent_id,
        time.monotonic() + TICKET_TTL_SECONDS,
    )
    return TicketResponse(ticket=ticket, expires_in=TICKET_TTL_SECONDS)


def _allowed_origins() -> set[str]:
    return settings.ws_allowed_origins


@router.websocket("/terminal/ws")
async def terminal_websocket(ws: WebSocket):
    """Browser WebSocket for the Web Terminal.

    The ticket is consumed (one-shot) on accept. After that the session
    is identified by a server-generated ``session_id`` that the agent
    echoes back on every PTY frame.
    """
    origin = ws.headers.get("origin")
    if origin is not None:
        if origin not in _allowed_origins():
            logger.warning(
                "terminal_websocket: rejecting Origin=%r", origin,
            )
            await ws.close(code=4403, reason="Origin not allowed")
            return

    ticket = ws.query_params.get("ticket")
    shell = ws.query_params.get("shell", "")
    if not ticket:
        await ws.close(code=4008, reason="ticket required")
        return

    _purge_expired_tickets()
    entry = _tickets.pop(ticket, None)
    if entry is None:
        await ws.close(code=4008, reason="ticket invalid or expired")
        return
    _user_id, agent_id, _exp = entry

    await ws.accept()

    session_id = uuid.uuid4().hex
    terminal_router.register(session_id, ws)

    try:
        cols = int(ws.query_params.get("cols", 120))
        rows = int(ws.query_params.get("rows", 40))
    except ValueError:
        cols, rows = 120, 40

    try:
        result = await agent_manager.send_request(
            agent_id, "terminal_create",
            {
                "session_id": session_id,
                "shell": shell,
                "cols": cols,
                "rows": rows,
            },
            timeout=10.0,
        )
    except AgentOfflineError:
        terminal_router.unregister(session_id)
        try:
            await ws.send_text(json.dumps({
                "type": "error", "message": "Agent offline",
            }))
        except Exception:
            logger.info("terminal_websocket: could not deliver offline notice", exc_info=True)
        await ws.close(code=4500, reason="Agent offline")
        return
    except Exception as e:
        terminal_router.unregister(session_id)
        logger.exception(
            "terminal_websocket: send_request failed agent=%s session=%s",
            agent_id, session_id,
        )
        try:
            await ws.send_text(json.dumps({
                "type": "error", "message": f"PTY open failed: {e}",
            }))
        except Exception:
            logger.info("terminal_websocket: could not deliver error notice", exc_info=True)
        await ws.close(code=4500, reason="PTY open failed")
        return

    if not isinstance(result, dict) or not result.get("success"):
        terminal_router.unregister(session_id)
        msg = (result or {}).get("error", "PTY open failed")
        try:
            await ws.send_text(json.dumps({
                "type": "error", "message": msg,
            }))
        except Exception:
            logger.info("terminal_websocket: could not deliver agent-error", exc_info=True)
        await ws.close(code=4500, reason="PTY open failed")
        return

    try:
        await ws.send_text(json.dumps({
            "type": "session_started",
            "session_id": session_id,
            "shell": result.get("shell"),
        }))
    except Exception:
        logger.exception(
            "terminal_websocket: failed to send session_started session=%s",
            session_id,
        )
        terminal_router.unregister(session_id)
        return

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(
                    "terminal_websocket: dropped non-JSON frame session=%s",
                    session_id,
                )
                continue

            msg_type = msg.get("type")

            if msg_type == "input":
                data = msg.get("data", "")
                if isinstance(data, str):
                    await agent_manager.send_raw(agent_id, {
                        "type": "terminal_input",
                        "payload": {"session_id": session_id, "data": data},
                    })
            elif msg_type == "resize":
                try:
                    new_cols = int(msg.get("cols", 120))
                    new_rows = int(msg.get("rows", 40))
                except (TypeError, ValueError):
                    continue
                await agent_manager.send_raw(agent_id, {
                    "type": "terminal_resize",
                    "payload": {
                        "session_id": session_id,
                        "cols": new_cols,
                        "rows": new_rows,
                    },
                })
            elif msg_type == "ping":
                try:
                    await ws.send_text(json.dumps({"type": "pong"}))
                except Exception:
                    logger.info(
                        "terminal_websocket: pong send failed session=%s",
                        session_id, exc_info=True,
                    )
                    break
            else:
                logger.warning(
                    "terminal_websocket: unknown msg_type=%r session=%s",
                    msg_type, session_id,
                )

    except WebSocketDisconnect:
        logger.info(
            "terminal_websocket: browser disconnected session=%s", session_id,
        )
    except Exception:
        logger.exception(
            "terminal_websocket: unexpected error session=%s", session_id,
        )
    finally:
        terminal_router.unregister(session_id)
        try:
            await agent_manager.send_raw(agent_id, {
                "type": "terminal_close",
                "payload": {"session_id": session_id},
            })
        except Exception:
            logger.info(
                "terminal_websocket: terminal_close send failed agent=%s session=%s",
                agent_id, session_id, exc_info=True,
            )
