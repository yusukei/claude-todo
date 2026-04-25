"""Origin-allowlist regression tests for the supervisor WebSocket.

Same threat model as the agent endpoint (``test_agent_websocket_origin``):
a browser-mediated CSWSH attempt must be rejected before ``accept()``
is ever called, while server-to-server clients (no Origin header) pass
through to token auth.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.endpoints.workspaces.supervisor_ws import supervisor_websocket
from app.core.config import settings


def _make_ws(origin: str | None) -> MagicMock:
    ws = MagicMock()
    ws.headers = {"origin": origin} if origin is not None else {}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=Exception("should not be reached"))
    return ws


@pytest.fixture
def frontend_url(monkeypatch):
    def _set(value: str) -> None:
        monkeypatch.setattr(settings, "FRONTEND_URL", value)

    return _set


class TestOriginAllowlist:
    async def test_disallowed_origin_rejected_before_accept(self, frontend_url):
        frontend_url("https://todo.example.com")
        ws = _make_ws(origin="https://evil.example.com")

        await supervisor_websocket(ws)

        ws.accept.assert_not_called()
        ws.close.assert_awaited_once()
        call = ws.close.await_args
        assert call.kwargs.get("code") == 4403 or 4403 in call.args

    async def test_no_origin_header_proceeds_to_accept(self, frontend_url):
        """The Rust supervisor sends no Origin header, so it must pass."""
        from fastapi import WebSocketDisconnect

        frontend_url("https://todo.example.com")
        ws = _make_ws(origin=None)
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())

        await supervisor_websocket(ws)

        ws.accept.assert_awaited_once()
