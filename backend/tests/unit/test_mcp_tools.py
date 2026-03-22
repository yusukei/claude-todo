"""MCP tool unit tests for reopen_task, delete_comment, get_subtasks, list_tags, list_tasks date filters."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Task
from app.models.task import Comment, TaskStatus
from tests.helpers.factories import make_task


@pytest.fixture
def mock_auth():
    """Mock authenticate() to return a key_info dict with no project scopes."""
    with patch(
        "app.mcp.tools.tasks.authenticate",
        new_callable=AsyncMock,
        return_value={"key_id": "test-key", "project_scopes": []},
    ) as m:
        yield m


@pytest.fixture
def mock_check():
    """Mock check_project_access() to always pass."""
    with patch("app.mcp.tools.tasks.check_project_access") as m:
        yield m


@pytest.fixture
def mock_publish():
    """Mock publish_event() to avoid Redis dependency."""
    with patch(
        "app.mcp.tools.tasks.publish_event",
        new_callable=AsyncMock,
    ) as m:
        yield m


# Shared mock for authenticate + check_project_access
_MOCK_KEY_INFO = {"key_id": "test-key", "project_scopes": []}


def _patch_mcp_auth():
    """Patch authenticate() and check_project_access() for MCP tool tests."""
    return [
        patch(
            "app.mcp.tools.tasks.authenticate",
            new_callable=AsyncMock,
            return_value=_MOCK_KEY_INFO,
        ),
        patch("app.mcp.tools.tasks.check_project_access"),
    ]


class TestReopenTask:
    async def test_reopen_done_task(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Reopening a done task sets status to todo and clears completed_at."""
        from app.mcp.tools.tasks import reopen_task

        task = await make_task(
            str(test_project.id), admin_user, status=TaskStatus.done
        )
        task.completed_at = datetime.now(UTC)
        await task.save()

        result = await reopen_task(task_id=str(task.id))

        assert result["status"] == "todo"
        assert result["completed_at"] is None

        db_task = await Task.get(task.id)
        assert db_task.status == TaskStatus.todo
        assert db_task.completed_at is None

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][1] == "task.updated"

    async def test_reopen_cancelled_task(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Reopening a cancelled task sets status to todo."""
        from app.mcp.tools.tasks import reopen_task

        task = await make_task(
            str(test_project.id), admin_user, status=TaskStatus.cancelled
        )

        result = await reopen_task(task_id=str(task.id))

        assert result["status"] == "todo"
        assert result["completed_at"] is None

    async def test_reopen_already_todo_task(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Reopening a todo task is idempotent - still returns todo."""
        from app.mcp.tools.tasks import reopen_task

        task = await make_task(
            str(test_project.id), admin_user, status=TaskStatus.todo
        )

        result = await reopen_task(task_id=str(task.id))

        assert result["status"] == "todo"

    async def test_reopen_deleted_task_raises(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Reopening a soft-deleted task raises ToolError."""
        from fastmcp.exceptions import ToolError

        from app.mcp.tools.tasks import reopen_task

        task = await make_task(
            str(test_project.id), admin_user, is_deleted=True
        )

        with pytest.raises(ToolError, match="Task not found"):
            await reopen_task(task_id=str(task.id))

    async def test_reopen_nonexistent_task_raises(
        self, mock_auth, mock_check, mock_publish
    ):
        """Reopening a non-existent task raises ToolError."""
        from fastmcp.exceptions import ToolError

        from app.mcp.tools.tasks import reopen_task

        with pytest.raises(ToolError, match="Task not found"):
            await reopen_task(task_id="000000000000000000000000")


class TestDeleteComment:
    async def test_delete_existing_comment(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Deleting an existing comment removes it from the task."""
        from app.mcp.tools.tasks import delete_comment

        task = await make_task(str(test_project.id), admin_user)
        comment = Comment(content="To be deleted", author_id="mcp", author_name="Claude")
        task.comments.append(comment)
        await task.save()

        result = await delete_comment(task_id=str(task.id), comment_id=comment.id)

        assert len(result["comments"]) == 0

        db_task = await Task.get(task.id)
        assert len(db_task.comments) == 0

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][1] == "comment.deleted"
        assert call_args[0][2]["comment_id"] == comment.id

    async def test_delete_one_of_multiple_comments(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Deleting one comment preserves others."""
        from app.mcp.tools.tasks import delete_comment

        task = await make_task(str(test_project.id), admin_user)
        comment1 = Comment(content="Keep me", author_id="mcp", author_name="Claude")
        comment2 = Comment(content="Delete me", author_id="mcp", author_name="Claude")
        task.comments = [comment1, comment2]
        await task.save()

        result = await delete_comment(task_id=str(task.id), comment_id=comment2.id)

        assert len(result["comments"]) == 1
        assert result["comments"][0]["content"] == "Keep me"

    async def test_delete_nonexistent_comment_raises(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Deleting a non-existent comment raises ToolError."""
        from fastmcp.exceptions import ToolError

        from app.mcp.tools.tasks import delete_comment

        task = await make_task(str(test_project.id), admin_user)

        with pytest.raises(ToolError, match="Comment not found"):
            await delete_comment(task_id=str(task.id), comment_id="nonexistent-id")

    async def test_delete_comment_on_deleted_task_raises(
        self, admin_user, test_project, mock_auth, mock_check, mock_publish
    ):
        """Deleting a comment on a soft-deleted task raises ToolError."""
        from fastmcp.exceptions import ToolError

        from app.mcp.tools.tasks import delete_comment

        task = await make_task(
            str(test_project.id), admin_user, is_deleted=True
        )

        with pytest.raises(ToolError, match="Task not found"):
            await delete_comment(task_id=str(task.id), comment_id="any-id")

    async def test_delete_comment_on_nonexistent_task_raises(
        self, mock_auth, mock_check, mock_publish
    ):
        """Deleting a comment on a non-existent task raises ToolError."""
        from fastmcp.exceptions import ToolError

        from app.mcp.tools.tasks import delete_comment

        with pytest.raises(ToolError, match="Task not found"):
            await delete_comment(
                task_id="000000000000000000000000", comment_id="any-id"
            )


# ---------------------------------------------------------------------------
# get_subtasks
# ---------------------------------------------------------------------------


class TestGetSubtasks:
    async def test_returns_subtasks_of_parent(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        parent = await make_task(pid, admin_user, title="Parent")
        child1 = await make_task(pid, admin_user, title="Child 1", parent_task_id=str(parent.id))
        child2 = await make_task(pid, admin_user, title="Child 2", parent_task_id=str(parent.id))
        # Unrelated task (no parent)
        await make_task(pid, admin_user, title="Unrelated")

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import get_subtasks

            result = await get_subtasks(task_id=str(parent.id))

        assert result["total"] == 2
        titles = {item["title"] for item in result["items"]}
        assert titles == {"Child 1", "Child 2"}

    async def test_excludes_deleted_subtasks(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        parent = await make_task(pid, admin_user, title="Parent")
        await make_task(pid, admin_user, title="Active", parent_task_id=str(parent.id))
        await make_task(pid, admin_user, title="Deleted", parent_task_id=str(parent.id), is_deleted=True)

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import get_subtasks

            result = await get_subtasks(task_id=str(parent.id))

        assert result["total"] == 1
        assert result["items"][0]["title"] == "Active"

    async def test_filter_subtasks_by_status(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        parent = await make_task(pid, admin_user, title="Parent")
        await make_task(pid, admin_user, title="Todo", parent_task_id=str(parent.id), status=TaskStatus.todo)
        await make_task(pid, admin_user, title="Done", parent_task_id=str(parent.id), status=TaskStatus.done)

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import get_subtasks

            result = await get_subtasks(task_id=str(parent.id), status="done")

        assert result["total"] == 1
        assert result["items"][0]["title"] == "Done"

    async def test_parent_not_found_raises(
        self, admin_user, test_project,
    ):
        from fastmcp.exceptions import ToolError

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import get_subtasks

            with pytest.raises(ToolError, match="Parent task not found"):
                await get_subtasks(task_id="000000000000000000000000")

    async def test_no_subtasks_returns_empty(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        parent = await make_task(pid, admin_user, title="Lonely Parent")

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import get_subtasks

            result = await get_subtasks(task_id=str(parent.id))

        assert result["total"] == 0
        assert result["items"] == []


# ---------------------------------------------------------------------------
# list_tasks date range filters
# ---------------------------------------------------------------------------


class TestListTasksDateFilter:
    async def test_due_before_filter(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        early = datetime(2025, 1, 15, tzinfo=UTC)
        late = datetime(2025, 6, 15, tzinfo=UTC)
        await make_task(pid, admin_user, title="Early", due_date=early)
        await make_task(pid, admin_user, title="Late", due_date=late)

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tasks

            # Patch _resolve_project_id to pass through
            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tasks(
                    project_id=pid,
                    due_before="2025-03-01T00:00:00+00:00",
                )

        assert result["total"] == 1
        assert result["items"][0]["title"] == "Early"

    async def test_due_after_filter(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        early = datetime(2025, 1, 15, tzinfo=UTC)
        late = datetime(2025, 6, 15, tzinfo=UTC)
        await make_task(pid, admin_user, title="Early", due_date=early)
        await make_task(pid, admin_user, title="Late", due_date=late)

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tasks

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tasks(
                    project_id=pid,
                    due_after="2025-03-01T00:00:00+00:00",
                )

        assert result["total"] == 1
        assert result["items"][0]["title"] == "Late"

    async def test_due_date_range_filter(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        d1 = datetime(2025, 1, 10, tzinfo=UTC)
        d2 = datetime(2025, 3, 15, tzinfo=UTC)
        d3 = datetime(2025, 6, 20, tzinfo=UTC)
        await make_task(pid, admin_user, title="Jan", due_date=d1)
        await make_task(pid, admin_user, title="Mar", due_date=d2)
        await make_task(pid, admin_user, title="Jun", due_date=d3)

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tasks

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tasks(
                    project_id=pid,
                    due_after="2025-02-01T00:00:00+00:00",
                    due_before="2025-05-01T00:00:00+00:00",
                )

        assert result["total"] == 1
        assert result["items"][0]["title"] == "Mar"

    async def test_no_date_filters_returns_all(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        d1 = datetime(2025, 1, 10, tzinfo=UTC)
        await make_task(pid, admin_user, title="With date", due_date=d1)
        await make_task(pid, admin_user, title="No date")

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tasks

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tasks(project_id=pid)

        assert result["total"] == 2


# ---------------------------------------------------------------------------
# list_tags
# ---------------------------------------------------------------------------


class TestListTags:
    async def test_returns_unique_tags(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        await make_task(pid, admin_user, title="T1", tags=["bug", "backend"])
        await make_task(pid, admin_user, title="T2", tags=["bug", "frontend"])
        await make_task(pid, admin_user, title="T3", tags=["feature"])

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tags

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tags(project_id=pid)

        assert result == ["backend", "bug", "feature", "frontend"]

    async def test_returns_empty_for_no_tags(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        await make_task(pid, admin_user, title="T1", tags=[])
        await make_task(pid, admin_user, title="T2")

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tags

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tags(project_id=pid)

        assert result == []

    async def test_excludes_deleted_task_tags(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        await make_task(pid, admin_user, title="Active", tags=["keep"])
        await make_task(pid, admin_user, title="Deleted", tags=["remove"], is_deleted=True)

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tags

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tags(project_id=pid)

        assert result == ["keep"]

    async def test_returns_sorted_tags(
        self, admin_user, test_project,
    ):
        pid = str(test_project.id)
        await make_task(pid, admin_user, title="T1", tags=["zeta", "alpha", "mu"])

        patches = _patch_mcp_auth()
        with patches[0], patches[1]:
            from app.mcp.tools.tasks import list_tags

            with patch(
                "app.mcp.tools.tasks._resolve_project_id",
                new_callable=AsyncMock,
                return_value=pid,
            ):
                result = await list_tags(project_id=pid)

        assert result == ["alpha", "mu", "zeta"]
