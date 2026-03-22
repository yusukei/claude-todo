"""Tests for app.session_store — Redis-backed EventStore for SSE sessions."""

import json
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from mcp.types import JSONRPCMessage
from pydantic import TypeAdapter

from app.session_store import RedisEventStore

_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)


def _make_jsonrpc_notification(method: str = "test", params: dict | None = None) -> JSONRPCMessage:
    """Build a minimal JSONRPC notification message."""
    raw = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        raw["params"] = params
    return _message_adapter.validate_python(raw)


@pytest.fixture()
async def store():
    """Create a RedisEventStore backed by fakeredis."""
    s = RedisEventStore()
    # Replace the real Redis connection with fakeredis
    s._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield s
    await s.aclose()


class TestStoreEvent:
    """Tests for store_event()."""

    async def test_returns_event_id_format(self, store: RedisEventStore):
        """store_event returns an event_id in '{stream_id}:{seq}' format."""
        msg = _make_jsonrpc_notification("tools/list")
        event_id = await store.store_event("stream-abc", msg)

        assert event_id == "stream-abc:1"

    async def test_sequential_ids(self, store: RedisEventStore):
        """Successive calls increment the sequence number."""
        msg = _make_jsonrpc_notification("tools/list")
        eid1 = await store.store_event("stream-abc", msg)
        eid2 = await store.store_event("stream-abc", msg)
        eid3 = await store.store_event("stream-abc", msg)

        assert eid1 == "stream-abc:1"
        assert eid2 == "stream-abc:2"
        assert eid3 == "stream-abc:3"

    async def test_data_persisted_in_redis(self, store: RedisEventStore):
        """Stored event data can be read back from the Redis list."""
        msg = _make_jsonrpc_notification("tools/call", {"name": "list_tasks"})
        await store.store_event("stream-x", msg)

        key = "todo:mcp:events:stream-x"
        raw_items = await store._redis.lrange(key, 0, -1)

        assert len(raw_items) == 1
        stored = json.loads(raw_items[0])
        assert stored["seq"] == 1
        assert stored["data"]["method"] == "tools/call"

    async def test_separate_streams_independent(self, store: RedisEventStore):
        """Different stream_ids maintain independent sequence counters."""
        msg = _make_jsonrpc_notification()
        eid_a = await store.store_event("stream-a", msg)
        eid_b = await store.store_event("stream-b", msg)

        assert eid_a == "stream-a:1"
        assert eid_b == "stream-b:1"


class TestReplayEventsAfter:
    """Tests for replay_events_after()."""

    async def test_replays_events_after_seq(self, store: RedisEventStore):
        """replay_events_after returns only events with seq > last_seq."""
        msg1 = _make_jsonrpc_notification("m1")
        msg2 = _make_jsonrpc_notification("m2")
        msg3 = _make_jsonrpc_notification("m3")
        await store.store_event("s1", msg1)
        await store.store_event("s1", msg2)
        await store.store_event("s1", msg3)

        replayed = []

        async def callback(event_message):
            replayed.append(event_message)

        stream_id = await store.replay_events_after("s1:1", callback)

        assert stream_id == "s1"
        assert len(replayed) == 2
        assert replayed[0].event_id == "s1:2"
        assert replayed[1].event_id == "s1:3"

    async def test_replay_with_seq_0_returns_all(self, store: RedisEventStore):
        """seq=0 means 'replay everything' since all stored seqs are > 0."""
        msg1 = _make_jsonrpc_notification("m1")
        msg2 = _make_jsonrpc_notification("m2")
        await store.store_event("s2", msg1)
        await store.store_event("s2", msg2)

        replayed = []

        async def callback(event_message):
            replayed.append(event_message)

        stream_id = await store.replay_events_after("s2:0", callback)

        assert stream_id == "s2"
        assert len(replayed) == 2

    async def test_replay_with_invalid_format_returns_none(self, store: RedisEventStore):
        """Invalid last_event_id format returns None without raising."""
        callback = AsyncMock()

        result = await store.replay_events_after("bad-format", callback)

        assert result is None
        callback.assert_not_awaited()

    async def test_replay_empty_stream(self, store: RedisEventStore):
        """Replaying a stream with no stored events calls callback zero times."""
        replayed = []

        async def callback(event_message):
            replayed.append(event_message)

        stream_id = await store.replay_events_after("no-stream:0", callback)

        assert stream_id == "no-stream"
        assert len(replayed) == 0


class TestAclose:
    """Tests for aclose()."""

    async def test_aclose_completes_without_error(self, store: RedisEventStore):
        """aclose() should close the Redis connection without error."""
        # Store something first to ensure the connection is active
        msg = _make_jsonrpc_notification()
        await store.store_event("s", msg)

        # Should not raise
        await store.aclose()
