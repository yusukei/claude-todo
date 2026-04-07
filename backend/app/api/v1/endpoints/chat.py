"""Chat session REST API + WebSocket router for Claude Code Web Chat.

This module is intentionally kept thin: it owns request/response schemas,
session CRUD endpoints, and the browser-facing WebSocket loop. Everything
else lives in `app.services.chat_manager` (connection fan-out) and
`app.services.chat_events` (agent dispatch + event handling), so the
agent WebSocket handler in `endpoints/terminal.py` and the lifespan
recovery hook in `app/main.py` can import them without depending on
this router module.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from ....core.deps import get_current_user
from ....models import Project, User
from ....models.chat import ChatMessage, ChatSession, MessageRole, MessageStatus, SessionStatus
from ....services.chat_events import (
    _process_stream_event,  # noqa: F401 — re-exported for tests
    cancel_agent_task,
    complete_with_error as _complete_with_error,  # noqa: F401 — back-compat
    dispatch_to_agent,
    handle_chat_event,  # noqa: F401 — re-exported for terminal.py back-compat
    message_dict as _message_dict,
    recover_stale_sessions as _recover_stale_sessions,  # noqa: F401 — re-exported for main.py back-compat
)
from ....services.chat_manager import ChatConnectionManager, chat_manager  # noqa: F401

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Re-exports keep historical import paths working without forcing every
# caller to be updated in this same commit.
__all__ = [
    "router",
    "chat_manager",
    "ChatConnectionManager",
    "_process_stream_event",
    "_complete_with_error",
    "handle_chat_event",
    "_recover_stale_sessions",
]


# ── Schemas ──────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    project_id: str
    title: str = Field("", max_length=255)
    model: str = Field("", max_length=100)


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(None, max_length=255)
    model: str | None = Field(None, max_length=100)


# ── Helpers ──────────────────────────────────────────────────


async def _check_project_access(project_id: str, user: User) -> Project:
    """Validate project exists and user has access."""
    project = await Project.get(project_id)
    if not project or not project.has_member(str(user.id)):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _session_dict(s: ChatSession) -> dict:
    return {
        "id": str(s.id),
        "project_id": s.project_id,
        "title": s.title,
        "claude_session_id": s.claude_session_id,
        "working_dir": s.working_dir,
        "status": s.status,
        "model": s.model,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


# ── Session CRUD ─────────────────────────────────────────────


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    user: User = Depends(get_current_user),
) -> dict:
    await _check_project_access(body.project_id, user)

    # Resolve working_dir from RemoteWorkspace
    from ....models.terminal import RemoteWorkspace
    workspace = await RemoteWorkspace.find_one({"project_id": body.project_id})
    working_dir = workspace.remote_path if workspace else ""

    session = ChatSession(
        project_id=body.project_id,
        title=body.title or f"Chat {datetime.now(UTC).strftime('%m/%d %H:%M')}",
        working_dir=working_dir,
        model=body.model,
        created_by=str(user.id),
    )
    await session.insert()
    return _session_dict(session)


@router.get("/sessions")
async def list_sessions(
    project_id: str | None = None,
    user: User = Depends(get_current_user),
) -> list[dict]:
    query: dict = {}
    if project_id:
        await _check_project_access(project_id, user)
        query["project_id"] = project_id
    elif not user.is_admin:
        # No project_id specified: restrict to projects this user is a
        # member of. Admins still see everything.
        member_projects = await Project.find(
            {"members.user_id": str(user.id)}
        ).to_list()
        allowed_ids = [str(p.id) for p in member_projects]
        if not allowed_ids:
            return []
        query["project_id"] = {"$in": allowed_ids}

    sessions = await ChatSession.find(query).sort("-updated_at").to_list()
    return [_session_dict(s) for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    session = await ChatSession.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _check_project_access(session.project_id, user)
    return _session_dict(session)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    user: User = Depends(get_current_user),
) -> dict:
    session = await ChatSession.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _check_project_access(session.project_id, user)

    if body.title is not None:
        session.title = body.title
    if body.model is not None:
        session.model = body.model
    await session.save_updated()
    return _session_dict(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
) -> None:
    session = await ChatSession.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _check_project_access(session.project_id, user)

    await ChatMessage.find({"session_id": str(session.id)}).delete()
    await session.delete()


# ── Messages ─────────────────────────────────────────────────


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    limit: int = 100,
    skip: int = 0,
    user: User = Depends(get_current_user),
) -> dict:
    session = await ChatSession.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await _check_project_access(session.project_id, user)

    query = ChatMessage.find({"session_id": str(session.id)})
    total = await query.count()
    messages = await query.sort("created_at").skip(skip).limit(limit).to_list()

    return {
        "items": [_message_dict(m) for m in messages],
        "total": total,
        "limit": limit,
        "skip": skip,
    }


# ── WebSocket ────────────────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def chat_websocket(ws: WebSocket, session_id: str):
    """WebSocket endpoint for real-time chat with Claude Code.

    Supports multi-browser fan-out: all browsers connected to the same
    session receive the same events. Inbound user messages are dispatched
    to the agent via `chat_events.dispatch_to_agent`; the agent's reply
    events flow back through `chat_events.handle_chat_event` (called from
    the agent WebSocket loop in `endpoints/terminal.py`).
    """
    await ws.accept()

    session = await ChatSession.get(session_id)
    if not session:
        await ws.close(code=4004, reason="Session not found")
        return

    chat_manager.connect(session_id, ws)
    logger.info(
        "Chat WS connected: session=%s (total=%d)",
        session_id, chat_manager.connection_count(session_id),
    )

    await ws.send_text(json.dumps({
        "type": "status",
        "session_status": session.status,
    }))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            elif msg_type == "send_message":
                content = msg.get("content", "").strip()
                if not content:
                    continue
                if session.status == SessionStatus.busy:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "detail": "Session is busy. Wait for the current response to complete.",
                    }))
                    continue

                user_msg = ChatMessage(
                    session_id=str(session.id),
                    role=MessageRole.user,
                    content=content,
                )
                await user_msg.insert()

                await chat_manager.broadcast(session_id, {
                    "type": "user_message",
                    "message": _message_dict(user_msg),
                })

                session.status = SessionStatus.busy
                await session.save_updated()
                await chat_manager.broadcast(session_id, {
                    "type": "status",
                    "session_status": "busy",
                })

                await dispatch_to_agent(session, content)

            elif msg_type == "cancel":
                await cancel_agent_task(session)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Chat WS error: session=%s, error=%s", session_id, e)
    finally:
        chat_manager.disconnect(session_id, ws)
        logger.info(
            "Chat WS disconnected: session=%s (remaining=%d)",
            session_id, chat_manager.connection_count(session_id),
        )
