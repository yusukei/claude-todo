"""MCP ツール使用状況計測のテスト.

タスク 69d5b9f58e61d9be531aa532。
- バケット upsert ロジック (`_record_bucket`)
- 個別イベント insert (`_record_event`)
- ミドルウェア on_call_tool の成功/失敗パス
- 集計 API (summary / unused / errors / health) の認可と動作
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.mcp.middleware.usage_tracking import (
    UsageTrackingMiddleware,
    _floor_to_hour,
    _record_bucket,
    _record_event,
)
from app.models import McpApiFeedback, McpToolCallEvent, McpToolUsageBucket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_hour() -> datetime:
    return _floor_to_hour(datetime.now(UTC))


# ---------------------------------------------------------------------------
# _record_bucket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_bucket_inserts_new_doc():
    hour = _now_hour()
    await _record_bucket(
        tool_name="create_task",
        api_key_id="abc",
        hour=hour,
        duration_ms=120,
        success=True,
        arg_size=42,
    )
    docs = await McpToolUsageBucket.find({}).to_list()
    assert len(docs) == 1
    d = docs[0]
    assert d.tool_name == "create_task"
    assert d.api_key_id == "abc"
    assert d.call_count == 1
    assert d.error_count == 0
    assert d.duration_ms_sum == 120
    assert d.duration_ms_max == 120
    assert d.arg_size_sum == 42


@pytest.mark.asyncio
async def test_record_bucket_increments_existing():
    hour = _now_hour()
    for i, dur in enumerate([100, 200, 50]):
        await _record_bucket(
            tool_name="list_tasks",
            api_key_id="key1",
            hour=hour,
            duration_ms=dur,
            success=(i != 1),  # 2 番目だけ失敗
            arg_size=10,
        )
    docs = await McpToolUsageBucket.find({}).to_list()
    assert len(docs) == 1
    d = docs[0]
    assert d.call_count == 3
    assert d.error_count == 1
    assert d.duration_ms_sum == 350
    assert d.duration_ms_max == 200
    assert d.arg_size_sum == 30


@pytest.mark.asyncio
async def test_record_bucket_separates_by_key_and_hour():
    hour1 = _now_hour()
    hour2 = hour1 - timedelta(hours=1)
    await _record_bucket(tool_name="t", api_key_id="k1", hour=hour1, duration_ms=1, success=True, arg_size=0)
    await _record_bucket(tool_name="t", api_key_id="k2", hour=hour1, duration_ms=1, success=True, arg_size=0)
    await _record_bucket(tool_name="t", api_key_id="k1", hour=hour2, duration_ms=1, success=True, arg_size=0)
    assert await McpToolUsageBucket.find({}).count() == 3


# ---------------------------------------------------------------------------
# _record_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_event_persists_minimal_fields():
    await _record_event(
        tool_name="search_tasks",
        api_key_id="abc",
        duration_ms=3000,
        success=False,
        error_class="ValueError",
        arg_size=128,
        reason="error",
    )
    docs = await McpToolCallEvent.find({}).to_list()
    assert len(docs) == 1
    d = docs[0]
    assert d.tool_name == "search_tasks"
    assert d.success is False
    assert d.error_class == "ValueError"
    assert d.duration_ms == 3000
    assert d.reason == "error"


# ---------------------------------------------------------------------------
# UsageTrackingMiddleware
# ---------------------------------------------------------------------------


class _DummyMessage:
    def __init__(self, name: str, arguments: dict | None = None):
        self.name = name
        self.arguments = arguments or {}


class _DummyContext:
    def __init__(self, message):
        self.message = message
        self.method = "tools/call"
        self.type = "request"


@pytest.mark.asyncio
async def test_middleware_records_success_call(monkeypatch):
    # サンプリングを 100% にして必ず event が出るようにする
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "MCP_USAGE_SAMPLING_RATE", 1.0)

    mw = UsageTrackingMiddleware()
    ctx = _DummyContext(_DummyMessage("ping", {"a": 1}))

    async def _next(_c):
        return "ok"

    result = await mw.on_call_tool(ctx, _next)
    assert result == "ok"

    # asyncio.create_task で非同期書き込み → 完了を待つ
    import asyncio

    await asyncio.sleep(0.05)

    buckets = await McpToolUsageBucket.find({}).to_list()
    assert len(buckets) == 1
    assert buckets[0].tool_name == "ping"
    assert buckets[0].call_count == 1
    assert buckets[0].error_count == 0

    events = await McpToolCallEvent.find({}).to_list()
    assert len(events) == 1
    assert events[0].reason == "sampled"
    assert events[0].success is True


@pytest.mark.asyncio
async def test_middleware_records_failure_event(monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "MCP_USAGE_SAMPLING_RATE", 0.0)

    mw = UsageTrackingMiddleware()
    ctx = _DummyContext(_DummyMessage("create_task", {"x": "y"}))

    async def _next(_c):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await mw.on_call_tool(ctx, _next)

    import asyncio

    await asyncio.sleep(0.05)

    buckets = await McpToolUsageBucket.find({}).to_list()
    assert len(buckets) == 1
    assert buckets[0].error_count == 1

    events = await McpToolCallEvent.find({}).to_list()
    assert len(events) == 1
    assert events[0].success is False
    assert events[0].error_class == "RuntimeError"
    assert events[0].reason == "error"


@pytest.mark.asyncio
async def test_middleware_disabled_short_circuits(monkeypatch):
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "MCP_USAGE_TRACKING_ENABLED", False)

    mw = UsageTrackingMiddleware()
    ctx = _DummyContext(_DummyMessage("ping"))

    async def _next(_c):
        return "ok"

    result = await mw.on_call_tool(ctx, _next)
    assert result == "ok"

    import asyncio

    await asyncio.sleep(0.05)

    assert await McpToolUsageBucket.find({}).count() == 0
    assert await McpToolCallEvent.find({}).count() == 0


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_buckets():
    """テスト用にバケットを直接挿入."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    docs = [
        McpToolUsageBucket(
            tool_name="hot_tool",
            api_key_id="k1",
            hour=now,
            call_count=100,
            error_count=2,
            duration_ms_sum=5000,
            duration_ms_max=300,
            arg_size_sum=10000,
        ),
        McpToolUsageBucket(
            tool_name="cold_tool",
            api_key_id="k1",
            hour=now - timedelta(hours=2),
            call_count=3,
            error_count=0,
            duration_ms_sum=90,
            duration_ms_max=40,
            arg_size_sum=300,
        ),
    ]
    for d in docs:
        await d.insert()
    return docs


@pytest.mark.asyncio
async def test_summary_requires_admin(client, user_headers):
    res = await client.get("/api/v1/mcp/usage/summary", headers=user_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_summary_aggregates_buckets(client, admin_headers, seed_buckets):
    res = await client.get("/api/v1/mcp/usage/summary?days=30", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    by_name = {r["tool_name"]: r for r in body["items"]}
    assert by_name["hot_tool"]["count"] == 100
    assert by_name["hot_tool"]["error_count"] == 2
    assert by_name["hot_tool"]["error_rate"] == pytest.approx(0.02)
    assert by_name["hot_tool"]["avg_duration_ms"] == pytest.approx(50.0)
    assert by_name["cold_tool"]["count"] == 3
    assert body["total_calls"] >= 103


@pytest.mark.asyncio
async def test_unused_endpoint_returns_zero_call_tools(client, admin_headers, seed_buckets):
    res = await client.get("/api/v1/mcp/usage/unused?days=30", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    # 実 MCP インスタンスのツール一覧が空でも壊れない (registered_count=0 でも OK)
    assert "unused" in body
    assert isinstance(body["unused"], list)
    assert body["used_count"] >= 2  # hot_tool / cold_tool


@pytest.mark.asyncio
async def test_errors_endpoint_returns_recent_events(client, admin_headers):
    await McpToolCallEvent(
        tool_name="failing_tool",
        api_key_id="k1",
        duration_ms=4321,
        success=False,
        error_class="TimeoutError",
        arg_size_bytes=99,
        reason="error",
    ).insert()
    res = await client.get("/api/v1/mcp/usage/errors?only_errors=true", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["tool_name"] == "failing_tool"
    assert body["items"][0]["error_class"] == "TimeoutError"
    # PII 観点: error_class 以外の本文は保存されていない
    assert "error_message" not in body["items"][0]


@pytest.mark.asyncio
async def test_health_endpoint(client, admin_headers):
    res = await client.get("/api/v1/mcp/usage/health", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert "enabled" in body
    assert "sampling_rate" in body
    assert "slow_call_ms" in body


# ---------------------------------------------------------------------------
# Phase 1 拡張エンドポイント
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_rich_data():
    """dashboard / tools / co-occurrence テスト用の充実したデータ."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    buckets = [
        McpToolUsageBucket(
            tool_name="list_tasks",
            api_key_id="k1",
            hour=now,
            call_count=200,
            error_count=3,
            duration_ms_sum=20000,
            duration_ms_max=500,
            arg_size_sum=8000,
        ),
        McpToolUsageBucket(
            tool_name="list_tasks",
            api_key_id="k2",
            hour=now,
            call_count=50,
            error_count=1,
            duration_ms_sum=4000,
            duration_ms_max=300,
            arg_size_sum=2000,
        ),
        McpToolUsageBucket(
            tool_name="get_task_context",
            api_key_id="k1",
            hour=now,
            call_count=80,
            error_count=0,
            duration_ms_sum=12000,
            duration_ms_max=800,
            arg_size_sum=4000,
        ),
        McpToolUsageBucket(
            tool_name="create_bookmark",
            api_key_id="k1",
            hour=now,
            call_count=10,
            error_count=2,
            duration_ms_sum=5000,
            duration_ms_max=1200,
            arg_size_sum=3000,
        ),
        McpToolUsageBucket(
            tool_name="list_tasks",
            api_key_id="k1",
            hour=now - timedelta(days=1),
            call_count=180,
            error_count=0,
            duration_ms_sum=15000,
            duration_ms_max=400,
            arg_size_sum=7000,
        ),
    ]
    for b in buckets:
        await b.insert()

    events = [
        McpToolCallEvent(
            tool_name="list_tasks",
            api_key_id="k1",
            duration_ms=50,
            success=True,
            reason="sampled",
            ts=now,
        ),
        McpToolCallEvent(
            tool_name="list_tasks",
            api_key_id="k1",
            duration_ms=150,
            success=True,
            reason="sampled",
            ts=now,
        ),
        McpToolCallEvent(
            tool_name="list_tasks",
            api_key_id="k1",
            duration_ms=500,
            success=False,
            error_class="TimeoutError",
            reason="error",
            ts=now,
        ),
        McpToolCallEvent(
            tool_name="create_bookmark",
            api_key_id="k1",
            duration_ms=1200,
            success=False,
            error_class="ValidationError",
            reason="error",
            ts=now,
        ),
    ]
    for e in events:
        await e.insert()

    return buckets, events


@pytest.mark.asyncio
async def test_dashboard_returns_kpis(client, admin_headers, seed_rich_data):
    res = await client.get("/api/v1/mcp/usage/dashboard?days=30", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()

    assert "period" in body
    assert body["total_calls"] >= 520  # 200+50+80+10+180
    assert body["total_errors"] >= 6
    assert body["error_rate"] > 0
    assert body["unique_tools_used"] >= 3
    assert body["total_tools_available"] >= 0
    assert "unused_tools" in body
    assert "busiest_hour" in body
    assert "top_tools" in body
    assert len(body["top_tools"]) > 0
    assert body["top_tools"][0]["tool_name"] == "list_tasks"
    assert "top_errors" in body


@pytest.mark.asyncio
async def test_dashboard_requires_admin(client, user_headers):
    res = await client.get("/api/v1/mcp/usage/dashboard", headers=user_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_tools_ranking(client, admin_headers, seed_rich_data):
    res = await client.get("/api/v1/mcp/usage/tools?days=30", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    items = body["items"]

    by_name = {r["tool_name"]: r for r in items}
    assert by_name["list_tasks"]["call_count"] == 430  # 200+50+180
    assert by_name["list_tasks"]["category"] == "tasks"
    assert by_name["list_tasks"]["unique_callers"] == 2  # k1, k2
    assert by_name["create_bookmark"]["category"] == "bookmarks"

    # デフォルトは call_count desc
    assert items[0]["call_count"] >= items[-1]["call_count"]


@pytest.mark.asyncio
async def test_tools_ranking_category_filter(client, admin_headers, seed_rich_data):
    res = await client.get(
        "/api/v1/mcp/usage/tools?days=30&category=bookmarks", headers=admin_headers
    )
    assert res.status_code == 200
    items = res.json()["items"]
    for item in items:
        assert item["category"] == "bookmarks"


@pytest.mark.asyncio
async def test_tools_ranking_sort(client, admin_headers, seed_rich_data):
    res = await client.get(
        "/api/v1/mcp/usage/tools?days=30&sort=error_count&order=desc",
        headers=admin_headers,
    )
    assert res.status_code == 200
    items = res.json()["items"]
    error_counts = [i["error_count"] for i in items]
    assert error_counts == sorted(error_counts, reverse=True)


@pytest.mark.asyncio
async def test_tool_detail(client, admin_headers, seed_rich_data):
    res = await client.get("/api/v1/mcp/usage/tools/list_tasks?days=30", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()

    assert body["tool_name"] == "list_tasks"
    assert body["category"] == "tasks"
    assert body["total_calls"] == 430
    assert body["total_errors"] == 4  # 3+1
    assert body["error_rate"] > 0
    assert len(body["daily_breakdown"]) >= 1
    assert "callers" in body
    assert len(body["callers"]) == 2  # k1, k2

    # レイテンシ分布
    ld = body["latency_distribution"]
    assert ld["sample_size"] == 3  # 3 events for list_tasks
    assert ld["p50"] is not None

    # エラー
    assert len(body["recent_errors"]) >= 1
    assert body["recent_errors"][0]["error_class"] == "TimeoutError"


@pytest.mark.asyncio
async def test_tool_detail_empty(client, admin_headers):
    res = await client.get(
        "/api/v1/mcp/usage/tools/nonexistent_tool?days=30", headers=admin_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_calls"] == 0
    assert body["latency_distribution"]["sample_size"] == 0


@pytest.mark.asyncio
async def test_co_occurrence(client, admin_headers, seed_rich_data):
    # k1 が同じ hour に list_tasks, get_task_context, create_bookmark を使っている
    res = await client.get(
        "/api/v1/mcp/usage/co-occurrence?days=30&min_count=1", headers=admin_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert "pairs" in body

    # k1 の now バケットに 3 ツール → 3 ペア: (create_bookmark, get_task_context),
    # (create_bookmark, list_tasks), (get_task_context, list_tasks)
    pair_keys = {(p["tool_a"], p["tool_b"]) for p in body["pairs"]}
    assert len(pair_keys) >= 3


@pytest.mark.asyncio
async def test_co_occurrence_min_count_filter(client, admin_headers, seed_rich_data):
    res = await client.get(
        "/api/v1/mcp/usage/co-occurrence?days=30&min_count=100", headers=admin_headers
    )
    assert res.status_code == 200
    assert len(res.json()["pairs"]) == 0


@pytest.mark.asyncio
async def test_trends_daily(client, admin_headers, seed_rich_data):
    res = await client.get("/api/v1/mcp/usage/trends?days=30&granularity=daily", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["granularity"] == "daily"
    assert "series" in body
    assert "list_tasks" in body["series"]
    # list_tasks は 2 日分のデータがある
    assert len(body["series"]["list_tasks"]) >= 2


@pytest.mark.asyncio
async def test_trends_with_tool_filter(client, admin_headers, seed_rich_data):
    res = await client.get(
        "/api/v1/mcp/usage/trends?days=30&tools=create_bookmark", headers=admin_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tools_filter"] == ["create_bookmark"]
    assert "create_bookmark" in body["series"]
    assert "list_tasks" not in body["series"]


@pytest.mark.asyncio
async def test_trends_hourly(client, admin_headers, seed_rich_data):
    res = await client.get(
        "/api/v1/mcp/usage/trends?days=7&granularity=hourly", headers=admin_headers
    )
    assert res.status_code == 200
    assert res.json()["granularity"] == "hourly"


# ---------------------------------------------------------------------------
# API 改善リクエスト (feedback)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_feedback():
    """テスト用のフィードバックデータ."""
    docs = [
        McpApiFeedback(
            tool_name="list_tasks",
            request_type="missing_param",
            description="include_subtasks パラメータが欲しい",
            status="open",
            submitted_by="k1",
        ),
        McpApiFeedback(
            tool_name="list_tasks",
            request_type="performance",
            description="大量タスク時のレスポンスが遅い",
            status="open",
            submitted_by="k2",
        ),
        McpApiFeedback(
            tool_name="get_task",
            request_type="merge",
            description="get_task と get_subtasks を統合したい",
            related_tools=["get_subtasks"],
            status="open",
            submitted_by="k1",
        ),
        McpApiFeedback(
            tool_name="search_tasks",
            request_type="bug",
            description="日本語検索でヒットしない場合がある",
            status="accepted",
            submitted_by="k1",
        ),
        McpApiFeedback(
            tool_name="create_bookmark",
            request_type="deprecate",
            description="clip_bookmark に統合すべき",
            status="done",
            submitted_by="k2",
        ),
    ]
    for d in docs:
        await d.insert()
    return docs


@pytest.mark.asyncio
async def test_feedback_list(client, admin_headers, seed_feedback):
    res = await client.get("/api/v1/mcp/usage/feedback", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5


@pytest.mark.asyncio
async def test_feedback_list_filter_by_status(client, admin_headers, seed_feedback):
    res = await client.get(
        "/api/v1/mcp/usage/feedback?status=open", headers=admin_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    for item in body["items"]:
        assert item["status"] == "open"


@pytest.mark.asyncio
async def test_feedback_list_filter_by_tool(client, admin_headers, seed_feedback):
    res = await client.get(
        "/api/v1/mcp/usage/feedback?tool_name=list_tasks", headers=admin_headers
    )
    assert res.status_code == 200
    assert res.json()["total"] == 2


@pytest.mark.asyncio
async def test_feedback_list_requires_admin(client, user_headers):
    res = await client.get("/api/v1/mcp/usage/feedback", headers=user_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_feedback_summary(client, admin_headers, seed_feedback):
    res = await client.get("/api/v1/mcp/usage/feedback/summary", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()

    assert body["by_status"]["open"] == 3
    assert body["by_status"]["accepted"] == 1
    assert body["by_status"]["done"] == 1

    # by_type はリスト形式
    type_map = {r["request_type"]: r["count"] for r in body["by_type"]}
    assert type_map["missing_param"] == 1
    assert type_map["merge"] == 1

    # top_tools_with_open_requests
    assert len(body["top_tools_with_open_requests"]) >= 1
    assert body["top_tools_with_open_requests"][0]["tool_name"] == "list_tasks"
    assert body["top_tools_with_open_requests"][0]["open_count"] == 2


@pytest.mark.asyncio
async def test_feedback_update_status(client, admin_headers, seed_feedback):
    # open のフィードバックを取得
    res = await client.get("/api/v1/mcp/usage/feedback?status=open", headers=admin_headers)
    fb_id = res.json()["items"][0]["id"]

    # ステータスを accepted に更新
    res = await client.patch(
        f"/api/v1/mcp/usage/feedback/{fb_id}?status=accepted", headers=admin_headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_feedback_update_votes(client, admin_headers, seed_feedback):
    res = await client.get("/api/v1/mcp/usage/feedback?status=open", headers=admin_headers)
    fb_id = res.json()["items"][0]["id"]

    res = await client.patch(
        f"/api/v1/mcp/usage/feedback/{fb_id}?votes_delta=1", headers=admin_headers
    )
    assert res.status_code == 200
    assert res.json()["votes"] == 2  # 初期値1 + delta 1


@pytest.mark.asyncio
async def test_feedback_update_invalid_status(client, admin_headers, seed_feedback):
    res = await client.get("/api/v1/mcp/usage/feedback?status=open", headers=admin_headers)
    fb_id = res.json()["items"][0]["id"]

    res = await client.patch(
        f"/api/v1/mcp/usage/feedback/{fb_id}?status=invalid", headers=admin_headers
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_feedback_update_not_found(client, admin_headers):
    res = await client.patch(
        "/api/v1/mcp/usage/feedback/000000000000000000000000?status=done",
        headers=admin_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_includes_feedback(client, admin_headers, seed_feedback):
    res = await client.get("/api/v1/mcp/usage/dashboard?days=30", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()

    assert "feedback" in body
    assert body["feedback"]["open_count"] == 3
    assert len(body["feedback"]["top_requested_tools"]) >= 1
