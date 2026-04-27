"""Audit log for ``lookup_url`` MCP tool (URL S4 §7.4).

仕様書: ``docs/api/url-contract.md`` §7.4 / 不変条件 URL-7

成功・失敗の両方を記録する。失敗 (`success=False`) は IDOR / 存在しない /
rate-limit 超過 / parse 不能のいずれか。``message`` フィールドに簡潔な
分類タグ (例: ``"not_found_or_denied"``, ``"rate_limited"``,
``"parse_failed"``) を入れる。

URL 値そのものは敏感情報ではない (path のみ) が、accessing user の行動
パターンを記録するため、project_id があれば保存。
"""
from __future__ import annotations

from datetime import UTC, datetime

from beanie import Document
from pydantic import Field


class UrlLookupAuditLog(Document):
    """``lookup_url`` の各呼び出しを記録する監査ログ。"""

    user_id: str
    url: str
    kind: str  # ParsedUrl.kind (incl. "unknown")
    project_id: str | None = None
    success: bool = True
    auth_kind: str = ""  # "oauth" | "api_key"
    message: str = ""  # 失敗理由のタグ。"" は成功時
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "url_lookup_audit_logs"
        indexes = [
            [("user_id", 1), ("created_at", -1)],
            [("project_id", 1), ("created_at", -1)],
        ]
