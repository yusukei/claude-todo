"""URL lookup MCP tools (URL S4) — ``parse_url`` / ``get_resource`` / ``lookup_url``.

仕様: ``docs/api/url-contract.md``
不変条件: URL-1 (round-trip) / URL-3 (legacy redirect) / URL-4 (unknown は
unknown を返す) / URL-5 (IDOR oracle なし) / URL-6 (rate limit 429) /
URL-7 (audit log)

純粋な URL 解析は ``app.lib.url_contract.parse_url`` に委譲する。本モジュール
は MCP 表面 (decorator + auth + 認可 + rate limit + audit log + dispatch)
のみを持つ。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastmcp.exceptions import ToolError

from ...core.redis import get_redis
from ...lib.url_contract import (
    LAYOUT_QUERY_KEYS,
    ParsedUrl,
    parse_url as _pure_parse_url,
)
from ...models.url_lookup_audit import UrlLookupAuditLog
from ..auth import McpAuthError, authenticate, check_project_access
from ..server import mcp

logger = logging.getLogger(__name__)

# 仕様書 §7.3: 1 user / 100 reqs/min
URL_LOOKUP_RATE_LIMIT_PER_MIN = 100

# 存在 oracle 統一 (URL-5): "存在しない" と "アクセス不可" を同じ文言で
# 返す。message を fixed にして oracle にしないこと。
_NOT_FOUND_OR_DENIED = "Not found or access denied"


# ── helpers ──────────────────────────────────────────────────────


async def _check_rate_limit(user_id: str) -> tuple[bool, int]:
    """token-bucket rate limit (1 minute window).

    Redis ``INCR`` + ``EXPIRE 120`` の最小実装。fail-closed (Redis 不通時は
    reject)。

    Returns:
        (allowed, retry_after_sec). retry_after は最大 60 秒。
    """
    minute = int(time.time() // 60)
    key = f"ratelimit:url_lookup:{user_id}:{minute}"
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 120)
        count, _ = await pipe.execute()
    except Exception:
        logger.exception("url_lookup rate_limit: redis unavailable — rejecting")
        return False, 60

    count = int(count)
    if count > URL_LOOKUP_RATE_LIMIT_PER_MIN:
        # 同じ分内のリトライは無意味 (window 終了まで待つ)
        retry = max(1, 60 - (int(time.time()) % 60))
        return False, retry
    return True, 0


async def _audit(
    *,
    user_id: str,
    auth_kind: str,
    url: str,
    parsed: ParsedUrl | None,
    success: bool,
    message: str = "",
) -> None:
    """監査ログ書き込み。例外は握り潰す (audit 失敗で本処理を落とさない)。"""
    try:
        await UrlLookupAuditLog(
            user_id=user_id,
            url=url,
            kind=parsed.kind if parsed else "unknown",
            project_id=parsed.project_id if parsed else None,
            success=success,
            auth_kind=auth_kind,
            message=message,
        ).insert()
    except Exception:
        logger.exception("url_lookup audit: insert failed (non-fatal)")


def _parsed_to_dict(parsed: ParsedUrl) -> dict[str, Any]:
    """ParsedUrl → MCP 戻り値 dict (None は省略)."""
    out: dict[str, Any] = {"kind": parsed.kind}
    if parsed.project_id is not None:
        out["project_id"] = parsed.project_id
    if parsed.resource_id is not None:
        out["resource_id"] = parsed.resource_id
    if parsed.path is not None:
        out["path"] = parsed.path
    if parsed.site_id is not None:
        out["site_id"] = parsed.site_id
    out["had_unknown_params"] = parsed.had_unknown_params
    if parsed.redirect_to is not None:
        out["redirect_to"] = parsed.redirect_to
    return out


async def _project_access_or_deny(
    project_id: str | None, key_info: dict
) -> bool:
    """project_id があれば membership を確認。bypassible (admin)。

    Returns:
        True: アクセス OK
        False: 拒否 (oracle 統一のため not-found と同じ応答にする)
    """
    if project_id is None:
        return True
    try:
        await check_project_access(project_id, key_info)
        return True
    except McpAuthError:
        return False


async def _fetch_resource(
    parsed: ParsedUrl, key_info: dict
) -> tuple[bool, dict[str, Any] | None]:
    """parse 結果から resource を取得。

    Returns:
        (success, resource_dict)。oracle 統一のため None / 拒否 / 未定義
        kind はすべて (False, None) で返す。
    """
    kind = parsed.kind

    # project_id が parse 段階で得られている系は IDOR チェック必須。
    if parsed.project_id is not None:
        if not await _project_access_or_deny(parsed.project_id, key_info):
            return False, None

    try:
        if kind == "task":
            from ...models.task import Task

            if not parsed.resource_id:
                return False, None
            task = await Task.get(parsed.resource_id)
            if task is None:
                return False, None
            # task.project_id と URL の project_id 一致確認 (URL-5)
            if (
                parsed.project_id is not None
                and getattr(task, "project_id", None) != parsed.project_id
            ):
                return False, None
            # admin / member 判定は parsed.project_id ですでに通過。
            from ...services.serializers import task_to_dict  # type: ignore  # noqa: F401

            try:
                return True, task_to_dict(task)
            except Exception:
                return True, task.model_dump(mode="json")

        if kind in ("document", "document_full"):
            from ...models.document import ProjectDocument

            if not parsed.resource_id:
                return False, None
            doc = await ProjectDocument.get(parsed.resource_id)
            if doc is None or getattr(doc, "is_deleted", False):
                return False, None
            if (
                parsed.project_id is not None
                and getattr(doc, "project_id", None) != parsed.project_id
            ):
                return False, None
            return True, doc.model_dump(mode="json")

        if kind == "bookmark":
            from ...models.bookmark import Bookmark

            if not parsed.resource_id:
                return False, None
            bm = await Bookmark.get(parsed.resource_id)
            if bm is None:
                return False, None
            # bookmark は内部的に Common project に紐づく → URL に pid は無い
            # ものの、bm.project_id で IDOR 判定する。
            bm_pid = getattr(bm, "project_id", None)
            if bm_pid is not None and not await _project_access_or_deny(
                bm_pid, key_info
            ):
                return False, None
            return True, bm.model_dump(mode="json")

        if kind == "knowledge":
            from ...models.knowledge import Knowledge

            if not parsed.resource_id:
                return False, None
            k = await Knowledge.get(parsed.resource_id)
            if k is None:
                return False, None
            # knowledge は project_id を持たない (cross-project) ため
            # 認証済みユーザは閲覧可。
            return True, k.model_dump(mode="json")

        if kind == "docsite_page":
            from ...models.docsite import DocPage

            if not parsed.site_id or not parsed.path:
                return False, None
            page = await DocPage.find_one(
                DocPage.site_id == parsed.site_id,
                DocPage.path == parsed.path,
            )
            if page is None:
                return False, None
            return True, page.model_dump(mode="json")

        if kind == "project":
            # project membership は _project_access_or_deny で済んでいる
            from ...models.project import Project

            if not parsed.project_id:
                return False, None
            project = await Project.get(parsed.project_id)
            if project is None:
                return False, None
            return True, project.model_dump(mode="json")

        # unknown / その他は resource fetch しない
        return False, None
    except Exception:
        # oracle 統一: あらゆるエラーで not-found に丸める
        logger.exception(
            "url_lookup fetch failed silently for kind=%s id=%s",
            kind,
            parsed.resource_id,
        )
        return False, None


# ── MCP tools ────────────────────────────────────────────────────


@mcp.tool()
async def parse_url(url: str) -> dict:
    """URL を解析し、routing メタデータ dict を返す (認可なし、純関数表面)。

    詳細仕様: ``docs/api/url-contract.md`` §4.3。

    Args:
        url: full URL or path. e.g. ``/projects/abc?task=def``

    Returns:
        ``{kind, project_id?, resource_id?, path?, site_id?, had_unknown_params, redirect_to?}``。
        ``kind`` は ``task``/``document``/``document_full``/``bookmark``/
        ``knowledge``/``docsite_page``/``project``/``unknown`` のいずれか。
    """
    # 認証だけは要求 (rate limit / oracle の対象は lookup_url のみ)
    await authenticate()
    parsed = _pure_parse_url(url)
    return _parsed_to_dict(parsed)


@mcp.tool()
async def get_resource(
    kind: str,
    resource_id: str,
    project_id: str | None = None,
) -> dict:
    """kind / id からリソースを取得する (認可チェックあり)。

    内部で task / document / bookmark / knowledge / docpage / project の
    既存 fetch を呼ぶ薄ラッパー。**存在しない or アクセス不可** は同じ
    応答 (URL-5 oracle 統一)。

    Args:
        kind: ResourceKind (task/document/document_full/bookmark/knowledge/
            docsite_page/project)。
        resource_id: 24 桁 hex (docsite_page 以外)。
        project_id: optional。task / document / document_full は **必須**。
    """
    key_info = await authenticate()
    user_id = key_info.get("user_id", "")
    auth_kind = key_info.get("auth_kind", "")

    parsed = ParsedUrl(
        kind=kind,  # type: ignore[arg-type]
        project_id=project_id,
        resource_id=resource_id,
    )
    success, resource = await _fetch_resource(parsed, key_info)
    if not success:
        await _audit(
            user_id=user_id,
            auth_kind=auth_kind,
            url=f"<get_resource kind={kind} id={resource_id}>",
            parsed=parsed,
            success=False,
            message="not_found_or_denied",
        )
        return {
            "kind": "unknown",
            "message": _NOT_FOUND_OR_DENIED,
        }
    await _audit(
        user_id=user_id,
        auth_kind=auth_kind,
        url=f"<get_resource kind={kind} id={resource_id}>",
        parsed=parsed,
        success=True,
    )
    return {
        "kind": kind,
        "project_id": project_id,
        "resource_id": resource_id,
        "resource": resource,
    }


@mcp.tool()
async def lookup_url(url: str, follow: bool = True) -> dict:
    """URL を resolve してリソースを返す (parse_url + get_resource 薄ラッパー)。

    詳細仕様: ``docs/api/url-contract.md`` §4 / §7。
    rate limit: 1 ユーザ / 100 reqs/min (URL-6)。
    存在 oracle 統一: 不在 / 非 member / IDOR は同じ応答 (URL-5)。
    audit log: 成功 / 失敗ともに記録 (URL-7)。

    Args:
        url: ターゲット URL (相対 or 絶対)。
        follow: True なら resource 本体も inline、False なら routing
            metadata のみ返す。

    Returns:
        ``{url, kind, project_id?, resource_id?, path?, site_id?,
           had_unknown_params, redirect_to?, resource?, message?}``
    """
    key_info = await authenticate()
    user_id = key_info.get("user_id", "")
    auth_kind = key_info.get("auth_kind", "")

    # rate limit (URL-6)
    allowed, retry_after = await _check_rate_limit(user_id)
    if not allowed:
        # audit に記録してから ToolError を raise
        # (parse 前なので parsed=None)
        await _audit(
            user_id=user_id,
            auth_kind=auth_kind,
            url=url,
            parsed=None,
            success=False,
            message="rate_limited",
        )
        raise ToolError(
            f"Rate limit exceeded ({URL_LOOKUP_RATE_LIMIT_PER_MIN}/min). "
            f"Retry after {retry_after}s."
        )

    parsed = _pure_parse_url(url)
    base = {"url": url, **_parsed_to_dict(parsed)}
    # consumer 向けに layout query keys のヒントを残す (had_unknown_params だけだと
    # どの key が含まれていたか分からない)
    base["layout_query_keys"] = sorted(LAYOUT_QUERY_KEYS)

    if parsed.kind == "unknown":
        await _audit(
            user_id=user_id,
            auth_kind=auth_kind,
            url=url,
            parsed=parsed,
            success=False,
            message="parse_failed",
        )
        return {**base, "message": _NOT_FOUND_OR_DENIED}

    if not follow:
        # routing metadata のみ。authenticate() は通っているが
        # IDOR / resource fetch は走らない (caller の判断で別途 get_resource)。
        await _audit(
            user_id=user_id,
            auth_kind=auth_kind,
            url=url,
            parsed=parsed,
            success=True,
        )
        return base

    success, resource = await _fetch_resource(parsed, key_info)
    if not success:
        # oracle 統一: kind は元のまま残しつつ message で not-found を表現
        # しても良いが、仕様書 §7.2 が "kind: unknown" の応答を例示している
        # ので、resource fetch 失敗時は kind を unknown に丸めて oracle を
        # 排除する。
        await _audit(
            user_id=user_id,
            auth_kind=auth_kind,
            url=url,
            parsed=parsed,
            success=False,
            message="not_found_or_denied",
        )
        return {
            "url": url,
            "kind": "unknown",
            "had_unknown_params": parsed.had_unknown_params,
            "message": _NOT_FOUND_OR_DENIED,
            "layout_query_keys": sorted(LAYOUT_QUERY_KEYS),
        }

    await _audit(
        user_id=user_id,
        auth_kind=auth_kind,
        url=url,
        parsed=parsed,
        success=True,
    )
    return {**base, "resource": resource}


__all__ = [
    "parse_url",
    "get_resource",
    "lookup_url",
    "URL_LOOKUP_RATE_LIMIT_PER_MIN",
]
