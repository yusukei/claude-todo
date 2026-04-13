"""MCP API 改善リクエストのデータモデル.

作業中に MCP ツール経由で送信された API 改善リクエストを蓄積する。
usage stats の tool_name と紐付けて定量+定性の統合分析を可能にする。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pymongo
from beanie import Document
from pydantic import Field

FeedbackRequestType = Literal[
    "missing_param",
    "merge",
    "split",
    "deprecate",
    "bug",
    "performance",
    "other",
]

FeedbackStatus = Literal["open", "accepted", "rejected", "done"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class McpApiFeedback(Document):
    """MCP API 改善リクエスト.

    MCP ツール `request_api_improvement` から作成される。
    REST API で一覧・ステータス管理を行う。
    """

    tool_name: str
    request_type: FeedbackRequestType
    description: str
    related_tools: list[str] = Field(default_factory=list)
    status: FeedbackStatus = "open"

    # 同一内容のリクエストが複数来た場合の投票数
    votes: int = 1

    # 送信元の識別子 (api_key_id or user:xxx)
    submitted_by: str | None = None

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "mcp_api_feedback"
        indexes = [
            pymongo.IndexModel(
                [("tool_name", 1), ("status", 1)], name="tool_status"
            ),
            pymongo.IndexModel(
                [("request_type", 1)], name="request_type"
            ),
            pymongo.IndexModel(
                [("status", 1), ("created_at", -1)], name="status_created"
            ),
            pymongo.IndexModel(
                [("created_at", -1)], name="created_desc"
            ),
        ]
