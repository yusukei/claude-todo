"""MCP ツール: API 改善リクエストの送信・一覧.

作業中に Claude Code から直接 API の改善提案を送信できる。
"""

import logging

from fastmcp.exceptions import ToolError

from ...models.mcp_api_feedback import FeedbackRequestType, McpApiFeedback
from ..auth import authenticate
from ..server import mcp

logger = logging.getLogger(__name__)

_VALID_REQUEST_TYPES = {
    "missing_param",
    "merge",
    "split",
    "deprecate",
    "bug",
    "performance",
    "other",
}


@mcp.tool()
async def request_api_improvement(
    tool_name: str,
    request_type: str,
    description: str,
    related_tools: list[str] | None = None,
) -> dict:
    """Submit an API improvement request for an MCP tool.

    Use this when you notice an MCP tool could be improved during work.
    Requests are stored and reviewed by admins alongside usage statistics.

    Args:
        tool_name: Target tool name (e.g. "list_tasks", "search_tasks")
        request_type: Type of improvement: missing_param | merge | split | deprecate | bug | performance | other
        description: Specific description of the improvement (max 2000 chars)
        related_tools: Related tools (required for merge/split requests, e.g. ["get_task", "get_subtasks"])
    """
    if not tool_name or not tool_name.strip():
        raise ToolError("tool_name is required")
    if request_type not in _VALID_REQUEST_TYPES:
        raise ToolError(
            f"Invalid request_type '{request_type}'. "
            f"Valid: {', '.join(sorted(_VALID_REQUEST_TYPES))}"
        )
    if not description or not description.strip():
        raise ToolError("description is required")
    if len(description) > 2000:
        raise ToolError("description exceeds maximum length of 2000 characters")
    if request_type in ("merge", "split") and not related_tools:
        raise ToolError(
            f"related_tools is required for '{request_type}' requests"
        )

    key_info = await authenticate()
    submitted_by = key_info.get("key_hash") or (
        f"user:{key_info['user_id']}" if key_info.get("user_id") else None
    )

    normalized_related = [t.strip() for t in (related_tools or []) if t.strip()]

    feedback = McpApiFeedback(
        tool_name=tool_name.strip(),
        request_type=request_type,  # type: ignore[arg-type]
        description=description.strip(),
        related_tools=normalized_related,
        submitted_by=submitted_by,
    )
    await feedback.insert()

    return {
        "id": str(feedback.id),
        "tool_name": feedback.tool_name,
        "request_type": feedback.request_type,
        "description": feedback.description,
        "related_tools": feedback.related_tools,
        "status": feedback.status,
        "created_at": feedback.created_at.isoformat(),
        "message": "Improvement request submitted successfully.",
    }


@mcp.tool()
async def list_api_feedback(
    tool_name: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> dict:
    """List API improvement requests with optional filters.

    Args:
        tool_name: Filter by target tool name
        status: Filter by status: open | accepted | rejected | done
        request_type: Filter by type: missing_param | merge | split | deprecate | bug | performance | other
        limit: Maximum items to return (default 20, max 100)
        skip: Number of items to skip for pagination
    """
    await authenticate()

    query: dict = {}
    if tool_name:
        query["tool_name"] = tool_name.strip()
    if status:
        query["status"] = status
    if request_type:
        query["request_type"] = request_type

    limit = min(limit, 100)

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
            }
            for d in docs
        ],
    }
