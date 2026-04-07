"""ChatConnectionManager — per-session WebSocket fan-out for chat browsers.

Extracted from `api/v1/endpoints/chat.py` so the websocket handler, the
agent event dispatcher, and the lifespan recovery code can all share a
single process-wide singleton without depending on the FastAPI router
module (which would create a circular import).

The class is intentionally minimal: it tracks `session_id → set[WebSocket]`
and broadcasts JSON-serializable dicts to every browser attached to a
session. Failed sends are removed from the set so a stuck browser can't
block fan-out for the rest.
"""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ChatConnectionManager:
    """Manages WebSocket connections per chat session for multi-browser fan-out."""

    def __init__(self) -> None:
        # session_id → set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}

    def connect(self, session_id: str, ws: WebSocket) -> None:
        if session_id not in self._connections:
            self._connections[session_id] = set()
        self._connections[session_id].add(ws)

    def disconnect(self, session_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(session_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._connections[session_id]

    async def broadcast(self, session_id: str, message: dict) -> None:
        """Send message to all browsers connected to this session."""
        conns = self._connections.get(session_id, set())
        payload = json.dumps(message, default=str)
        disconnected = []
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            conns.discard(ws)

    def get_session_ids(self) -> list[str]:
        return list(self._connections.keys())

    def connection_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, set()))


# Module-level singleton — import from anywhere instead of constructing
# new instances. Tests can swap it out via monkeypatch on this module.
chat_manager = ChatConnectionManager()
