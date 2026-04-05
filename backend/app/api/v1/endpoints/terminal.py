"""Terminal remote access — REST endpoints + WebSocket relay.

Shared workspace model:
- Sessions persist until PTY exits, agent disconnects, or user explicitly closes
- All browsers see the same session list (server is source of truth)
- Multiple browsers share the same session output
- One WebSocket per browser, multiplexing all sessions for that agent
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from dataclasses import dataclass, field
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

_TICKET_TTL = 30
_TICKET_PREFIX = "terminal_ticket:"

# ── In-memory state (server is source of truth) ──────────────


@dataclass
class SessionState:
    session_id: str
    agent_id: str
    shell: str
    started_at: datetime
    db_id: str
    browsers: set[WebSocket] = field(default_factory=set)


# agent_id → WebSocket
_agent_connections: dict[str, WebSocket] = {}

# session_id → SessionState
_sessions: dict[str, SessionState] = {}

# agent_id → set of session_ids
_agent_sessions: dict[str, set[str]] = {}

# browser WebSocket → (agent_id, user_id)  — tracks all connected browsers
_browser_agents: dict[WebSocket, tuple[str, str]] = {}


# ── Schemas ──────────────────────────────────────────────────

class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class TicketResponse(BaseModel):
    ticket: str


# ── Helpers ──────────────────────────────────────────────────

def _agent_dict(a: TerminalAgent) -> dict:
    agent_id = str(a.id)
    return {
        "id": agent_id,
        "name": a.name,
        "hostname": a.hostname,
        "os_type": a.os_type,
        "available_shells": a.available_shells,
        "is_online": agent_id in _agent_connections,
        "active_sessions": len(_agent_sessions.get(agent_id, set())),
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        "created_at": a.created_at.isoformat(),
    }


def _session_dict(s: SessionState) -> dict:
    return {
        "session_id": s.session_id,
        "agent_id": s.agent_id,
        "shell": s.shell,
        "started_at": s.started_at.isoformat(),
        "viewers": len(s.browsers),
    }


async def _broadcast_session(session_id: str, message: str) -> None:
    """Send message to all browsers viewing a session."""
    state = _sessions.get(session_id)
    if not state:
        return
    dead: list[WebSocket] = []
    for ws in state.browsers:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.browsers.discard(ws)


async def _notify_all_browsers(agent_id: str, message: str) -> None:
    """Send message to all browsers connected to an agent."""
    for ws, (aid, _uid) in list(_browser_agents.items()):
        if aid == agent_id:
            try:
                await ws.send_text(message)
            except Exception:
                pass


async def _close_session(session_id: str, reason: str) -> None:
    """Close a session: notify browsers, update DB, clean up state."""
    state = _sessions.pop(session_id, None)
    if not state:
        return

    # Notify all browsers viewing this session
    msg = json.dumps({"type": "session_ended", "session_id": session_id, "reason": reason})
    for ws in state.browsers:
        try:
            await ws.send_text(msg)
        except Exception:
            pass

    # Notify all browsers of this agent that session list changed
    await _notify_all_browsers(state.agent_id, json.dumps({
        "type": "sessions_changed", "agent_id": state.agent_id,
    }))

    # Remove from agent sessions
    sids = _agent_sessions.get(state.agent_id)
    if sids:
        sids.discard(session_id)
        if not sids:
            _agent_sessions.pop(state.agent_id, None)

    # Update DB
    try:
        s = await TerminalSession.get(state.db_id)
        if s and not s.ended_at:
            s.ended_at = datetime.now(UTC)
            await s.save()
    except Exception:
        pass


# ── Health check ─────────────────────────────────────────────

@router.get("/health")
async def terminal_health() -> dict:
    return {"status": "ok", "websocket_endpoints": ["/agent/ws", "/ws"]}


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
    return {**_agent_dict(agent), "token": raw_token}


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
    """List active sessions for an agent (source of truth for all browsers)."""
    agent = await TerminalAgent.get(agent_id)
    if not agent or agent.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail="Agent not found")
    sids = _agent_sessions.get(agent_id, set())
    return [_session_dict(_sessions[sid]) for sid in sids if sid in _sessions]


@router.post("/ticket", response_model=TicketResponse)
async def create_terminal_ticket(user: User = Depends(get_admin_user)) -> TicketResponse:
    ticket = uuid.uuid4().hex
    redis = get_redis()
    await redis.set(f"{_TICKET_PREFIX}{ticket}", str(user.id), ex=_TICKET_TTL)
    return TicketResponse(ticket=ticket)


# ── WebSocket: Agent ─────────────────────────────────────────

@router.websocket("/agent/ws")
async def agent_websocket(ws: WebSocket, token: str = Query(...)):
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

            # Fast path: output → broadcast to session browsers
            if '"output"' in raw[:40]:
                try:
                    msg = json.loads(raw)
                    sid = msg.get("session_id", "")
                except (json.JSONDecodeError, TypeError):
                    continue
                if sid:
                    await _broadcast_session(sid, raw)
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
                await _close_session(sid, f"process_exited:{msg.get('exit_code', -1)}")

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

        # Close all sessions for this agent
        for sid in list(_agent_sessions.pop(agent_id, set())):
            await _close_session(sid, "agent_disconnect")


# ── WebSocket: Browser ───────────────────────────────────────

@router.websocket("/ws")
async def browser_websocket(
    ws: WebSocket,
    ticket: str = Query(...),
    agent_id: str = Query(...),
):
    """Single WebSocket per browser, multiplexing all sessions for one agent.

    Browser sends commands via this WS:
    - {"type": "session_create", "shell": "..."} → create new session
    - {"type": "session_close", "session_id": "..."} → terminate session
    - {"type": "session_join", "session_id": "..."} → start receiving output
    - {"type": "session_leave", "session_id": "..."} → stop receiving output
    - {"type": "input", "session_id": "...", "data": "..."} → terminal input
    - {"type": "resize", "session_id": "...", "cols": N, "rows": N}
    """
    # Auth
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

    await ws.accept()
    _browser_agents[ws] = (agent_id, str(user.id))

    # Send current session list
    sids = _agent_sessions.get(agent_id, set())
    sessions = [_session_dict(_sessions[sid]) for sid in sids if sid in _sessions]
    await ws.send_text(json.dumps({
        "type": "session_list",
        "sessions": sessions,
    }))

    logger.info("Browser connected: user=%s agent=%s", user.name, agent.name)

    try:
        while True:
            raw = await ws.receive_text()

            # Fast path: input
            if '"input"' in raw[:30]:
                try:
                    msg = json.loads(raw)
                    sid = msg.get("session_id", "")
                except (json.JSONDecodeError, TypeError):
                    continue
                if sid and sid in _sessions:
                    agent_ws = _agent_connections.get(agent_id)
                    if agent_ws:
                        try:
                            await agent_ws.send_text(raw)
                        except Exception:
                            pass
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "session_create":
                await _handle_create(ws, agent_id, user, msg)

            elif msg_type == "session_close":
                await _handle_close(ws, agent_id, msg)

            elif msg_type == "session_join":
                sid = msg.get("session_id", "")
                state = _sessions.get(sid)
                if state and state.agent_id == agent_id:
                    state.browsers.add(ws)
                    await ws.send_text(json.dumps({
                        "type": "session_joined",
                        "session_id": sid,
                        "viewers": len(state.browsers),
                    }))
                    await _broadcast_viewer_changed(sid)

            elif msg_type == "session_leave":
                sid = msg.get("session_id", "")
                state = _sessions.get(sid)
                if state:
                    state.browsers.discard(ws)
                    await _broadcast_viewer_changed(sid)

            elif msg_type == "resize":
                sid = msg.get("session_id", "")
                if sid and sid in _sessions:
                    agent_ws = _agent_connections.get(agent_id)
                    if agent_ws:
                        try:
                            await agent_ws.send_text(raw)
                        except Exception:
                            pass

            elif msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        logger.info("Browser disconnected: user=%s", user.name)
    except Exception as e:
        logger.error("Browser WebSocket error: %s", e)
    finally:
        _browser_agents.pop(ws, None)
        # Remove this browser from all sessions (but don't close sessions)
        for state in _sessions.values():
            if ws in state.browsers:
                state.browsers.discard(ws)


async def _handle_create(ws: WebSocket, agent_id: str, user: User, msg: dict) -> None:
    """Handle session_create command from browser."""
    agent_ws = _agent_connections.get(agent_id)
    if not agent_ws:
        await ws.send_text(json.dumps({"type": "error", "message": "Agent is offline"}))
        return

    shell = msg.get("shell", "")
    session_id = uuid.uuid4().hex[:12]

    # Create DB record
    db_session = TerminalSession(
        agent_id=agent_id,
        user_id=str(user.id),
        shell=shell,
    )
    await db_session.insert()

    # Create state
    state = SessionState(
        session_id=session_id,
        agent_id=agent_id,
        shell=shell,
        started_at=datetime.now(UTC),
        db_id=str(db_session.id),
        browsers={ws},
    )
    _sessions[session_id] = state
    _agent_sessions.setdefault(agent_id, set()).add(session_id)

    # Tell agent to spawn PTY
    try:
        await agent_ws.send_text(json.dumps({
            "type": "session_start",
            "session_id": session_id,
            "shell": shell,
            "cols": msg.get("cols", 120),
            "rows": msg.get("rows", 40),
        }))
    except Exception as e:
        logger.error("Failed to start session: %s", e)
        _sessions.pop(session_id, None)
        _agent_sessions.get(agent_id, set()).discard(session_id)
        await ws.send_text(json.dumps({"type": "error", "message": "Failed to start session"}))
        return

    await ws.send_text(json.dumps({
        "type": "session_started",
        "session_id": session_id,
        "shell": shell,
    }))

    # Notify all browsers that session list changed
    await _notify_all_browsers(agent_id, json.dumps({
        "type": "sessions_changed", "agent_id": agent_id,
    }))

    logger.info("Session created: %s (agent=%s user=%s)", session_id, agent_id, user.name)


async def _handle_close(ws: WebSocket, agent_id: str, msg: dict) -> None:
    """Handle session_close command from browser — explicitly kill session."""
    sid = msg.get("session_id", "")
    state = _sessions.get(sid)
    if not state or state.agent_id != agent_id:
        return

    # Tell agent to end PTY
    agent_ws = _agent_connections.get(agent_id)
    if agent_ws:
        try:
            await agent_ws.send_text(json.dumps({
                "type": "session_end",
                "session_id": sid,
            }))
        except Exception:
            pass

    await _close_session(sid, "user_closed")


async def _broadcast_viewer_changed(session_id: str) -> None:
    state = _sessions.get(session_id)
    if not state:
        return
    msg = json.dumps({
        "type": "viewer_changed",
        "session_id": session_id,
        "viewers": len(state.browsers),
    })
    await _broadcast_session(session_id, msg)
