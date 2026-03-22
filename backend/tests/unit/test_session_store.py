"""RedisEventStore のユニットテスト (fakeredis 使用、実 Redis 不要)"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio
from mcp.server.streamable_http import EventMessage, StreamId
from mcp.types import JSONRPCMessage, JSONRPCResponse


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_message(request_id: int = 1, result: dict | None = None) -> JSONRPCMessage:
    """テスト用の有効な JSONRPCMessage を生成する"""
    return JSONRPCMessage(
        root=JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result or {}),
    )


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_redis():
    """テストごとに独立した fakeredis インスタンスを生成する"""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def store(fake_redis):
    """fakeredis をバックエンドに持つ RedisEventStore を生成する"""
    with patch("app.mcp.session_store.aioredis.from_url", return_value=fake_redis):
        from app.mcp.session_store import RedisEventStore

        s = RedisEventStore()
    yield s


# ---------------------------------------------------------------------------
# TestStoreEvent
# ---------------------------------------------------------------------------

class TestStoreEvent:
    """store_event() の動作検証"""

    @pytest.mark.asyncio
    async def test_store_returns_event_id_format(self, store):
        """event_id が "{stream_id}:{seq}" 形式で返る"""
        event_id = await store.store_event("stream-abc", _make_message(1))
        assert event_id == "stream-abc:1"

    @pytest.mark.asyncio
    async def test_store_increments_sequence(self, store):
        """連続 store で seq が 1, 2, 3 とインクリメントされる"""
        ids = []
        for i in range(3):
            eid = await store.store_event("stream-inc", _make_message(i))
            ids.append(eid)
        assert ids == ["stream-inc:1", "stream-inc:2", "stream-inc:3"]

    @pytest.mark.asyncio
    async def test_store_persists_to_redis(self, store, fake_redis):
        """Redis リストにイベントが実際に格納される"""
        await store.store_event("stream-persist", _make_message(1))
        raw_items = await fake_redis.lrange("todo:mcp:events:stream-persist", 0, -1)
        assert len(raw_items) == 1
        stored = json.loads(raw_items[0])
        assert stored["seq"] == 1
        assert stored["data"]["jsonrpc"] == "2.0"
        assert stored["data"]["id"] == 1

    @pytest.mark.asyncio
    async def test_store_sets_ttl(self, store, fake_redis):
        """イベントキーとシーケンスキーに TTL が設定される"""
        await store.store_event("stream-ttl", _make_message(1))

        ttl_list = await fake_redis.ttl("todo:mcp:events:stream-ttl")
        ttl_seq = await fake_redis.ttl("todo:mcp:events:stream-ttl:seq")
        assert ttl_list > 0
        assert ttl_seq > 0
        # _TTL = 3600 なので、実行直後は 3600 付近のはず
        assert ttl_list <= 3600
        assert ttl_seq <= 3600

    @pytest.mark.asyncio
    async def test_store_trims_to_max_events(self, store, fake_redis):
        """_MAX_EVENTS_PER_STREAM (1000) を超えるとリストがトリムされる"""
        stream_id = "stream-trim"
        # 1005 件挿入
        for i in range(1005):
            await store.store_event(stream_id, _make_message(i))

        length = await fake_redis.llen(f"todo:mcp:events:{stream_id}")
        assert length == 1000


# ---------------------------------------------------------------------------
# TestReplayEventsAfter
# ---------------------------------------------------------------------------

class TestReplayEventsAfter:
    """replay_events_after() の動作検証"""

    @pytest.mark.asyncio
    async def test_replay_sends_events_after_id(self, store):
        """last_event_id 以降のイベントだけがコールバックに送られる"""
        stream_id = "stream-replay"
        for i in range(5):
            await store.store_event(stream_id, _make_message(i))

        received: list[EventMessage] = []
        callback = AsyncMock(side_effect=lambda em: received.append(em))

        # seq=2 以降 → seq 3, 4, 5 が送られるはず
        result = await store.replay_events_after(f"{stream_id}:2", callback)

        assert result == StreamId(stream_id)
        assert callback.await_count == 3
        event_ids = [r.event_id for r in received]
        assert event_ids == [
            f"{stream_id}:3",
            f"{stream_id}:4",
            f"{stream_id}:5",
        ]

    @pytest.mark.asyncio
    async def test_replay_returns_stream_id(self, store):
        """正常時に StreamId を返す"""
        stream_id = "stream-ret"
        await store.store_event(stream_id, _make_message(1))

        callback = AsyncMock()
        result = await store.replay_events_after(f"{stream_id}:0", callback)
        assert result == StreamId(stream_id)

    @pytest.mark.asyncio
    async def test_replay_invalid_event_id_returns_none(self, store):
        """不正な event_id フォーマットで None を返す"""
        callback = AsyncMock()

        # コロンが無い
        assert await store.replay_events_after("no-colon", callback) is None
        # seq 部分が数値でない
        assert await store.replay_events_after("stream:abc", callback) is None

        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replay_no_events_after_id(self, store):
        """last_seq 以降にイベントが無い場合、コールバックは呼ばれないが stream_id は返る"""
        stream_id = "stream-noop"
        await store.store_event(stream_id, _make_message(1))
        await store.store_event(stream_id, _make_message(2))

        callback = AsyncMock()
        result = await store.replay_events_after(f"{stream_id}:2", callback)

        assert result == StreamId(stream_id)
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replay_all_events(self, store):
        """last_seq=0 で全イベントがリプレイされる"""
        stream_id = "stream-all"
        for i in range(3):
            await store.store_event(stream_id, _make_message(i))

        received: list[EventMessage] = []
        callback = AsyncMock(side_effect=lambda em: received.append(em))

        result = await store.replay_events_after(f"{stream_id}:0", callback)

        assert result == StreamId(stream_id)
        assert callback.await_count == 3
        event_ids = [r.event_id for r in received]
        assert event_ids == [
            f"{stream_id}:1",
            f"{stream_id}:2",
            f"{stream_id}:3",
        ]


# ---------------------------------------------------------------------------
# TestRoundTrip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """store → replay のラウンドトリップ検証"""

    @pytest.mark.asyncio
    async def test_store_and_replay_roundtrip(self, store):
        """格納したメッセージがリプレイ時にデシリアライズされて一致する"""
        stream_id = "stream-rt"
        messages = [_make_message(i, {"value": f"data-{i}"}) for i in range(3)]

        for msg in messages:
            await store.store_event(stream_id, msg)

        received: list[EventMessage] = []
        callback = AsyncMock(side_effect=lambda em: received.append(em))
        await store.replay_events_after(f"{stream_id}:0", callback)

        assert len(received) == 3
        for i, em in enumerate(received):
            assert em.message.root.jsonrpc == "2.0"
            assert em.message.root.id == i
            assert em.message.root.result == {"value": f"data-{i}"}

    @pytest.mark.asyncio
    async def test_store_multiple_streams_independent(self, store):
        """異なる stream_id のイベントは互いに独立している"""
        await store.store_event("stream-A", _make_message(1, {"from": "A"}))
        await store.store_event("stream-A", _make_message(2, {"from": "A"}))
        await store.store_event("stream-B", _make_message(10, {"from": "B"}))

        # stream-A をリプレイ
        received_a: list[EventMessage] = []
        cb_a = AsyncMock(side_effect=lambda em: received_a.append(em))
        result_a = await store.replay_events_after("stream-A:0", cb_a)
        assert result_a == StreamId("stream-A")
        assert len(received_a) == 2

        # stream-B をリプレイ
        received_b: list[EventMessage] = []
        cb_b = AsyncMock(side_effect=lambda em: received_b.append(em))
        result_b = await store.replay_events_after("stream-B:0", cb_b)
        assert result_b == StreamId("stream-B")
        assert len(received_b) == 1
        assert received_b[0].message.root.id == 10


# ---------------------------------------------------------------------------
# TestKeyFormat
# ---------------------------------------------------------------------------

class TestKeyFormat:
    """Redis キーフォーマットの検証"""

    @pytest.mark.asyncio
    async def test_key_prefix(self, store):
        """_key() が "todo:mcp:events:" プレフィックスを使う"""
        key = store._key("my-stream")
        assert key == "todo:mcp:events:my-stream"

    @pytest.mark.asyncio
    async def test_key_with_special_characters(self, store):
        """stream_id に UUID 等が含まれても正しくキーを生成する"""
        stream_id = "550e8400-e29b-41d4-a716-446655440000"
        key = store._key(stream_id)
        assert key == f"todo:mcp:events:{stream_id}"
