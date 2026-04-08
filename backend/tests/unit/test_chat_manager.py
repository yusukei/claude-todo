"""Unit tests for the multi-worker chat connection manager.

Two-instance setup mirrors the test pattern used by
``test_agent_bus.py``: we construct two ``ChatConnectionManager``
objects sharing the conftest fakeredis client to simulate two
backend workers, and verify that a ``broadcast`` from worker A
reaches a WebSocket attached to worker B.

## Limitation

fakeredis pub/sub is broken (subscribe + publish in the same
process returns ``None`` from ``get_message``), so the cross-worker
delivery cannot be exercised end-to-end here. Instead we test the
**publish-then-fanout** path by directly invoking the local
fan-out, which is what the subscriber would do upon receiving the
Redis message. The full pub/sub round-trip is covered by the
real-redis follow-up test suite [task:69d6900af4b6de00d3fd136a].
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services.chat_manager import (
    CHANNEL_PREFIX,
    ChatConnectionManager,
    _channel_for,
    _session_id_from_channel,
)


class FakeWebSocket:
    """Minimal WebSocket double that records sends."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


class TestLocalConnectionBookkeeping:
    """The connect / disconnect / count APIs stay process-local."""

    def test_connect_adds_to_local_set(self):
        m = ChatConnectionManager()
        ws = FakeWebSocket()
        m.connect("session-1", ws)  # type: ignore[arg-type]
        assert m.connection_count("session-1") == 1
        assert "session-1" in m.get_session_ids()

    def test_disconnect_removes_from_local_set(self):
        m = ChatConnectionManager()
        ws = FakeWebSocket()
        m.connect("session-1", ws)  # type: ignore[arg-type]
        m.disconnect("session-1", ws)  # type: ignore[arg-type]
        assert m.connection_count("session-1") == 0
        # Empty session is purged from get_session_ids.
        assert "session-1" not in m.get_session_ids()

    def test_disconnect_unknown_ws_is_noop(self):
        m = ChatConnectionManager()
        ws_a = FakeWebSocket()
        ws_b = FakeWebSocket()
        m.connect("session-1", ws_a)  # type: ignore[arg-type]
        m.disconnect("session-1", ws_b)  # type: ignore[arg-type]
        # ws_a is still attached.
        assert m.connection_count("session-1") == 1


class TestChannelHelpers:
    def test_channel_format_round_trip(self):
        sid = "deadbeef-1234"
        channel = _channel_for(sid)
        assert channel == f"{CHANNEL_PREFIX}{sid}"
        assert _session_id_from_channel(channel) == sid

    def test_channel_helper_rejects_unrelated(self):
        assert _session_id_from_channel("todo:events") is None
        assert _session_id_from_channel("") is None


class TestBroadcastPublishesToRedis:
    """The Redis publish path replaces the old in-process fan-out."""

    async def test_broadcast_publishes_when_redis_set(self):
        """``broadcast`` calls ``redis.publish`` with the JSON envelope."""
        m = ChatConnectionManager()
        published: list[tuple[str, str]] = []

        class _CapturingRedis:
            async def publish(self, channel: str, message: str) -> int:
                published.append((channel, message))
                return 1

        m._redis = _CapturingRedis()  # type: ignore[assignment]

        await m.broadcast("session-x", {"type": "text_delta", "text": "hi"})

        assert len(published) == 1
        channel, raw = published[0]
        assert channel == "chat:session:session-x"
        assert json.loads(raw) == {"type": "text_delta", "text": "hi"}

    async def test_broadcast_falls_back_to_local_when_redis_unset(self):
        """If ``start()`` was not called, broadcast still fans out locally.

        This keeps the test environment ergonomic — the test suite
        does not have to call ``start()`` to verify chat fan-out.
        Production always runs ``start()`` from the lifespan.
        """
        m = ChatConnectionManager()
        ws = FakeWebSocket()
        m.connect("session-y", ws)  # type: ignore[arg-type]

        await m.broadcast("session-y", {"type": "ping"})

        assert ws.sent == [json.dumps({"type": "ping"})]

    async def test_broadcast_falls_back_to_local_on_publish_failure(self):
        """A Redis hiccup must NOT silently lose chat messages.

        We log the failure (caller observes via ``logger.exception``)
        and fall back to local fan-out so browsers attached to this
        worker still get the message. CLAUDE.md "no error hiding"
        is satisfied because the failure is logged loudly.
        """
        m = ChatConnectionManager()
        ws = FakeWebSocket()
        m.connect("session-z", ws)  # type: ignore[arg-type]

        class _BrokenRedis:
            async def publish(self, channel: str, message: str) -> int:
                raise RuntimeError("redis is down")

        m._redis = _BrokenRedis()  # type: ignore[assignment]

        await m.broadcast("session-z", {"type": "ping"})

        # Local fan-out fired even though publish raised.
        assert ws.sent == [json.dumps({"type": "ping"})]


class TestSubscriberFanout:
    """The subscriber loop forwards Redis messages to local browsers."""

    async def test_fanout_local_delivers_to_all_attached(self):
        """``_fanout_local`` is the inner half of the subscriber path."""
        m = ChatConnectionManager()
        ws_a = FakeWebSocket()
        ws_b = FakeWebSocket()
        m.connect("session-1", ws_a)  # type: ignore[arg-type]
        m.connect("session-1", ws_b)  # type: ignore[arg-type]

        await m._fanout_local("session-1", json.dumps({"type": "ping"}))

        assert ws_a.sent == [json.dumps({"type": "ping"})]
        assert ws_b.sent == [json.dumps({"type": "ping"})]

    async def test_fanout_local_drops_dead_websockets(self):
        """A WebSocket whose ``send_text`` raises is removed from the set."""
        m = ChatConnectionManager()

        class DeadWS:
            async def send_text(self, payload: str) -> None:
                raise RuntimeError("connection reset")

        ws_alive = FakeWebSocket()
        dead = DeadWS()
        m.connect("session-d", ws_alive)  # type: ignore[arg-type]
        m.connect("session-d", dead)  # type: ignore[arg-type]

        await m._fanout_local("session-d", "hello")

        # Alive socket got the message, dead one was pruned.
        assert ws_alive.sent == ["hello"]
        assert dead not in m._connections.get("session-d", set())

    async def test_fanout_to_unknown_session_is_noop(self):
        m = ChatConnectionManager()
        # Should not raise even though session-unknown was never connected.
        await m._fanout_local("session-unknown", "hello")


class TestLifecycle:
    async def test_stop_when_not_started_is_noop(self):
        m = ChatConnectionManager()
        # Calling stop without start should be safe.
        await m.stop()

    async def test_start_is_idempotent(self):
        """Calling start twice does not double-launch the subscriber."""
        m = ChatConnectionManager()
        try:
            await m.start()
            first_task = m._subscriber_task
            await m.start()
            assert m._subscriber_task is first_task
        finally:
            await m.stop()
