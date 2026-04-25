"""Unit tests for SupervisorConnectionManager.

Targets the in-process state machine: register/unregister, RPC
correlation by request_id, timeout, and the offline-cancel
guarantee that disconnect fails just the affected futures.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.services.supervisor_manager import (
    SupervisorConnectionManager,
    SupervisorOfflineError,
    SupervisorRpcTimeout,
)


class FakeWebSocket:
    """Records every send_text payload; raises on demand."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail_next: bool = False
        self.closed: tuple[int, str] | None = None

    async def send_text(self, payload: str) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("send failed")
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


@pytest.fixture
def manager() -> SupervisorConnectionManager:
    return SupervisorConnectionManager()


class TestRegisterUnregister:
    async def test_register_marks_connected(self, manager):
        ws = FakeWebSocket()
        await manager.register("sup-1", ws)
        assert manager.is_connected("sup-1")
        assert "sup-1" in manager.get_connected_supervisor_ids()

    async def test_unregister_with_matching_ws_evicts(self, manager):
        ws = FakeWebSocket()
        await manager.register("sup-1", ws)
        await manager.unregister("sup-1", ws)
        assert not manager.is_connected("sup-1")

    async def test_unregister_with_stale_ws_is_noop(self, manager):
        """A late cleanup from an old handler must not evict the live ws."""
        old = FakeWebSocket()
        new = FakeWebSocket()
        await manager.register("sup-1", old)
        await manager.register("sup-1", new)  # reconnect
        await manager.unregister("sup-1", old)  # stale cleanup
        assert manager.is_connected("sup-1")

    async def test_unregister_unknown_id_is_noop(self, manager):
        await manager.unregister("never-registered")  # must not raise


class TestRpc:
    async def test_send_request_offline_raises(self, manager):
        with pytest.raises(SupervisorOfflineError):
            await manager.send_request(
                "missing", "supervisor_status", {}, timeout=1.0
            )

    async def test_send_request_resolves_via_request_id(self, manager):
        ws = FakeWebSocket()
        await manager.register("sup-1", ws)

        # Start the RPC; the response arrives via resolve_request below.
        task = asyncio.create_task(
            manager.send_request("sup-1", "supervisor_status", {}, timeout=2.0)
        )
        # Give send_text a tick to land a frame in ``ws.sent``.
        await asyncio.sleep(0.01)
        sent = json.loads(ws.sent[-1])
        assert sent["type"] == "supervisor_status"
        rid = sent["request_id"]

        manager.resolve_request({
            "type": "supervisor_status_result",
            "request_id": rid,
            "payload": {"agent_state": "running", "consecutive_crashes": 0},
        })
        result = await task
        assert result["agent_state"] == "running"
        # __type__ is injected so callers can inspect the response kind.
        assert result["__type__"] == "supervisor_status_result"

    async def test_send_request_timeout(self, manager):
        ws = FakeWebSocket()
        await manager.register("sup-1", ws)
        with pytest.raises(SupervisorRpcTimeout):
            await manager.send_request(
                "sup-1", "supervisor_status", {}, timeout=0.05
            )
        # The pending Future must be cleaned up so a late response
        # doesn't leak through.
        assert not manager._pending  # internal state; OK in a unit test

    async def test_disconnect_fails_pending_rpcs(self, manager):
        ws = FakeWebSocket()
        await manager.register("sup-1", ws)

        # Start a long-running RPC.
        task = asyncio.create_task(
            manager.send_request("sup-1", "supervisor_status", {}, timeout=10.0)
        )
        await asyncio.sleep(0.01)
        # Disconnect while RPC is still in flight.
        await manager.unregister("sup-1", ws)
        with pytest.raises(SupervisorOfflineError):
            await task

    async def test_send_request_send_failure_cleans_up(self, manager):
        ws = FakeWebSocket()
        ws.fail_next = True
        await manager.register("sup-1", ws)
        with pytest.raises(SupervisorOfflineError):
            await manager.send_request(
                "sup-1", "supervisor_status", {}, timeout=2.0
            )
        # Failed send must not leave a phantom pending Future.
        assert not manager._pending


class TestResolve:
    async def test_resolve_unknown_request_id_returns_false(self, manager):
        assert manager.resolve_request({
            "type": "supervisor_status_result",
            "request_id": "never-issued",
            "payload": {},
        }) is False

    async def test_resolve_push_frame_returns_false(self, manager):
        # Push frames have no request_id at all.
        assert manager.resolve_request({
            "type": "supervisor_event",
            "payload": {"event": "agent_started"},
        }) is False

    async def test_disconnect_only_cancels_owned_pending(self, manager):
        ws_a = FakeWebSocket()
        ws_b = FakeWebSocket()
        await manager.register("sup-a", ws_a)
        await manager.register("sup-b", ws_b)

        task_a = asyncio.create_task(
            manager.send_request("sup-a", "supervisor_status", {}, timeout=10.0)
        )
        task_b = asyncio.create_task(
            manager.send_request("sup-b", "supervisor_status", {}, timeout=10.0)
        )
        await asyncio.sleep(0.01)

        # Disconnect only sup-a — sup-b's RPC must remain pending.
        await manager.unregister("sup-a", ws_a)
        with pytest.raises(SupervisorOfflineError):
            await task_a
        assert not task_b.done()

        # Resolve sup-b's RPC normally.
        sent_b = json.loads(ws_b.sent[-1])
        manager.resolve_request({
            "type": "supervisor_status_result",
            "request_id": sent_b["request_id"],
            "payload": {"ok": True},
        })
        result = await task_b
        assert result["ok"] is True
