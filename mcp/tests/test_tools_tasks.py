"""Tests for app.tools.tasks — all task-related MCP tools."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from app.auth import McpAuthError
from app.tools.tasks import (
    add_comment,
    complete_task,
    create_task,
    delete_task,
    get_task,
    list_overdue_tasks,
    list_tasks,
    list_users,
    search_tasks,
    update_task,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _auth_mock(scopes: list[str] | None = None):
    """Return a patch context for authenticate in the tasks module."""
    return patch(
        "app.tools.tasks.authenticate",
        new_callable=AsyncMock,
        return_value={"key_id": "test-key", "project_scopes": scopes or []},
    )


def _br_mock(**kwargs):
    """Return a patch context for backend_request in the tasks module."""
    return patch(
        "app.tools.tasks.backend_request",
        new_callable=AsyncMock,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------

class TestListTasks:

    async def test_basic_list(self):
        """list_tasks passes project_id and returns task list."""
        tasks = [{"id": "t1", "title": "Task 1"}]
        with _auth_mock(), _br_mock(return_value=tasks) as mock_br:
            result = await list_tasks(project_id="proj-1")

        assert result == tasks
        mock_br.assert_awaited_once_with("GET", "/projects/proj-1/tasks", params={})

    async def test_with_status_filter(self):
        """Status filter is forwarded as 'task_status' param key (backend convention)."""
        with _auth_mock(), _br_mock(return_value=[]) as mock_br:
            await list_tasks(project_id="proj-1", status="todo")

        mock_br.assert_awaited_once_with("GET", "/projects/proj-1/tasks", params={"task_status": "todo"})

    async def test_with_multiple_filters(self):
        """Multiple filters are all forwarded as params."""
        with _auth_mock(), _br_mock(return_value=[]) as mock_br:
            await list_tasks(project_id="proj-1", status="in_progress", priority="high", tag="bug")

        call_params = mock_br.call_args.kwargs["params"]
        assert call_params == {"task_status": "in_progress", "priority": "high", "tag": "bug"}

    async def test_scope_check_enforced(self):
        """list_tasks raises McpAuthError when project is out of scope."""
        with _auth_mock(scopes=["proj-other"]):
            with pytest.raises(McpAuthError, match="No access to project proj-1"):
                await list_tasks(project_id="proj-1")


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------

class TestGetTask:

    async def test_returns_task_dict(self):
        """get_task fetches and returns the task."""
        task = {"id": "t1", "project_id": "proj-1", "title": "Task"}
        with _auth_mock(), _br_mock(return_value=task) as mock_br:
            result = await get_task(task_id="t1")

        assert result == task
        mock_br.assert_awaited_once_with("GET", "/tasks/t1")

    async def test_scope_check_after_fetch(self):
        """get_task fetches the task first then checks project scope."""
        task = {"id": "t1", "project_id": "proj-99", "title": "Task"}
        with _auth_mock(scopes=["proj-1"]), _br_mock(return_value=task):
            with pytest.raises(McpAuthError, match="No access to project proj-99"):
                await get_task(task_id="t1")


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

class TestCreateTask:

    async def test_minimal_create(self):
        """create_task sends correct body with required fields."""
        created = {"id": "t-new", "title": "New task"}
        with _auth_mock(), _br_mock(return_value=created) as mock_br:
            result = await create_task(project_id="proj-1", title="New task")

        assert result == created
        call_json = mock_br.call_args.kwargs["json"]
        assert call_json["title"] == "New task"
        assert call_json["created_by"] == "mcp"
        assert call_json["priority"] == "medium"
        assert call_json["status"] == "todo"

    async def test_full_create(self):
        """create_task includes all optional fields when provided."""
        with _auth_mock(), _br_mock(return_value={"id": "t-new"}) as mock_br:
            await create_task(
                project_id="proj-1",
                title="Full task",
                description="Detailed description",
                priority="high",
                status="in_progress",
                due_date="2025-12-31T00:00:00",
                assignee_id="user-1",
                parent_task_id="t-parent",
                tags=["bug", "urgent"],
            )

        body = mock_br.call_args.kwargs["json"]
        assert body["description"] == "Detailed description"
        assert body["priority"] == "high"
        assert body["status"] == "in_progress"
        assert body["due_date"] == "2025-12-31T00:00:00"
        assert body["assignee_id"] == "user-1"
        assert body["parent_task_id"] == "t-parent"
        assert body["tags"] == ["bug", "urgent"]

    async def test_scope_check_enforced(self):
        """create_task respects project scopes."""
        with _auth_mock(scopes=["proj-other"]):
            with pytest.raises(McpAuthError):
                await create_task(project_id="proj-1", title="Test")


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------

class TestUpdateTask:

    async def test_valid_update(self):
        """update_task sends PATCH with only non-None fields."""
        task = {"id": "t1", "project_id": "proj-1"}
        updated = {"id": "t1", "title": "Updated", "status": "done"}
        with _auth_mock(), _br_mock(side_effect=[task, updated]) as mock_br:
            result = await update_task(task_id="t1", title="Updated", status="done")

        assert result == updated
        # First call: GET to fetch task for scope check
        assert mock_br.call_args_list[0].args == ("GET", "/tasks/t1")
        # Second call: PATCH with updates
        patch_call = mock_br.call_args_list[1]
        assert patch_call.args == ("PATCH", "/tasks/t1")
        assert patch_call.kwargs["json"] == {"title": "Updated", "status": "done"}

    async def test_invalid_status_raises_tool_error(self):
        """update_task raises ToolError for invalid status values."""
        with _auth_mock():
            with pytest.raises(ToolError, match="Invalid status"):
                await update_task(task_id="t1", status="invalid_status")

    async def test_invalid_priority_raises_tool_error(self):
        """update_task raises ToolError for invalid priority values."""
        with _auth_mock():
            with pytest.raises(ToolError, match="Invalid priority"):
                await update_task(task_id="t1", priority="super_high")

    async def test_scope_check_after_fetch(self):
        """update_task checks scope against the fetched task's project_id."""
        task = {"id": "t1", "project_id": "proj-restricted"}
        with _auth_mock(scopes=["proj-1"]), _br_mock(return_value=task):
            with pytest.raises(McpAuthError, match="No access to project proj-restricted"):
                await update_task(task_id="t1", title="Nope")


# ---------------------------------------------------------------------------
# delete_task
# ---------------------------------------------------------------------------

class TestDeleteTask:

    async def test_successful_delete(self):
        """delete_task returns success dict after deletion."""
        task = {"id": "t1", "project_id": "proj-1"}
        # backend_request calls: GET (fetch), DELETE (returns None for 204 or similar)
        with _auth_mock(), _br_mock(side_effect=[task, None]) as mock_br:
            result = await delete_task(task_id="t1")

        assert result == {"success": True, "task_id": "t1"}
        assert mock_br.call_args_list[1].args == ("DELETE", "/tasks/t1")

    async def test_scope_check(self):
        """delete_task checks project scope before deleting."""
        task = {"id": "t1", "project_id": "proj-restricted"}
        with _auth_mock(scopes=["proj-1"]), _br_mock(return_value=task):
            with pytest.raises(McpAuthError):
                await delete_task(task_id="t1")


# ---------------------------------------------------------------------------
# complete_task
# ---------------------------------------------------------------------------

class TestCompleteTask:

    async def test_marks_task_done(self):
        """complete_task sends PATCH with status=done."""
        task = {"id": "t1", "project_id": "proj-1"}
        completed = {"id": "t1", "status": "done"}
        with _auth_mock(), _br_mock(side_effect=[task, completed]) as mock_br:
            result = await complete_task(task_id="t1")

        assert result == completed
        patch_call = mock_br.call_args_list[1]
        assert patch_call.args == ("PATCH", "/tasks/t1")
        assert patch_call.kwargs["json"] == {"status": "done"}

    async def test_scope_check(self):
        """complete_task checks project scope before completing."""
        task = {"id": "t1", "project_id": "proj-99"}
        with _auth_mock(scopes=["proj-1"]), _br_mock(return_value=task):
            with pytest.raises(McpAuthError):
                await complete_task(task_id="t1")


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------

class TestAddComment:

    async def test_adds_comment_with_author(self):
        """add_comment sends POST with content and author_name='Claude'."""
        task = {"id": "t1", "project_id": "proj-1"}
        comment = {"id": "c1", "content": "Done", "author_name": "Claude"}
        with _auth_mock(), _br_mock(side_effect=[task, comment]) as mock_br:
            result = await add_comment(task_id="t1", content="Done")

        assert result == comment
        post_call = mock_br.call_args_list[1]
        assert post_call.args == ("POST", "/tasks/t1/comments")
        body = post_call.kwargs["json"]
        assert body["content"] == "Done"
        assert body["author_name"] == "Claude"

    async def test_scope_check(self):
        """add_comment checks project scope before adding."""
        task = {"id": "t1", "project_id": "proj-restricted"}
        with _auth_mock(scopes=["proj-1"]), _br_mock(return_value=task):
            with pytest.raises(McpAuthError):
                await add_comment(task_id="t1", content="Test")


# ---------------------------------------------------------------------------
# search_tasks
# ---------------------------------------------------------------------------

class TestSearchTasks:

    async def test_search_with_project_id(self):
        """search_tasks scoped to a single project returns matching tasks."""
        tasks = [
            {"id": "t1", "title": "Fix login bug", "description": ""},
            {"id": "t2", "title": "Add signup page", "description": ""},
        ]
        with _auth_mock(), _br_mock(return_value=tasks):
            result = await search_tasks(query="login", project_id="proj-1")

        assert len(result) == 1
        assert result[0]["id"] == "t1"

    async def test_search_without_project_id_uses_all_projects(self):
        """When no project_id, search_tasks queries all accessible projects."""
        projects = [{"id": "proj-1"}, {"id": "proj-2"}]
        tasks_p1 = [{"id": "t1", "title": "Deploy app", "description": ""}]
        tasks_p2 = [{"id": "t2", "title": "Deploy service", "description": ""}]

        async def side_effect(method, path, **kwargs):
            if path == "/projects":
                return projects
            if "proj-1" in path:
                return tasks_p1
            if "proj-2" in path:
                return tasks_p2
            return []

        with _auth_mock(), _br_mock(side_effect=side_effect):
            result = await search_tasks(query="deploy")

        assert len(result) == 2

    async def test_search_matches_description(self):
        """search_tasks matches against description field too."""
        tasks = [
            {"id": "t1", "title": "Task", "description": "Fix the critical bug"},
        ]
        with _auth_mock(), _br_mock(return_value=tasks):
            result = await search_tasks(query="critical", project_id="proj-1")

        assert len(result) == 1

    async def test_search_case_insensitive(self):
        """search_tasks performs case-insensitive matching."""
        tasks = [
            {"id": "t1", "title": "Deploy Application", "description": ""},
        ]
        with _auth_mock(), _br_mock(return_value=tasks):
            result = await search_tasks(query="deploy", project_id="proj-1")

        assert len(result) == 1

    async def test_search_with_scopes_uses_scoped_projects(self):
        """When key has scopes but no project_id, search uses scoped project list."""
        tasks = [{"id": "t1", "title": "Match", "description": ""}]

        async def side_effect(method, path, **kwargs):
            if "/projects/" in path and "/tasks" in path:
                return tasks
            return []

        with _auth_mock(scopes=["proj-1"]), _br_mock(side_effect=side_effect):
            result = await search_tasks(query="match")

        assert len(result) == 1

    async def test_search_scope_check_with_project_id(self):
        """search_tasks checks scope when project_id is explicitly provided."""
        with _auth_mock(scopes=["proj-other"]):
            with pytest.raises(McpAuthError):
                await search_tasks(query="test", project_id="proj-1")


# ---------------------------------------------------------------------------
# list_overdue_tasks
# ---------------------------------------------------------------------------

class TestListOverdueTasks:

    async def test_returns_overdue_tasks(self):
        """list_overdue_tasks filters tasks past their due_date."""
        tasks = [
            {"id": "t1", "title": "Overdue", "due_date": "2020-01-01T00:00:00", "status": "todo"},
            {"id": "t2", "title": "Future", "due_date": "2099-12-31T00:00:00", "status": "todo"},
            {"id": "t3", "title": "No due", "due_date": None, "status": "todo"},
        ]
        projects = [{"id": "proj-1"}]

        async def side_effect(method, path, **kwargs):
            if path == "/projects":
                return projects
            return tasks

        with _auth_mock(), _br_mock(side_effect=side_effect):
            result = await list_overdue_tasks()

        assert len(result) == 1
        assert result[0]["id"] == "t1"

    async def test_excludes_done_and_cancelled(self):
        """Overdue tasks with status 'done' or 'cancelled' are excluded."""
        tasks = [
            {"id": "t1", "title": "Done overdue", "due_date": "2020-01-01T00:00:00", "status": "done"},
            {"id": "t2", "title": "Cancelled overdue", "due_date": "2020-01-01T00:00:00", "status": "cancelled"},
            {"id": "t3", "title": "Active overdue", "due_date": "2020-01-01T00:00:00", "status": "in_progress"},
        ]
        projects = [{"id": "proj-1"}]

        async def side_effect(method, path, **kwargs):
            if path == "/projects":
                return projects
            return tasks

        with _auth_mock(), _br_mock(side_effect=side_effect):
            result = await list_overdue_tasks()

        assert len(result) == 1
        assert result[0]["id"] == "t3"

    async def test_sorted_by_due_date(self):
        """Results are sorted by due_date ascending."""
        tasks = [
            {"id": "t2", "title": "Later", "due_date": "2020-06-01T00:00:00", "status": "todo"},
            {"id": "t1", "title": "Earlier", "due_date": "2020-01-01T00:00:00", "status": "todo"},
        ]
        projects = [{"id": "proj-1"}]

        async def side_effect(method, path, **kwargs):
            if path == "/projects":
                return projects
            return tasks

        with _auth_mock(), _br_mock(side_effect=side_effect):
            result = await list_overdue_tasks()

        assert result[0]["id"] == "t1"
        assert result[1]["id"] == "t2"

    async def test_with_project_id(self):
        """list_overdue_tasks scoped to a specific project."""
        tasks = [
            {"id": "t1", "title": "Overdue", "due_date": "2020-01-01T00:00:00", "status": "todo"},
        ]
        with _auth_mock(), _br_mock(return_value=tasks):
            result = await list_overdue_tasks(project_id="proj-1")

        assert len(result) == 1

    async def test_scope_check_with_project_id(self):
        """list_overdue_tasks checks scope when project_id is given."""
        with _auth_mock(scopes=["proj-other"]):
            with pytest.raises(McpAuthError):
                await list_overdue_tasks(project_id="proj-1")


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

class TestListUsers:

    async def test_returns_user_list(self):
        """list_users returns the user list from backend."""
        users = [{"id": "u1", "name": "Alice"}, {"id": "u2", "name": "Bob"}]
        with _auth_mock(), _br_mock(return_value=users) as mock_br:
            result = await list_users()

        assert result == users
        mock_br.assert_awaited_once_with("GET", "/users")
