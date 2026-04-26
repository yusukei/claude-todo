"""Phase 0.5 / P0.5.6 — MCP tool extensions.

Covers:
* ``create_task(decider_id=...)`` validates the user, populates
  ``decision_requested_at`` automatically.
* ``update_task(decider_id=...)`` sets / clears the decider and
  re-stamps ``decision_requested_at`` on each change.
* ``decider_id`` validation rejects unknown user ids.
* MCP-driven mutations record ``actor_type=ai`` on the activity log
  (so the timeline UI can label them).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from app.models import ActorType, Task, User
from app.models.task import TaskStatus
from app.models.user import AuthType
from tests.helpers.factories import make_task


pytestmark = pytest.mark.asyncio


# ── Reuse the shared mocks from test_mcp_tools.py via patches ────


@pytest.fixture
def mock_auth():
    with patch(
        "app.mcp.tools.tasks.authenticate",
        new_callable=AsyncMock,
        return_value={
            "key_id": "test-key",
            "user_id": "test-user",
            "key_name": "robot",
            "is_admin": True,
            "auth_kind": "api_key",
        },
    ) as m:
        yield m


@pytest.fixture
def mock_check():
    with patch("app.mcp.tools.tasks.check_project_access") as m:
        yield m


@pytest.fixture
def mock_publish():
    with patch(
        "app.mcp.tools.tasks.publish_event",
        new_callable=AsyncMock,
    ) as m:
        yield m


@pytest.fixture
async def koji() -> User:
    u = User(email="koji@test.com", name="Koji", auth_type=AuthType.admin)
    await u.insert()
    return u


# ── create_task with decider_id ──────────────────────────────────


class TestCreateTaskDecider:
    async def test_create_with_decider_id_sets_request_timestamp(
        self, admin_user, test_project, koji, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import create_task

        pid = str(test_project.id)
        with patch(
            "app.mcp.tools.tasks._resolve_project_id",
            new_callable=AsyncMock,
            return_value=pid,
        ):
            result = await create_task(
                project_id=pid,
                title="Decision needed",
                task_type="decision",
                decision_context={
                    "decision_point": "Choose A or B",
                    "background": "Need a call",
                    "options": [{"label": "A", "description": "..."}],
                },
                decider_id=str(koji.id),
            )
        assert result["decider_id"] == str(koji.id)
        assert result["decision_requested_at"] is not None

    async def test_create_with_invalid_decider_id_raises(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import create_task

        pid = str(test_project.id)
        with patch(
            "app.mcp.tools.tasks._resolve_project_id",
            new_callable=AsyncMock,
            return_value=pid,
        ):
            with pytest.raises(ToolError, match="decider_id"):
                await create_task(
                    project_id=pid,
                    title="Bad decider",
                    decider_id="not-an-objectid",
                )

    async def test_create_with_unknown_decider_id_raises(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import create_task

        pid = str(test_project.id)
        # Valid ObjectId format but no User with that id
        ghost_id = "000000000000000000000099"
        with patch(
            "app.mcp.tools.tasks._resolve_project_id",
            new_callable=AsyncMock,
            return_value=pid,
        ):
            with pytest.raises(ToolError, match="not found"):
                await create_task(
                    project_id=pid,
                    title="Phantom decider",
                    decider_id=ghost_id,
                )


# ── update_task with decider_id ──────────────────────────────────


class TestUpdateTaskDecider:
    async def test_update_decider_id_resets_timestamp(
        self, admin_user, test_project, koji, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import update_task

        task = await make_task(str(test_project.id), admin_user, title="t")
        result = await update_task(
            task_id=str(task.id),
            decider_id=str(koji.id),
        )
        assert result["decider_id"] == str(koji.id)
        assert result["decision_requested_at"] is not None
        # Activity log records the change with actor_type=ai
        db = await Task.get(task.id)
        assert any(
            entry.field == "decider_id" and entry.actor_type == ActorType.ai
            for entry in db.activity_log
        )

    async def test_update_clear_decider_id_clears_timestamp(
        self, admin_user, test_project, koji, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import update_task
        from datetime import UTC, datetime as dt

        task = await make_task(str(test_project.id), admin_user, title="t")
        task.decider_id = str(koji.id)
        task.decision_requested_at = dt.now(UTC)
        await task.save()

        # Empty string clears the decider
        result = await update_task(task_id=str(task.id), decider_id="")
        assert result["decider_id"] is None
        assert result["decision_requested_at"] is None

    async def test_update_unknown_decider_id_raises(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import update_task

        task = await make_task(str(test_project.id), admin_user, title="t")
        with pytest.raises(ToolError, match="not found"):
            await update_task(
                task_id=str(task.id),
                decider_id="000000000000000000000099",
            )


# ── actor_type recording ─────────────────────────────────────────


class TestActorTypeOnMcpMutations:
    async def test_update_task_records_actor_type_ai(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import update_task

        task = await make_task(str(test_project.id), admin_user, title="t")
        await update_task(task_id=str(task.id), priority="high")
        db = await Task.get(task.id)
        # The priority change must be recorded as ai
        priority_changes = [e for e in db.activity_log if e.field == "priority"]
        assert priority_changes
        assert all(e.actor_type == ActorType.ai for e in priority_changes)

    async def test_complete_task_records_actor_type_ai(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import complete_task

        task = await make_task(
            str(test_project.id), admin_user, status=TaskStatus.in_progress
        )
        await complete_task(task_id=str(task.id))
        db = await Task.get(task.id)
        status_changes = [e for e in db.activity_log if e.field == "status"]
        assert status_changes
        assert all(e.actor_type == ActorType.ai for e in status_changes)

    async def test_reopen_task_records_actor_type_ai(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        from app.mcp.tools.tasks import reopen_task

        task = await make_task(
            str(test_project.id), admin_user, status=TaskStatus.done
        )
        await reopen_task(task_id=str(task.id))
        db = await Task.get(task.id)
        status_changes = [e for e in db.activity_log if e.field == "status"]
        assert status_changes
        assert all(e.actor_type == ActorType.ai for e in status_changes)
