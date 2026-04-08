"""Regression tests for the agent WebSocket Origin allowlist (Security C-2).

The agent WebSocket endpoint must validate the ``Origin`` header against
``settings.WS_ALLOWED_ORIGINS`` *before* calling ``ws.accept()``. This
defends against browser-mediated CSWSH attacks where a malicious page
could otherwise initiate a WebSocket from the user's browser, bypassing
SOP because WebSockets are exempt.

Server-to-server agent clients do not send an Origin header, so they
remain unaffected — their security boundary is the first-message auth
token, not Origin.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints.workspaces.websocket import agent_websocket


def _make_ws(origin: str | None) -> MagicMock:
    """Build a minimal WebSocket double with controllable headers."""
    ws = MagicMock()
    ws.headers = {"origin": origin} if origin is not None else {}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=Exception("should not be reached"))
    return ws


class TestOriginAllowlist:
    async def test_disallowed_origin_rejected_before_accept(self):
        """A browser-style request with a non-allowlisted Origin is closed
        before ``accept()`` is ever called."""
        ws = _make_ws(origin="https://evil.example.com")

        with patch(
            "app.api.v1.endpoints.workspaces.websocket.settings"
        ) as mock_settings:
            mock_settings.WS_ALLOWED_ORIGINS = "https://todo.example.com"
            await agent_websocket(ws)

        ws.accept.assert_not_called()
        ws.close.assert_awaited_once()
        # Verify the policy violation close code (4403)
        call = ws.close.await_args
        assert call.kwargs.get("code") == 4403 or 4403 in call.args

    async def test_allowed_origin_proceeds_to_accept(self):
        """Origin matching the allowlist passes through to ``accept()``."""
        ws = _make_ws(origin="https://todo.example.com")
        # ``receive_text`` raises on the auth message read so we can stop
        # the test right after accept() — we only care that accept happened.
        from fastapi import WebSocketDisconnect
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        with patch(
            "app.api.v1.endpoints.workspaces.websocket.settings"
        ) as mock_settings:
            mock_settings.WS_ALLOWED_ORIGINS = "https://todo.example.com,http://localhost:3000"
            await agent_websocket(ws)

        ws.accept.assert_awaited_once()

    async def test_multiple_allowed_origins(self):
        """Comma-separated allowlist accepts any listed origin."""
        ws = _make_ws(origin="http://localhost:3000")
        from fastapi import WebSocketDisconnect
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        with patch(
            "app.api.v1.endpoints.workspaces.websocket.settings"
        ) as mock_settings:
            mock_settings.WS_ALLOWED_ORIGINS = "https://todo.example.com,http://localhost:3000"
            await agent_websocket(ws)

        ws.accept.assert_awaited_once()

    async def test_no_origin_header_proceeds(self):
        """A request without an Origin header (server-to-server agent) is
        not blocked by the allowlist — Origin defense only applies to
        browser-mediated requests, which always send Origin."""
        ws = _make_ws(origin=None)
        from fastapi import WebSocketDisconnect
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        with patch(
            "app.api.v1.endpoints.workspaces.websocket.settings"
        ) as mock_settings:
            mock_settings.WS_ALLOWED_ORIGINS = "https://todo.example.com"
            await agent_websocket(ws)

        ws.accept.assert_awaited_once()

    async def test_whitespace_in_allowlist_tolerated(self):
        """Spaces around comma-separated values in the env var are stripped."""
        ws = _make_ws(origin="https://todo.example.com")
        from fastapi import WebSocketDisconnect
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        with patch(
            "app.api.v1.endpoints.workspaces.websocket.settings"
        ) as mock_settings:
            mock_settings.WS_ALLOWED_ORIGINS = "  https://todo.example.com  ,  http://localhost:3000  "
            await agent_websocket(ws)

        ws.accept.assert_awaited_once()

    async def test_empty_allowlist_rejects_browser_requests(self):
        """If WS_ALLOWED_ORIGINS is empty (misconfiguration that escapes
        the startup check, e.g. test mocking), browser requests with an
        Origin header must still be rejected."""
        ws = _make_ws(origin="https://todo.example.com")

        with patch(
            "app.api.v1.endpoints.workspaces.websocket.settings"
        ) as mock_settings:
            mock_settings.WS_ALLOWED_ORIGINS = ""
            await agent_websocket(ws)

        ws.accept.assert_not_called()
        ws.close.assert_awaited_once()
