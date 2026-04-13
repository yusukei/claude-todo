"""MCP ツール使用状況の集計エンドポイント.

タスク 69d5b9f58e61d9be531aa532。
spec "MCP サーバー仕様 > REST API（集計エンドポイント）" を参照。

すべて管理者認証必須。
レスポンスフィールド名は `count` を維持 (フロントとの契約) するが、
内部の Mongo フィールドは `call_count` (Beanie の `Document.count` と衝突するため)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ....core.deps import get_admin_user
from ....mcp.server import mcp
from ....models import McpApiFeedback, McpToolCallEvent, McpToolUsageBucket, User

router = APIRouter(prefix="/mcp/usage", tags=["mcp-usage"])

# ---------------------------------------------------------------------------
# ツール名 → カテゴリのマッピング
# ---------------------------------------------------------------------------
# MCP ツールモジュール (backend/app/mcp/tools/*.py) のファイル名をカテゴリとする。
# ツール名の prefix で自動判定する。

# ツール名に含まれるキーワードでカテゴリを判定する。
# 順序重要: より具体的なパターンを先に。
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    # docsites は documents より先に判定
    ("docsite", "docsites"),
    ("docpage", "docsites"),
    ("document", "documents"),
    # bookmarks
    ("bookmark", "bookmarks"),
    # tasks (comment は tasks に属する)
    ("task", "tasks"),
    ("comment", "tasks"),
    ("subtask", "tasks"),
    ("approved", "tasks"),
    ("overdue", "tasks"),
    ("review_task", "tasks"),
    ("work_context", "tasks"),
    ("bulk_complete", "tasks"),
    ("bulk_archive", "tasks"),
    # knowledge
    ("knowledge", "knowledge"),
    # projects
    ("project", "projects"),
    ("list_users", "projects"),
    ("list_tags", "projects"),
    # secrets
    ("secret", "secrets"),
    # remote
    ("remote", "remote"),
    # setup
    ("setup", "setup"),
]


def _tool_category(tool_name: str) -> str:
    """ツール名からカテゴリを推定する."""
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword in tool_name:
            return category
    return "other"


class ToolSortField(str, Enum):
    call_count = "call_count"
    error_count = "error_count"
    error_rate = "error_rate"
    avg_duration_ms = "avg_duration_ms"
    last_called_at = "last_called_at"


async def _registered_tool_names() -> list[str]:
    """FastMCP インスタンスに登録されているツール名一覧.

    `mcp.list_tools()` は middleware を経由してしまうため、
    `run_middleware=False` で素のリストを取得する。
    """
    try:
        tools = await mcp.list_tools(run_middleware=False)
    except Exception:
        return []
    names: list[str] = []
    for t in tools:
        name = getattr(t, "name", None)
        if name:
            names.append(name)
    return sorted(set(names))


@router.get("/summary")
async def usage_summary(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_admin_user),
) -> dict:
    """ツール別の総呼び出し数 / エラー率 / 平均応答時間 を返す.

    過去 `days` 日のバケットを集計し、未呼び出しツールも 0 件で含める。
    """
    since = datetime.now(UTC) - timedelta(days=days)

    pipeline = [
        {"$match": {"hour": {"$gte": since}}},
        {
            "$group": {
                "_id": "$tool_name",
                "count": {"$sum": "$call_count"},
                "error_count": {"$sum": "$error_count"},
                "duration_ms_sum": {"$sum": "$duration_ms_sum"},
                "duration_ms_max": {"$max": "$duration_ms_max"},
                "arg_size_sum": {"$sum": "$arg_size_sum"},
            }
        },
    ]
    rows = await McpToolUsageBucket.get_motor_collection().aggregate(pipeline).to_list(length=None)

    by_tool: dict[str, dict] = {}
    for row in rows:
        count = int(row.get("count", 0)) or 0
        errors = int(row.get("error_count", 0)) or 0
        d_sum = int(row.get("duration_ms_sum", 0)) or 0
        by_tool[row["_id"]] = {
            "tool_name": row["_id"],
            "count": count,
            "error_count": errors,
            "error_rate": (errors / count) if count else 0.0,
            "avg_duration_ms": (d_sum / count) if count else 0.0,
            "max_duration_ms": int(row.get("duration_ms_max", 0)) or 0,
            "arg_size_sum": int(row.get("arg_size_sum", 0)) or 0,
        }

    # 登録済みだが計測実績ゼロのツールも 0 行で含める
    for name in await _registered_tool_names():
        by_tool.setdefault(
            name,
            {
                "tool_name": name,
                "count": 0,
                "error_count": 0,
                "error_rate": 0.0,
                "avg_duration_ms": 0.0,
                "max_duration_ms": 0,
                "arg_size_sum": 0,
            },
        )

    items = sorted(by_tool.values(), key=lambda r: (-r["count"], r["tool_name"]))
    return {
        "since": since.isoformat(),
        "days": days,
        "total_calls": sum(r["count"] for r in items),
        "total_errors": sum(r["error_count"] for r in items),
        "tool_count": len(items),
        "items": items,
    }


@router.get("/unused")
async def usage_unused(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_admin_user),
) -> dict:
    """過去 N 日で呼び出し数がゼロのツール一覧 (=削除候補)."""
    since = datetime.now(UTC) - timedelta(days=days)
    used_names = await McpToolUsageBucket.get_motor_collection().distinct(
        "tool_name", {"hour": {"$gte": since}}
    )
    used = set(used_names)
    registered = await _registered_tool_names()
    unused = [name for name in registered if name not in used]
    return {
        "since": since.isoformat(),
        "days": days,
        "registered_count": len(registered),
        "used_count": len(used),
        "unused_count": len(unused),
        "unused": unused,
    }


@router.get("/timeseries")
async def usage_timeseries(
    tool: str = Query(..., min_length=1),
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(get_admin_user),
) -> dict:
    """指定ツールの hour 粒度時系列データ."""
    since = datetime.now(UTC) - timedelta(days=days)
    pipeline = [
        {"$match": {"tool_name": tool, "hour": {"$gte": since}}},
        {
            "$group": {
                "_id": "$hour",
                "count": {"$sum": "$call_count"},
                "error_count": {"$sum": "$error_count"},
                "duration_ms_sum": {"$sum": "$duration_ms_sum"},
                "duration_ms_max": {"$max": "$duration_ms_max"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    rows = await McpToolUsageBucket.get_motor_collection().aggregate(pipeline).to_list(length=None)
    points = [
        {
            "hour": (row["_id"].isoformat() if isinstance(row["_id"], datetime) else row["_id"]),
            "count": int(row.get("count", 0)) or 0,
            "error_count": int(row.get("error_count", 0)) or 0,
            "avg_duration_ms": (
                int(row["duration_ms_sum"]) / int(row["count"])
                if row.get("count")
                else 0.0
            ),
            "max_duration_ms": int(row.get("duration_ms_max", 0)) or 0,
        }
        for row in rows
    ]
    return {"tool": tool, "days": days, "points": points}


@router.get("/errors")
async def usage_errors(
    tool: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    only_errors: bool = Query(False),
    _: User = Depends(get_admin_user),
) -> dict:
    """個別イベントログ (エラー / スローコール / サンプリング) を返す."""
    query: dict = {}
    if tool:
        query["tool_name"] = tool
    if only_errors:
        query["success"] = False

    docs = (
        await McpToolCallEvent.find(query)
        .sort("-ts")
        .limit(limit)
        .to_list()
    )
    return {
        "items": [
            {
                "id": str(d.id),
                "ts": d.ts.isoformat(),
                "tool_name": d.tool_name,
                "api_key_id": d.api_key_id,
                "duration_ms": d.duration_ms,
                "success": d.success,
                "error_class": d.error_class,
                "arg_size_bytes": d.arg_size_bytes,
                "reason": d.reason,
            }
            for d in docs
        ]
    }


@router.get("/health")
async def usage_health(_: User = Depends(get_admin_user)) -> dict:
    """計測機能のヘルスチェック (有効/無効・サンプリング率など)."""
    from ....core.config import settings as _s

    bucket_count = await McpToolUsageBucket.get_motor_collection().estimated_document_count()
    event_count = await McpToolCallEvent.get_motor_collection().estimated_document_count()
    return {
        "enabled": _s.MCP_USAGE_TRACKING_ENABLED,
        "sampling_rate": _s.MCP_USAGE_SAMPLING_RATE,
        "slow_call_ms": _s.MCP_USAGE_SLOW_CALL_MS,
        "registered_tools": len(await _registered_tool_names()),
        "bucket_doc_count": bucket_count,
        "event_doc_count": event_count,
    }


# ---------------------------------------------------------------------------
# Phase 1: 拡張エンドポイント
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def usage_dashboard(
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_admin_user),
) -> dict:
    """ダッシュボード用の全体サマリー.

    `/summary` がツール別リストを返すのに対し、こちらはハイレベルな KPI を返す:
    総コール数、エラー率、未使用ツール数、最繁忙時間帯、Top ツール/エラー。
    """
    since = datetime.now(UTC) - timedelta(days=days)
    col = McpToolUsageBucket.get_motor_collection()

    # --- ツール別集計 ---
    tool_pipeline = [
        {"$match": {"hour": {"$gte": since}}},
        {
            "$group": {
                "_id": "$tool_name",
                "call_count": {"$sum": "$call_count"},
                "error_count": {"$sum": "$error_count"},
                "duration_ms_sum": {"$sum": "$duration_ms_sum"},
                "unique_callers": {"$addToSet": "$api_key_id"},
                "last_hour": {"$max": "$hour"},
            }
        },
    ]
    tool_rows = await col.aggregate(tool_pipeline).to_list(length=None)

    # --- 最繁忙時間帯 ---
    busiest_pipeline = [
        {"$match": {"hour": {"$gte": since}}},
        {
            "$group": {
                "_id": "$hour",
                "total": {"$sum": "$call_count"},
            }
        },
        {"$sort": {"total": -1}},
        {"$limit": 1},
    ]
    busiest_rows = await col.aggregate(busiest_pipeline).to_list(length=1)

    # 集計
    total_calls = 0
    total_errors = 0
    tool_stats: list[dict] = []
    used_names: set[str] = set()

    for row in tool_rows:
        cc = int(row.get("call_count", 0))
        ec = int(row.get("error_count", 0))
        ds = int(row.get("duration_ms_sum", 0))
        callers = row.get("unique_callers", [])
        # None が含まれる場合を除外してカウント
        unique_count = len([c for c in callers if c is not None])
        total_calls += cc
        total_errors += ec
        used_names.add(row["_id"])
        tool_stats.append({
            "tool_name": row["_id"],
            "category": _tool_category(row["_id"]),
            "call_count": cc,
            "error_count": ec,
            "error_rate": (ec / cc) if cc else 0.0,
            "avg_duration_ms": round(ds / cc, 1) if cc else 0.0,
            "unique_callers": unique_count,
            "last_called_at": (
                row["last_hour"].isoformat()
                if isinstance(row.get("last_hour"), datetime)
                else None
            ),
        })

    registered = await _registered_tool_names()
    unused = sorted(set(registered) - used_names)

    # Top ツール (呼び出し数順 Top 10)
    top_tools = sorted(tool_stats, key=lambda r: -r["call_count"])[:10]
    # Top エラー (エラー数順、0 を除く)
    top_errors = sorted(
        [t for t in tool_stats if t["error_count"] > 0],
        key=lambda r: -r["error_count"],
    )[:10]

    busiest_hour = None
    if busiest_rows:
        bh = busiest_rows[0]["_id"]
        busiest_hour = bh.isoformat() if isinstance(bh, datetime) else str(bh)

    # --- フィードバック集計 ---
    feedback_col = McpApiFeedback.get_motor_collection()
    feedback_pipeline = [
        {"$match": {"status": "open"}},
        {"$group": {"_id": "$tool_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    fb_rows = await feedback_col.aggregate(feedback_pipeline).to_list(length=10)
    open_feedback_count = await McpApiFeedback.find({"status": "open"}).count()

    return {
        "period": {
            "from": since.isoformat(),
            "to": datetime.now(UTC).isoformat(),
            "days": days,
        },
        "total_calls": total_calls,
        "total_errors": total_errors,
        "error_rate": (total_errors / total_calls) if total_calls else 0.0,
        "unique_tools_used": len(used_names),
        "total_tools_available": len(registered),
        "unused_tool_count": len(unused),
        "unused_tools": unused,
        "busiest_hour": busiest_hour,
        "avg_latency_ms": round(
            sum(t["avg_duration_ms"] * t["call_count"] for t in tool_stats) / total_calls, 1
        ) if total_calls else 0.0,
        "top_tools": top_tools,
        "top_errors": top_errors,
        "feedback": {
            "open_count": open_feedback_count,
            "top_requested_tools": [
                {"tool_name": r["_id"], "open_requests": int(r["count"])}
                for r in fb_rows
            ],
        },
    }


@router.get("/tools")
async def usage_tools(
    days: int = Query(30, ge=1, le=365),
    category: str | None = Query(None, description="カテゴリでフィルタ (tasks, bookmarks, etc.)"),
    sort: ToolSortField = Query(ToolSortField.call_count, description="ソートフィールド"),
    order: Literal["asc", "desc"] = Query("desc"),
    _: User = Depends(get_admin_user),
) -> dict:
    """ツール別ランキング (ソート・フィルタ・カテゴリ対応)."""
    since = datetime.now(UTC) - timedelta(days=days)
    col = McpToolUsageBucket.get_motor_collection()

    pipeline = [
        {"$match": {"hour": {"$gte": since}}},
        {
            "$group": {
                "_id": "$tool_name",
                "call_count": {"$sum": "$call_count"},
                "error_count": {"$sum": "$error_count"},
                "duration_ms_sum": {"$sum": "$duration_ms_sum"},
                "duration_ms_max": {"$max": "$duration_ms_max"},
                "arg_size_sum": {"$sum": "$arg_size_sum"},
                "unique_callers": {"$addToSet": "$api_key_id"},
                "last_hour": {"$max": "$hour"},
            }
        },
    ]
    rows = await col.aggregate(pipeline).to_list(length=None)

    by_tool: dict[str, dict] = {}
    for row in rows:
        cc = int(row.get("call_count", 0))
        ec = int(row.get("error_count", 0))
        ds = int(row.get("duration_ms_sum", 0))
        callers = row.get("unique_callers", [])
        unique_count = len([c for c in callers if c is not None])
        cat = _tool_category(row["_id"])

        if category and cat != category:
            continue

        avg_dur = round(ds / cc, 1) if cc else 0.0
        by_tool[row["_id"]] = {
            "tool_name": row["_id"],
            "category": cat,
            "call_count": cc,
            "error_count": ec,
            "error_rate": round(ec / cc, 4) if cc else 0.0,
            "unique_callers": unique_count,
            "avg_duration_ms": avg_dur,
            "max_duration_ms": int(row.get("duration_ms_max", 0)),
            "avg_arg_size_bytes": round(int(row.get("arg_size_sum", 0)) / cc) if cc else 0,
            "last_called_at": (
                row["last_hour"].isoformat()
                if isinstance(row.get("last_hour"), datetime)
                else None
            ),
        }

    # 未使用ツールも含める
    for name in await _registered_tool_names():
        cat = _tool_category(name)
        if category and cat != category:
            continue
        by_tool.setdefault(name, {
            "tool_name": name,
            "category": cat,
            "call_count": 0,
            "error_count": 0,
            "error_rate": 0.0,
            "unique_callers": 0,
            "avg_duration_ms": 0.0,
            "max_duration_ms": 0,
            "avg_arg_size_bytes": 0,
            "last_called_at": None,
        })

    # ソート
    sort_key = sort.value
    reverse = order == "desc"
    items = sorted(
        by_tool.values(),
        key=lambda r: (r.get(sort_key, 0) or 0, r["tool_name"]),
        reverse=reverse,
    )

    return {"days": days, "category": category, "sort": sort_key, "order": order, "items": items}


@router.get("/tools/{tool_name}")
async def usage_tool_detail(
    tool_name: str = Path(..., min_length=1),
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_admin_user),
) -> dict:
    """個別ツールの詳細統計.

    日別内訳、レイテンシ分布 (パーセンタイル)、呼び出し元別集計、直近エラーを返す。
    """
    since = datetime.now(UTC) - timedelta(days=days)
    col = McpToolUsageBucket.get_motor_collection()

    # --- 日別集計 ---
    daily_pipeline = [
        {"$match": {"tool_name": tool_name, "hour": {"$gte": since}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$hour"}
                },
                "calls": {"$sum": "$call_count"},
                "errors": {"$sum": "$error_count"},
                "duration_ms_sum": {"$sum": "$duration_ms_sum"},
                "duration_ms_max": {"$max": "$duration_ms_max"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    daily_rows = await col.aggregate(daily_pipeline).to_list(length=None)

    daily_breakdown = [
        {
            "date": row["_id"],
            "calls": int(row.get("calls", 0)),
            "errors": int(row.get("errors", 0)),
            "avg_ms": round(
                int(row.get("duration_ms_sum", 0)) / int(row["calls"]), 1
            ) if row.get("calls") else 0.0,
            "max_ms": int(row.get("duration_ms_max", 0)),
        }
        for row in daily_rows
    ]

    # --- 全期間集計 ---
    total_calls = sum(d["calls"] for d in daily_breakdown)
    total_errors = sum(d["errors"] for d in daily_breakdown)
    total_duration = sum(
        int(r.get("duration_ms_sum", 0)) for r in daily_rows
    )

    # --- 呼び出し元別集計 ---
    caller_pipeline = [
        {"$match": {"tool_name": tool_name, "hour": {"$gte": since}}},
        {
            "$group": {
                "_id": "$api_key_id",
                "call_count": {"$sum": "$call_count"},
                "error_count": {"$sum": "$error_count"},
            }
        },
        {"$sort": {"call_count": -1}},
    ]
    caller_rows = await col.aggregate(caller_pipeline).to_list(length=None)
    callers = [
        {
            "api_key_id": row["_id"],
            "call_count": int(row.get("call_count", 0)),
            "error_count": int(row.get("error_count", 0)),
        }
        for row in caller_rows
    ]

    # --- レイテンシ分布 (イベントログから算出) ---
    latency_dist = await _latency_percentiles(tool_name, since)

    # --- 直近エラー ---
    recent_errors = (
        await McpToolCallEvent.find(
            {"tool_name": tool_name, "success": False, "ts": {"$gte": since}}
        )
        .sort("-ts")
        .limit(20)
        .to_list()
    )
    errors_list = [
        {
            "ts": e.ts.isoformat(),
            "error_class": e.error_class,
            "duration_ms": e.duration_ms,
        }
        for e in recent_errors
    ]

    # --- エラークラス分布 ---
    error_class_pipeline = [
        {
            "$match": {
                "tool_name": tool_name,
                "success": False,
                "ts": {"$gte": since},
            }
        },
        {"$group": {"_id": "$error_class", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    error_class_rows = (
        await McpToolCallEvent.get_motor_collection()
        .aggregate(error_class_pipeline)
        .to_list(length=None)
    )

    return {
        "tool_name": tool_name,
        "category": _tool_category(tool_name),
        "days": days,
        "total_calls": total_calls,
        "total_errors": total_errors,
        "error_rate": round(total_errors / total_calls, 4) if total_calls else 0.0,
        "avg_duration_ms": round(total_duration / total_calls, 1) if total_calls else 0.0,
        "daily_breakdown": daily_breakdown,
        "latency_distribution": latency_dist,
        "callers": callers,
        "error_classes": [
            {"error_class": r["_id"], "count": int(r["count"])}
            for r in error_class_rows
        ],
        "recent_errors": errors_list,
    }


async def _latency_percentiles(tool_name: str, since: datetime) -> dict:
    """イベントログからレイテンシのパーセンタイルを算出する.

    サンプリングされたイベントのみが記録されるため近似値。
    """
    event_col = McpToolCallEvent.get_motor_collection()
    pipeline = [
        {"$match": {"tool_name": tool_name, "ts": {"$gte": since}}},
        {"$sort": {"duration_ms": 1}},
        {"$group": {"_id": None, "durations": {"$push": "$duration_ms"}}},
    ]
    rows = await event_col.aggregate(pipeline).to_list(length=1)
    if not rows or not rows[0].get("durations"):
        return {"sample_size": 0, "p50": None, "p75": None, "p90": None, "p95": None, "p99": None}

    durations = rows[0]["durations"]
    n = len(durations)

    def _percentile(p: float) -> int:
        idx = int(n * p / 100)
        return int(durations[min(idx, n - 1)])

    return {
        "sample_size": n,
        "p50": _percentile(50),
        "p75": _percentile(75),
        "p90": _percentile(90),
        "p95": _percentile(95),
        "p99": _percentile(99),
    }


@router.get("/co-occurrence")
async def usage_co_occurrence(
    days: int = Query(30, ge=1, le=365),
    min_count: int = Query(5, ge=1, description="最低共起回数でフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(get_admin_user),
) -> dict:
    """同一 api_key_id × 同一時間バケット内で使われたツールのペアを集計.

    高頻度ペアは統合候補を示唆する。
    """
    since = datetime.now(UTC) - timedelta(days=days)
    col = McpToolUsageBucket.get_motor_collection()

    # 同一 (api_key_id, hour) 内のツール名を集める
    pipeline = [
        {"$match": {"hour": {"$gte": since}, "api_key_id": {"$ne": None}}},
        {
            "$group": {
                "_id": {"key": "$api_key_id", "hour": "$hour"},
                "tools": {"$addToSet": "$tool_name"},
            }
        },
    ]
    groups = await col.aggregate(pipeline).to_list(length=None)

    # Python 側でペアを展開して集計する。
    # $sortArray が mongomock 未サポートのため、パイプライン外で処理する。
    from collections import Counter

    pair_counter: Counter[tuple[str, str]] = Counter()
    for group in groups:
        tools = sorted(group["tools"])
        if len(tools) < 2:
            continue
        for i in range(len(tools)):
            for j in range(i + 1, len(tools)):
                pair_counter[(tools[i], tools[j])] += 1

    # フィルタ・ソート
    pairs = [
        {"tool_a": a, "tool_b": b, "co_count": cnt}
        for (a, b), cnt in pair_counter.most_common()
        if cnt >= min_count
    ][:limit]

    return {"days": days, "min_count": min_count, "pairs": pairs}


@router.get("/trends")
async def usage_trends(
    days: int = Query(30, ge=1, le=365),
    granularity: Literal["hourly", "daily"] = Query("daily"),
    tools: str | None = Query(
        None,
        description="カンマ区切りのツール名 (例: list_tasks,search_tasks)。省略時は全体合算",
    ),
    _: User = Depends(get_admin_user),
) -> dict:
    """時系列トレンドデータ (折れ線グラフ用).

    粒度 (hourly / daily) と対象ツールを指定可能。
    """
    since = datetime.now(UTC) - timedelta(days=days)
    col = McpToolUsageBucket.get_motor_collection()

    match_filter: dict = {"hour": {"$gte": since}}
    tool_list: list[str] | None = None
    if tools:
        tool_list = [t.strip() for t in tools.split(",") if t.strip()]
        if tool_list:
            match_filter["tool_name"] = {"$in": tool_list}

    if granularity == "hourly":
        group_id = "$hour"
    else:
        group_id = {"$dateToString": {"format": "%Y-%m-%d", "date": "$hour"}}

    pipeline = [
        {"$match": match_filter},
        {
            "$group": {
                "_id": {"period": group_id, "tool": "$tool_name"},
                "calls": {"$sum": "$call_count"},
                "errors": {"$sum": "$error_count"},
                "duration_ms_sum": {"$sum": "$duration_ms_sum"},
            }
        },
        {"$sort": {"_id.period": 1}},
    ]
    rows = await col.aggregate(pipeline).to_list(length=None)

    # ツール別に整理
    by_tool: dict[str, list[dict]] = {}
    for row in rows:
        tool = row["_id"]["tool"]
        period = row["_id"]["period"]
        if isinstance(period, datetime):
            period = period.isoformat()
        cc = int(row.get("calls", 0))
        by_tool.setdefault(tool, []).append({
            "period": period,
            "calls": cc,
            "errors": int(row.get("errors", 0)),
            "avg_ms": round(int(row.get("duration_ms_sum", 0)) / cc, 1) if cc else 0.0,
        })

    return {
        "days": days,
        "granularity": granularity,
        "tools_filter": tool_list,
        "series": by_tool,
    }


# ---------------------------------------------------------------------------
# API 改善リクエスト (REST)
# ---------------------------------------------------------------------------

_VALID_FEEDBACK_STATUSES = {"open", "accepted", "rejected", "done"}


@router.get("/feedback")
async def list_feedback(
    tool_name: str | None = Query(None),
    status: str | None = Query(None),
    request_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    _: User = Depends(get_admin_user),
) -> dict:
    """改善リクエスト一覧 (フィルタ対応)."""
    query: dict = {}
    if tool_name:
        query["tool_name"] = tool_name
    if status:
        query["status"] = status
    if request_type:
        query["request_type"] = request_type

    docs = (
        await McpApiFeedback.find(query)
        .sort("-created_at")
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    total = await McpApiFeedback.find(query).count()

    return {
        "total": total,
        "items": [
            {
                "id": str(d.id),
                "tool_name": d.tool_name,
                "request_type": d.request_type,
                "description": d.description,
                "related_tools": d.related_tools,
                "status": d.status,
                "votes": d.votes,
                "submitted_by": d.submitted_by,
                "created_at": d.created_at.isoformat(),
                "updated_at": d.updated_at.isoformat(),
            }
            for d in docs
        ],
    }


@router.get("/feedback/summary")
async def feedback_summary(
    _: User = Depends(get_admin_user),
) -> dict:
    """改善リクエストの集計サマリー (ステータス別・タイプ別・ツール別)."""
    col = McpApiFeedback.get_motor_collection()

    # ステータス別
    status_pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    status_rows = await col.aggregate(status_pipeline).to_list(length=None)

    # タイプ別
    type_pipeline = [
        {"$group": {"_id": "$request_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    type_rows = await col.aggregate(type_pipeline).to_list(length=None)

    # ツール別 (open のみ)
    tool_pipeline = [
        {"$match": {"status": "open"}},
        {"$group": {"_id": "$tool_name", "count": {"$sum": 1}, "total_votes": {"$sum": "$votes"}}},
        {"$sort": {"total_votes": -1}},
        {"$limit": 20},
    ]
    tool_rows = await col.aggregate(tool_pipeline).to_list(length=20)

    return {
        "by_status": {r["_id"]: int(r["count"]) for r in status_rows},
        "by_type": [
            {"request_type": r["_id"], "count": int(r["count"])}
            for r in type_rows
        ],
        "top_tools_with_open_requests": [
            {
                "tool_name": r["_id"],
                "open_count": int(r["count"]),
                "total_votes": int(r["total_votes"]),
            }
            for r in tool_rows
        ],
    }


@router.patch("/feedback/{feedback_id}")
async def update_feedback(
    feedback_id: str = Path(...),
    status: str | None = Query(None),
    votes_delta: int | None = Query(None, description="+1 で投票追加"),
    _: User = Depends(get_admin_user),
) -> dict:
    """改善リクエストのステータス更新 / 投票."""
    doc = await McpApiFeedback.get(feedback_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if status is not None:
        if status not in _VALID_FEEDBACK_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Valid: {', '.join(sorted(_VALID_FEEDBACK_STATUSES))}",
            )
        doc.status = status  # type: ignore[assignment]

    if votes_delta is not None:
        doc.votes = max(0, doc.votes + votes_delta)

    doc.updated_at = datetime.now(UTC)
    await doc.save()

    return {
        "id": str(doc.id),
        "tool_name": doc.tool_name,
        "status": doc.status,
        "votes": doc.votes,
        "updated_at": doc.updated_at.isoformat(),
    }
