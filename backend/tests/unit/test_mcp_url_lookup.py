"""URL S4 — ``lookup_url`` / ``get_resource`` / ``parse_url`` MCP tool tests.

仕様書 ``docs/api/url-contract.md`` §7 のセキュリティ要件 (URL-5/6/7) を
カバー。

不変条件:
    URL-3  legacy /workbench/{id} は redirect_to を返す
    URL-4  parse 不能な URL は kind: "unknown"
    URL-5  IDOR は kind: "unknown" (oracle 統一、message も固定)
    URL-6  1 ユーザ / 100 reqs/min を超えると ToolError (rate_limit)
    URL-7  成功 / 失敗ともに UrlLookupAuditLog に記録される
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from app.models.document import DocumentCategory, ProjectDocument
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskStatus
from app.models.url_lookup_audit import UrlLookupAuditLog


_ADMIN_KEY_INFO = {
    "key_id": "test-key",
    "key_name": "test",
    "user_id": "user-admin",
    "user_name": "admin",
    "is_admin": True,
    "auth_kind": "api_key",
}


@pytest.fixture
def mock_auth():
    """`authenticate()` を AsyncMock に差し替える。各テストで return_value を上書き可能。"""
    with patch(
        "app.mcp.tools.url_lookup.authenticate", new_callable=AsyncMock
    ) as m:
        m.return_value = {**_ADMIN_KEY_INFO}
        yield m


async def _make_project(
    name: str = "p-url-test", members: list | None = None
) -> Project:
    p = Project(
        name=name,
        description="URL test",
        color="#6366f1",
        status=ProjectStatus.active,
        members=members or [],
        created_by=None,
    )
    await p.insert()
    return p


async def _make_task(project_id: str, title: str = "T1") -> Task:
    t = Task(
        project_id=project_id,
        title=title,
        description="",
        status=TaskStatus.todo,
        created_by="test",
    )
    await t.insert()
    return t


async def _make_document(project_id: str, title: str = "D1") -> ProjectDocument:
    d = ProjectDocument(
        project_id=project_id,
        title=title,
        content="x",
        tags=[],
        category=DocumentCategory.spec,
        created_by="test",
    )
    await d.insert()
    return d


# ── parse_url ────────────────────────────────────────────────────


class TestParseUrlTool:
    async def test_returns_routing_metadata_for_task_url(self, mock_auth):
        from app.mcp.tools.url_lookup import parse_url

        pid = "a" * 24
        tid = "b" * 24
        result = await parse_url(f"/projects/{pid}?task={tid}")
        assert result["kind"] == "task"
        assert result["project_id"] == pid
        assert result["resource_id"] == tid
        assert result["had_unknown_params"] is False

    async def test_returns_unknown_for_garbage_url(self, mock_auth):
        from app.mcp.tools.url_lookup import parse_url

        result = await parse_url("/foo/bar")
        assert result["kind"] == "unknown"

    async def test_legacy_workbench_returns_redirect_to(self, mock_auth):
        from app.mcp.tools.url_lookup import parse_url

        pid = "c" * 24
        result = await parse_url(f"/workbench/{pid}")
        assert result["kind"] == "project"
        assert result["redirect_to"] == f"/projects/{pid}"


# ── lookup_url — success paths ───────────────────────────────────


class TestLookupUrlSuccess:
    async def test_admin_can_fetch_task_resource(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        t = await _make_task(str(p.id))
        url = f"/projects/{p.id}?task={t.id}"

        result = await lookup_url(url, follow=True)
        assert result["kind"] == "task"
        assert result["project_id"] == str(p.id)
        assert result["resource_id"] == str(t.id)
        assert "resource" in result
        assert result["resource"]["title"] == "T1"

    async def test_follow_false_skips_resource_fetch(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        t = await _make_task(str(p.id))
        url = f"/projects/{p.id}?task={t.id}"

        result = await lookup_url(url, follow=False)
        assert result["kind"] == "task"
        assert "resource" not in result

    async def test_legacy_workbench_includes_redirect_to(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        result = await lookup_url(f"/workbench/{p.id}", follow=True)
        # legacy URL でも resource fetch は走る (kind は project に解決される)
        assert result["kind"] == "project"
        assert result["redirect_to"] == f"/projects/{p.id}"
        assert "resource" in result

    async def test_document_resource_fetched(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        d = await _make_document(str(p.id))
        url = f"/projects/{p.id}?doc={d.id}"

        result = await lookup_url(url, follow=True)
        assert result["kind"] == "document"
        assert result["resource"]["title"] == "D1"


# ── URL-5: IDOR oracle 統一 ──────────────────────────────────────


class TestLookupUrlOracle:
    async def test_non_member_gets_kind_unknown_with_fixed_message(
        self, mock_auth
    ):
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        t = await _make_task(str(p.id))
        url = f"/projects/{p.id}?task={t.id}"

        # 別ユーザ (non-admin, non-member) として呼び出す
        mock_auth.return_value = {
            "user_id": "user-stranger",
            "user_name": "stranger",
            "is_admin": False,
            "auth_kind": "api_key",
        }

        result = await lookup_url(url, follow=True)
        assert result["kind"] == "unknown"
        assert result["message"] == "Not found or access denied"

    async def test_nonexistent_task_gets_kind_unknown_with_fixed_message(
        self, mock_auth
    ):
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        # task は作らず、適当な ObjectId で URL を組む
        fake_tid = "0" * 24
        url = f"/projects/{p.id}?task={fake_tid}"

        result = await lookup_url(url, follow=True)
        assert result["kind"] == "unknown"
        assert result["message"] == "Not found or access denied"

    async def test_oracle_message_is_identical_for_both_failures(
        self, mock_auth
    ):
        """URL-5: 不在 と アクセス不可 が同じ応答であることを直接比較。"""
        from app.mcp.tools.url_lookup import lookup_url

        p = await _make_project()
        t = await _make_task(str(p.id))

        # case A: 非 member
        mock_auth.return_value = {
            "user_id": "stranger",
            "user_name": "s",
            "is_admin": False,
            "auth_kind": "api_key",
        }
        result_idor = await lookup_url(
            f"/projects/{p.id}?task={t.id}", follow=True
        )

        # case B: 存在しない task (admin で)
        mock_auth.return_value = {**_ADMIN_KEY_INFO}
        result_404 = await lookup_url(
            f"/projects/{p.id}?task={'1' * 24}", follow=True
        )

        # 両方とも kind=unknown かつ message が固定
        assert result_idor["kind"] == result_404["kind"] == "unknown"
        assert (
            result_idor["message"]
            == result_404["message"]
            == "Not found or access denied"
        )


# ── URL-6: rate limit ────────────────────────────────────────────


class TestLookupUrlRateLimit:
    async def test_exceeding_limit_raises_tool_error(self, mock_auth):
        """101 回目で ToolError。limit を 2 に下げて高速化。"""
        from app.mcp.tools import url_lookup as ul
        from app.mcp.tools.url_lookup import lookup_url

        # 各テストで Redis state は fakeredis の dictionary に残るので
        # ユーザ id を test 専用にして競合を回避
        mock_auth.return_value = {
            **_ADMIN_KEY_INFO,
            "user_id": "rate-limit-test-1",
        }

        with patch.object(ul, "URL_LOOKUP_RATE_LIMIT_PER_MIN", 2):
            await lookup_url("/foo", follow=False)  # 1 (kind=unknown でも消費)
            await lookup_url("/foo", follow=False)  # 2
            with pytest.raises(ToolError, match="Rate limit"):
                await lookup_url("/foo", follow=False)  # 3 → reject

    async def test_rate_limit_audit_log_recorded(self, mock_auth):
        from app.mcp.tools import url_lookup as ul
        from app.mcp.tools.url_lookup import lookup_url

        user_id = "rate-limit-audit-user"
        mock_auth.return_value = {**_ADMIN_KEY_INFO, "user_id": user_id}

        # Clean prior logs for this user (mongomock doesn't isolate per test
        # by default in this suite; defensive deletion)
        await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).delete()

        with patch.object(ul, "URL_LOOKUP_RATE_LIMIT_PER_MIN", 1):
            await lookup_url("/foo", follow=False)  # consumes 1
            with pytest.raises(ToolError):
                await lookup_url("/foo", follow=False)

        logs = await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).to_list()
        # 1 件: parse_failed (1回目, /foo は unknown なので message=parse_failed)
        # 1 件: rate_limited (2回目)
        messages = sorted(log.message for log in logs)
        assert "rate_limited" in messages


# ── URL-7: audit log ─────────────────────────────────────────────


class TestLookupUrlAuditLog:
    async def test_success_recorded(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        user_id = "audit-success-user"
        mock_auth.return_value = {**_ADMIN_KEY_INFO, "user_id": user_id}

        await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).delete()

        p = await _make_project()
        t = await _make_task(str(p.id))
        url = f"/projects/{p.id}?task={t.id}"
        await lookup_url(url, follow=True)

        logs = await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).to_list()
        assert len(logs) == 1
        assert logs[0].success is True
        assert logs[0].kind == "task"
        assert logs[0].url == url
        assert logs[0].auth_kind == "api_key"

    async def test_oracle_failure_recorded_as_not_found(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        user_id = "audit-failure-user"
        mock_auth.return_value = {
            "user_id": user_id,
            "user_name": "x",
            "is_admin": False,
            "auth_kind": "api_key",
        }

        await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).delete()

        # 非 member の project への URL
        p = await _make_project()
        t = await _make_task(str(p.id))
        url = f"/projects/{p.id}?task={t.id}"
        result = await lookup_url(url, follow=True)
        assert result["kind"] == "unknown"

        logs = await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).to_list()
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].message == "not_found_or_denied"
        # parse 段階では task として認識されている
        assert logs[0].kind == "task"

    async def test_parse_failed_recorded(self, mock_auth):
        from app.mcp.tools.url_lookup import lookup_url

        user_id = "audit-parse-failed-user"
        mock_auth.return_value = {**_ADMIN_KEY_INFO, "user_id": user_id}

        await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).delete()

        result = await lookup_url("/totally-bogus", follow=True)
        assert result["kind"] == "unknown"

        logs = await UrlLookupAuditLog.find(
            UrlLookupAuditLog.user_id == user_id
        ).to_list()
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].message == "parse_failed"


# ── get_resource ─────────────────────────────────────────────────


class TestGetResourceTool:
    async def test_admin_fetches_task(self, mock_auth):
        from app.mcp.tools.url_lookup import get_resource

        p = await _make_project()
        t = await _make_task(str(p.id))
        result = await get_resource("task", str(t.id), project_id=str(p.id))
        assert result["kind"] == "task"
        assert result["resource"]["title"] == "T1"

    async def test_non_member_gets_unknown(self, mock_auth):
        from app.mcp.tools.url_lookup import get_resource

        mock_auth.return_value = {
            "user_id": "stranger",
            "user_name": "x",
            "is_admin": False,
            "auth_kind": "api_key",
        }
        p = await _make_project()
        t = await _make_task(str(p.id))
        result = await get_resource("task", str(t.id), project_id=str(p.id))
        assert result["kind"] == "unknown"
        assert result["message"] == "Not found or access denied"

    async def test_nonexistent_resource_unknown(self, mock_auth):
        from app.mcp.tools.url_lookup import get_resource

        p = await _make_project()
        result = await get_resource(
            "task", "0" * 24, project_id=str(p.id)
        )
        assert result["kind"] == "unknown"
