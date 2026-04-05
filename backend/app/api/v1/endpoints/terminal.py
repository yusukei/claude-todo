"""Terminal remote access — REST endpoints + WebSocket relay.

Supports multiple concurrent sessions per agent and multiple browsers
sharing the same session (broadcast output, any browser can input).
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from ....core.deps import get_admin_user
from ....core.redis import get_redis
from ....core.security import hash_api_key
from ....models import User
from ....models.terminal import TerminalAgent, TerminalSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])

# ── Ticket management ────────────────────────────────────────

_TICKET_TTL = 30  # seconds
_TICKET_PREFIX = "terminal_ticket:"

# ── In-memory relay state ────────────────────────────────────

# agent_id → WebSocket (one WS per agent)
_agent_connections: dict[str, WebSocket] = {}

# session_id → set of browser WebSockets (session sharing)
_session_browsers: dict[str, set[WebSocket]] = {}

# session_id → agent_id
_session_agent: dict[str, str] = {}

# session_id → TerminalSession DB id
_session_db_id: dict[str, str] = {}

# agent_id → set of active session_ids
_agent_sessions: dict[str, set[str]] = {}


# ── Request / Response schemas ───────────────────────────────

class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class TicketResponse(BaseModel):
    ticket: str


# ── Helper ───────────────────────────────────────────────────

def _agent_dict(a: TerminalAgent) -> dict:
    agent_id = str(a.id)
    sessions = _agent_sessions.get(agent_id, set())
    return {
        "id": agent_id,
        "name": a.name,
        "hostname": a.hostname,
        "os_type": a.os_type,
        "available_shells": a.available_shells,
        "is_online": agent_id in _agent_connections,
        "active_sessions": len(sessions),
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        "created_at": a.created_at.isoformat(),
    }


async def _broadcast(session_id: str, message: str, *, exclude: WebSocket | None = None) -> None:
    """Send a message to all browsers in a session."""
    browsers = _session_browsers.get(session_id)
    if not browsers:
        return
    dead: list[WebSocket] = []
    for ws in browsers:
        if ws is exclude:
            continue
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        browsers.discard(ws)


async def _close_session(session_id: str, reason: str = "closed") -> None:
    """Clean up a session: notify browsers, update DB, remove from state."""
    # Notify browsers
    msg = json.dumps({"type": "session_ended", "session_id": session_id, "reason": reason})
    await _broadcast(session_id, msg)
    _session_browsers.pop(session_id, None)

    # Remove from agent sessions
    agent_id = _session_agent.pop(session_id, None)
    if agent_id:
        sessions = _agent_sessions.get(agent_id)
        if sessions:
            sessions.discard(session_id)
            if not sessions:
                _agent_sessions.pop(agent_id, None)

    # Close DB record
    db_id = _session_db_id.pop(session_id, None)
    if db_id:
        try:
            s = await TerminalSession.get(db_id)
            if s and not s.ended_at:
                s.ended_at = datetime.now(UTC)
                await s.save()
        except Exception:
            pass


# ── Health check ─────────────────────────────────────────────

@router.get("/health")
async def terminal_health() -> dict:
    return {"status": "ok", "websocket_endpoints": ["/agent/ws", "/session/ws"]}


# ── REST endpoints (admin only) ──────────────────────────────

@router.get("/agents")
async def list_agents(user: User = Depends(get_admin_user)) -> list[dict]:
    agents = await TerminalAgent.find(
        {"owner_id": str(user.id)}
    ).sort("-created_at").to_list()
    return [_agent_dict(a) for a in agents]


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(body: CreateAgentRequest, user: User = Depends(get_admin_user)) -> dict:
    raw_token = f"ta_{secrets.token_hex(32)}"
    agent = TerminalAgent(
        name=body.name,
        key_hash=hash_api_key(raw_token),
        owner_id=str(user.id),
    )
    await agent.insert()
    return {
        **_agent_dict(agent),
        "token": raw_token,
    }


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, user: User = Depends(get_admin_user)) -> None:
    agent = await TerminalAgent.get(agent_id)
    if not agent or agent.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail="Agent not found")
    ws = _agent_connections.pop(str(agent.id), None)
    if ws:
        try:
            await ws.close(code=1000, reason="Agent deleted")
        except Exception:
            pass
    await agent.delete()


@router.get("/sessions")
async def list_sessions(agent_id: str = Query(...), user: User = Depends(get_admin_user)) -> list[dict]:
    """List active sessions for an agent."""
    agent = await TerminalAgent.get(agent_id)
    if not agent or agent.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail="Agent not found")
    sessions = _agent_sessions.get(agent_id, set())
    result = []
    for sid in sessions:
        browsers = _session_browsers.get(sid, set())
        db_id = _session_db_id.get(sid)
        result.append({
            "session_id": sid,
            "viewers": len(browsers),
            "db_id": db_id,
        })
    return result


@router.post("/ticket", response_model=TicketResponse)
async def create_terminal_ticket(user: User = Depends(get_admin_user)) -> TicketResponse:
    ticket = uuid.uuid4().hex
    redis = get_redis()
    await redis.set(f"{_TICKET_PREFIX}{ticket}", str(user.id), ex=_TICKET_TTL)
    return TicketResponse(ticket=ticket)


# ── WebSocket: Agent connection ──────────────────────────────

@router.websocket("/agent/ws")
async def agent_websocket(ws: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for remote agents."""
    key_hash = hash_api_key(token)
    agent = await TerminalAgent.find_one({"key_hash": key_hash})
    if not agent:
        await ws.close(code=4008, reason="Invalid agent token")
        return

    await ws.accept()
    agent_id = str(agent.id)
    _agent_connections[agent_id] = ws

    agent.is_online = True
    agent.last_seen_at = datetime.now(UTC)
    await agent.save()
    logger.info("Agent connected: %s (%s)", agent.name, agent_id)

    try:
        while True:
            raw = await ws.receive_text()

            # Fast path: forward output to session browsers
            if '"output"' in raw[:40]:
                # Extract session_id from raw JSON for routing
                try:
                    msg = json.loads(raw)
                    sid = msg.get("session_id", "")
                except (json.JSONDecodeError, TypeError):
                    continue
                if sid:
                    await _broadcast(sid, raw)
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            sid = msg.get("session_id", "")

            if msg_type == "agent_info":
                agent.hostname = msg.get("hostname", agent.hostname)
                agent.os_type = msg.get("os", agent.os_type)
                agent.available_shells = msg.get("shells", agent.available_shells)
                agent.last_seen_at = datetime.now(UTC)
                await agent.save()

            elif msg_type == "exited":
                exit_code = msg.get("exit_code", -1)
                await _close_session(sid, f"process_exited:{exit_code}")

            elif msg_type == "pong":
                pass

    except WebSocketDisconnect:
        logger.info("Agent disconnected: %s (%s)", agent.name, agent_id)
    except Exception as e:
        logger.error("Agent WebSocket error: %s", e)
    finally:
        _agent_connections.pop(agent_id, None)
        agent.is_online = False
        agent.last_seen_at = datetime.now(UTC)
        try:
            await agent.save()
        except Exception:
            pass

        # Close all sessions belonging to this agent
        session_ids = list(_agent_sessions.pop(agent_id, set()))
        for sid in session_ids:
            await _close_session(sid, "agent_disconnect")


# ── WebSocket: Browser session ───────────────────────────────

@router.websocket("/session/ws")
async def browser_websocket(
    ws: WebSocket,
    ticket: str = Query(...),
    agent_id: str = Query(...),
    shell: str = Query(""),
    session_id: str = Query(""),
):
    """WebSocket endpoint for browser terminal sessions.

    If session_id is provided, join an existing session (shared viewing).
    Otherwise, create a new session.
    """
    # Validate ticket
    redis = get_redis()
    ticket_key = f"{_TICKET_PREFIX}{ticket}"
    user_id = await redis.get(ticket_key)
    if not user_id:
        await ws.close(code=4001, reason="Invalid or expired ticket")
        return
    await redis.delete(ticket_key)

    user = await User.get(user_id)
    if not user or not user.is_active or not user.is_admin:
        await ws.close(code=4003, reason="Unauthorized")
        return

    agent = await TerminalAgent.get(agent_id)
    if not agent or agent.owner_id != str(user.id):
        await ws.close(code=4004, reason="Agent not found")
        return

    agent_ws = _agent_connections.get(agent_id)
    if not agent_ws:
        await ws.close(code=4005, reason="Agent is offline")
        return

    await ws.accept()

    joining_existing = bool(session_id and session_id in _session_browsers)

    if joining_existing:
        # Join existing session
        _session_browsers[session_id].add(ws)
        viewers = len(_session_browsers[session_id])
        await ws.send_text(json.dumps({
            "type": "session_joined",
            "session_id": session_id,
            "viewers": viewers,
        }))
        # Notify other browsers
        await _broadcast(session_id, json.dumps({
            "type": "viewer_changed",
            "session_id": session_id,
            "viewers": viewers,
        }), exclude=ws)
        logger.info("Browser joined session %s (viewers: %d)", session_id, viewers)
    else:
        # Create new session
        session_id = uuid.uuid4().hex[:12]
        _session_browsers[session_id] = {ws}
        _session_agent[session_id] = agent_id
        _agent_sessions.setdefault(agent_id, set()).add(session_id)

        # Create DB record
        db_session = TerminalSession(
            agent_id=agent_id,
            user_id=str(user.id),
            shell=shell or "",
        )
        await db_session.insert()
        _session_db_id[session_id] = str(db_session.id)

        # Tell agent to start PTY
        try:
            await agent_ws.send_text(json.dumps({
                "type": "session_start",
                "session_id": session_id,
                "shell": shell or "",
                "cols": 120,
                "rows": 40,
            }))
            await ws.send_text(json.dumps({
                "type": "session_started",
                "session_id": session_id,
                "shell": shell or "",
            }))
        except Exception as e:
            logger.error("Failed to start session: %s", e)
            _session_browsers.pop(session_id, None)
            _session_agent.pop(session_id, None)
            _agent_sessions.get(agent_id, set()).discard(session_id)
            _session_db_id.pop(session_id, None)
            await ws.close(code=1011, reason="Failed to start session")
            return

        logger.info("Terminal session started: user=%s agent=%s session=%s", user.name, agent.name, session_id)

    # ── Message loop ─────────────────────────────────────────
    try:
        while True:
            raw = await ws.receive_text()

            # Fast path: forward input
            if '"input"' in raw[:30]:
                current_agent_ws = _agent_connections.get(agent_id)
                if current_agent_ws:
                    # Inject session_id if not present
                    if '"session_id"' not in raw:
                        try:
                            m = json.loads(raw)
                            m["session_id"] = session_id
                            raw = json.dumps(m)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    try:
                        await current_agent_ws.send_text(raw)
                    except Exception:
                        break
                else:
                    await ws.send_text(json.dumps({
                        "type": "session_ended",
                        "session_id": session_id,
                        "reason": "agent_disconnect",
                    }))
                    break
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "resize":
                msg["session_id"] = session_id
                current_agent_ws = _agent_connections.get(agent_id)
                if current_agent_ws:
                    try:
                        await current_agent_ws.send_text(json.dumps(msg))
                    except Exception:
                        pass

            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        logger.info("Browser disconnected from session %s", session_id)
    except Exception as e:
        logger.error("Browser WebSocket error: %s", e)
    finally:
        # Remove this browser from session
        browsers = _session_browsers.get(session_id)
        if browsers:
            browsers.discard(ws)
            if browsers:
                # Other browsers still connected — notify viewer count change
                viewers = len(browsers)
                try:
                    await _broadcast(session_id, json.dumps({
                        "type": "viewer_changed",
                        "session_id": session_id,
                        "viewers": viewers,
                    }))
                except Exception:
                    pass
            else:
                # Last browser left — end session
                current_agent_ws = _agent_connections.get(agent_id)
                if current_agent_ws:
                    try:
                        await current_agent_ws.send_text(json.dumps({
                            "type": "session_end",
                            "session_id": session_id,
                        }))
                    except Exception:
                        pass
                await _close_session(session_id, "user_closed")
