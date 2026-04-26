"""Inspect recent errors for the worst-performing MCP tools."""
import asyncio
from datetime import UTC, datetime, timedelta

from app.core.database import close_db, connect
from app.models import McpApiFeedback, McpToolCallEvent


TARGETS = [
    "remote_exec", "remote_delete_file", "remote_grep",
    "create_task", "list_projects", "get_work_context",
    "remote_edit_file", "remote_read_file",
]


async def main():
    await connect()
    try:
        since = datetime.now(UTC) - timedelta(days=30)
        ev_col = McpToolCallEvent.get_motor_collection()

        for tool in TARGETS:
            print(f"\n=== {tool} ===")
            err_pipe = [
                {"$match": {"tool_name": tool, "success": False, "ts": {"$gte": since}}},
                {"$group": {"_id": {"cls": "$error_class", "reason": "$reason"},
                            "count": {"$sum": 1},
                            "max_dur": {"$max": "$duration_ms"}}},
                {"$sort": {"count": -1}},
                {"$limit": 10},
            ]
            rows = await ev_col.aggregate(err_pipe).to_list(length=10)
            for r in rows:
                cls = r["_id"].get("cls") or "?"
                reason = (r["_id"].get("reason") or "").strip().replace("\n", " ")
                if len(reason) > 200:
                    reason = reason[:200] + "..."
                print(f"  [{r['count']:>3}x cls={cls} max={r['max_dur']}ms] {reason}")

            slow_pipe = [
                {"$match": {"tool_name": tool, "ts": {"$gte": since}}},
                {"$sort": {"duration_ms": -1}},
                {"$limit": 3},
                {"$project": {"duration_ms": 1, "success": 1, "error_class": 1, "reason": 1, "ts": 1}},
            ]
            slows = await ev_col.aggregate(slow_pipe).to_list(length=3)
            if slows:
                print("  -- top 3 slow events --")
                for s in slows:
                    reason = (s.get("reason") or "").strip().replace("\n", " ")
                    if len(reason) > 150:
                        reason = reason[:150] + "..."
                    print(f"    {s['duration_ms']}ms ok={s.get('success')} cls={s.get('error_class')} {reason}")

        print("\n=== Open API Feedback (top 20) ===")
        fb_col = McpApiFeedback.get_motor_collection()
        fb = await fb_col.find({"status": "open"}).sort([("votes", -1), ("created_at", -1)]).to_list(length=20)
        for f in fb:
            desc = (f.get("description") or "").replace("\n", " ")[:140]
            print(f"  [{f.get('request_type'):>14}] votes={f.get('votes'):>2} {f.get('tool_name'):28} | {desc}")

    finally:
        await close_db()


asyncio.run(main())
