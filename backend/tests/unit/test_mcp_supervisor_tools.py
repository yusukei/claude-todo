"""Unit tests for the supervisor_* MCP tools.

Mocks ``authenticate``, ``RemoteSupervisor.get``, and
``supervisor_manager.send_request`` so we can exercise the dispatch
+ ownership + payload-shape logic in isolation. End-to-end with a
real Rust supervisor lives in the manual acceptance pass (Day 5).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from app.mcp.tools import supervisor as sup_tools
from app.services.supervisor_manager import (
    SupervisorOfflineError,
    SupervisorRpcTimeout,
)


_KEY_INFO = {
    "user_id": "user-1",
    "user_name": "alice",
    "is_admin": False,
    "auth_kind": "api_key",
}


def _fake_supervisor(owner_id: str = "user-1"):
    """Return a minimal stand-in that quacks like RemoteSupervisor."""
    return SimpleNamespace(id="sup-1", name="UM790Pro", owner_id=owner_id)


@pytest.fixture
def patch_auth_and_get():
    """Patch authenticate + RemoteSupervisor.get to return a sup we own."""
    with (
        patch.object(
            sup_tools, "authenticate", new=AsyncMock(return_value=_KEY_INFO)
        ),
        patch.object(
            sup_tools.RemoteSupervisor,
            "get",
            new=AsyncMock(return_value=_fake_supervisor()),
        ),
    ):
        yield


@pytest.fixture
def patch_send_request():
    """Patch supervisor_manager.send_request and yield the mock."""
    mock = AsyncMock()
    with patch.object(
        sup_tools.supervisor_manager, "send_request", new=mock
    ):
        yield mock


class TestStatus:
    async def test_returns_payload_minus_envelope_marker(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {
            "agent_state": "running",
            "agent_pid": 12345,
            "consecutive_crashes": 0,
            "__type__": "supervisor_status_result",
        }
        result = await sup_tools.supervisor_status("sup-1")
        assert result["agent_state"] == "running"
        assert result["agent_pid"] == 12345
        assert "__type__" not in result
        patch_send_request.assert_awaited_once()
        args, _ = patch_send_request.call_args
        assert args[0] == "sup-1"
        assert args[1] == "supervisor_status"

    async def test_unknown_supervisor_raises(self, patch_send_request):
        with (
            patch.object(
                sup_tools, "authenticate", new=AsyncMock(return_value=_KEY_INFO)
            ),
            patch.object(
                sup_tools.RemoteSupervisor,
                "get",
                new=AsyncMock(return_value=None),
            ),
        ):
            with pytest.raises(ToolError, match="not found"):
                await sup_tools.supervisor_status("missing")
        patch_send_request.assert_not_awaited()

    async def test_other_users_supervisor_raises(self, patch_send_request):
        with (
            patch.object(
                sup_tools, "authenticate", new=AsyncMock(return_value=_KEY_INFO)
            ),
            patch.object(
                sup_tools.RemoteSupervisor,
                "get",
                new=AsyncMock(
                    return_value=_fake_supervisor(owner_id="someone-else")
                ),
            ),
        ):
            with pytest.raises(ToolError, match="not found"):
                await sup_tools.supervisor_status("sup-1")
        patch_send_request.assert_not_awaited()

    async def test_offline_translates_to_tool_error(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.side_effect = SupervisorOfflineError("sup-1")
        with pytest.raises(ToolError, match="offline"):
            await sup_tools.supervisor_status("sup-1")

    async def test_timeout_translates_to_tool_error(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.side_effect = SupervisorRpcTimeout(
            "sup-1 did not respond within 30s"
        )
        with pytest.raises(ToolError, match="did not respond"):
            await sup_tools.supervisor_status("sup-1")


class TestRestart:
    async def test_passes_graceful_timeout_when_provided(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {
            "restarted": True,
            "new_pid": 9999,
            "error": None,
        }
        result = await sup_tools.supervisor_restart(
            "sup-1", graceful_timeout_ms=2000
        )
        assert result["restarted"] is True
        assert result["new_pid"] == 9999
        args, _ = patch_send_request.call_args
        assert args[2]["graceful_timeout_ms"] == 2000

    async def test_omits_graceful_timeout_when_none(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {
            "restarted": True,
            "new_pid": 1,
            "error": None,
        }
        await sup_tools.supervisor_restart("sup-1")
        args, _ = patch_send_request.call_args
        assert "graceful_timeout_ms" not in args[2]


class TestLogs:
    async def test_filters_validated_and_passed_through(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {"lines": []}
        await sup_tools.supervisor_logs(
            "sup-1",
            lines=50,
            since_ts="2026-04-25T00:00:00Z",
            stream="stderr",
        )
        args, _ = patch_send_request.call_args
        payload = args[2]
        assert payload["lines"] == 50
        assert payload["since_ts"] == "2026-04-25T00:00:00Z"
        assert payload["stream"] == "stderr"

    async def test_invalid_stream_rejected_locally(
        self, patch_auth_and_get, patch_send_request
    ):
        with pytest.raises(ToolError, match="stream must be"):
            await sup_tools.supervisor_logs("sup-1", stream="garbage")
        patch_send_request.assert_not_awaited()

    async def test_zero_lines_rejected(
        self, patch_auth_and_get, patch_send_request
    ):
        with pytest.raises(ToolError, match="lines must be"):
            await sup_tools.supervisor_logs("sup-1", lines=0)
        patch_send_request.assert_not_awaited()


class TestUpgrade:
    async def test_lowercase_hex_passes_and_dispatches(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {
            "success": True,
            "new_version": None,
            "error": None,
        }
        sha = "a" * 64
        await sup_tools.supervisor_upgrade(
            "sup-1", "https://example.invalid/agent.exe", sha
        )
        args, kwargs = patch_send_request.call_args
        assert args[1] == "supervisor_upgrade"
        assert args[2]["sha256"] == sha
        # 180s upgrade timeout vs 30s default for other RPCs.
        assert kwargs.get("timeout") == sup_tools.UPGRADE_RPC_TIMEOUT_S

    async def test_uppercase_hex_normalised(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {
            "success": True,
            "new_version": None,
            "error": None,
        }
        sha = "A" * 64
        await sup_tools.supervisor_upgrade(
            "sup-1", "https://example.invalid/agent.exe", sha
        )
        args, _ = patch_send_request.call_args
        assert args[2]["sha256"] == sha.lower()

    async def test_short_sha_rejected_locally(
        self, patch_auth_and_get, patch_send_request
    ):
        with pytest.raises(ToolError, match="sha256 must be"):
            await sup_tools.supervisor_upgrade(
                "sup-1", "https://example/x", "abc123"
            )
        patch_send_request.assert_not_awaited()

    async def test_non_hex_rejected_locally(
        self, patch_auth_and_get, patch_send_request
    ):
        with pytest.raises(ToolError, match="sha256 must be"):
            await sup_tools.supervisor_upgrade(
                "sup-1", "https://example/x", "z" * 64
            )
        patch_send_request.assert_not_awaited()


class TestConfigReload:
    async def test_returns_payload_minus_marker(
        self, patch_auth_and_get, patch_send_request
    ):
        patch_send_request.return_value = {
            "success": False,
            "errors": [],
            "requires_restart": ["backend.token"],
            "__type__": "supervisor_config_reload_result",
        }
        result = await sup_tools.supervisor_config_reload("sup-1")
        assert result["success"] is False
        assert result["requires_restart"] == ["backend.token"]
        assert "__type__" not in result
