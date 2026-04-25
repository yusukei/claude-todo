"""In-process terminal session router.

Maps browser-supplied ``session_id`` to the originating browser
WebSocket so the agent's ``terminal_output`` / ``terminal_exit``
envelopes can be routed back. Single-process by design — multi-worker
support would require a Redis pub/sub fan-out, deferred until needed.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TerminalSessionRouter:
    def __init__(self) -> None:
        self._browsers: dict[str, WebSocket] = {}

    def register(self, session_id: str, ws: WebSocket) -> None:
        self._browsers[session_id] = ws

    def unregister(self, session_id: str) -> None:
        self._browsers.pop(session_id, None)

    def is_registered(self, session_id: str) -> bool:
        return session_id in self._browsers

    async def dispatch(self, msg: dict) -> bool:
        """Forward an agent terminal_output/terminal_exit envelope to the browser.

        Returns True if a browser was found and the frame was sent,
        False if the session is unknown or the send failed.
        """
        payload = msg.get("payload") or {}
        session_id = payload.get("session_id")
        if not session_id:
            return False
        ws = self._browsers.get(session_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            logger.exception(
                "terminal_router: failed to dispatch %s for session=%s",
                msg.get("type"), session_id,
            )
            return False
        return True


terminal_router = TerminalSessionRouter()
