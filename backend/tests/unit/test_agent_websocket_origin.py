"""Regression tests for the agent WebSocket Origin allowlist (Security C-2).

The agent WebSocket endpoint must validate the ``Origin`` header against
``settings.ws_allowed_origins`` *before* calling ``ws.accept()``. This
defends against browser-mediated CSWSH attacks where a malicious page
could otherwise initiate a WebSocket from the user's browser, bypassing
SOP because WebSockets are exempt.

Server-to-server agent clients do not send an Origin header, so they
remain unaffected — their security boundary is the first-message auth
token, not Origin.

Note on the allowlist source: ``ws_allowed_origins`` is a derived
``@property`` on ``Settings`` that returns ``{FRONTEND_URL}``. The
tests monkeypatch ``FRONTEND_URL`` so the derivation is exercised
end-to-end instead of short-circuiting the property.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.endpoints.workspaces.websocket import agent_websocket
from app.core.config import settings


def _make_ws(origin: str | None) -> MagicMock:
    """Build a minimal WebSocket double with controllable headers."""
    ws = MagicMock()
    ws.headers = {"origin": origin} if origin is not None else {}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=Exception("should not be reached"))
    return ws


@pytest.fixture
def frontend_url(monkeypatch):
    """Return a setter that overrides ``settings.FRONTEND_URL`` for the test.

    ``ws_allowed_origins`` is a derived property, so there is nothing to
    patch on its own — swapping ``FRONTEND_URL`` changes the allowlist
    value that the endpoint observes.
    """

    def _set(value: str) -> None:
        monkeypatch.setattr(settings, "FRONTEND_URL", value)

    return _set


class TestOriginAllowlist:
    async def test_disallowed_origin_rejected_before_accept(self, frontend_url):
        """A browser-style request with a non-allowlisted Origin is closed
        before ``accept()`` is ever called."""
        frontend_url("https://todo.example.com")
        ws = _make_ws(origin="https://evil.example.com")

        await agent_websocket(ws)

        ws.accept.assert_not_called()
        ws.close.assert_awaited_once()
        # Verify the policy violation close code (4403)
        call = ws.close.await_args
        assert call.kwargs.get("code") == 4403 or 4403 in call.args

    async def test_allowed_origin_proceeds_to_accept(self, frontend_url):
        """Origin matching the allowlist passes through to ``accept()``."""
        from fastapi import WebSocketDisconnect

        frontend_url("https://todo.example.com")
        ws = _make_ws(origin="https://todo.example.com")
        # ``receive_text`` raises on the auth message read so we can stop
        # the test right after accept() — we only care that accept happened.
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        await agent_websocket(ws)

        ws.accept.assert_awaited_once()

    async def test_no_origin_header_proceeds(self, frontend_url):
        """A request without an Origin header (server-to-server agent) is
        not blocked by the allowlist — Origin defense only applies to
        browser-mediated requests, which always send Origin."""
        from fastapi import WebSocketDisconnect

        frontend_url("https://todo.example.com")
        ws = _make_ws(origin=None)
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        await agent_websocket(ws)

        ws.accept.assert_awaited_once()

    async def test_localhost_frontend_allows_localhost_origin(self, frontend_url):
        """Default dev configuration: FRONTEND_URL=http://localhost:3000
        accepts localhost browser connections."""
        from fastapi import WebSocketDisconnect

        frontend_url("http://localhost:3000")
        ws = _make_ws(origin="http://localhost:3000")
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        await agent_websocket(ws)

        ws.accept.assert_awaited_once()
