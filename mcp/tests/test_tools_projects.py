"""Tests for app.tools.projects — all project-related MCP tools."""

from unittest.mock import AsyncMock, patch

import pytest

from app.auth import McpAuthError
from app.tools.projects import get_project, get_project_summary, list_projects


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _auth_mock(scopes: list[str] | None = None):
    """Return a patch context for authenticate in the projects module."""
    return patch(
        "app.tools.projects.authenticate",
        new_callable=AsyncMock,
        return_value={"key_id": "test-key", "project_scopes": scopes or []},
    )


def _br_mock(**kwargs):
    """Return a patch context for backend_request in the projects module."""
    return patch(
        "app.tools.projects.backend_request",
        new_callable=AsyncMock,
        **kwargs,
    )


def _resolve_mock():
    """Patch resolve_project_id to pass-through (no backend call)."""
    async def _passthrough(pid: str) -> str:
        return pid
    return patch("app.tools.projects.resolve_project_id", side_effect=_passthrough)


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------

class TestListProjects:

    async def test_unscoped_lists_all(self):
        """With empty scopes, list_projects sends no project_scopes param."""
        projects = [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Beta"}]
        with _auth_mock(scopes=[]), _br_mock(return_value=projects) as mock_br:
            result = await list_projects()

        assert result == projects
        mock_br.assert_awaited_once_with("GET", "/projects", params={})

    async def test_scoped_sends_project_scopes_param(self):
        """With scopes, list_projects sends the project_scopes as a comma-joined param."""
        projects = [{"id": "p1", "name": "Alpha"}]
        with _auth_mock(scopes=["p1", "p2"]), _br_mock(return_value=projects) as mock_br:
            result = await list_projects()

        assert result == projects
        mock_br.assert_awaited_once_with("GET", "/projects", params={"project_scopes": "p1,p2"})


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------

class TestGetProject:

    async def test_returns_project_dict(self):
        """get_project fetches and returns the project."""
        project = {"id": "p1", "name": "Alpha", "members": []}
        with _auth_mock(), _resolve_mock(), _br_mock(return_value=project) as mock_br:
            result = await get_project(project_id="p1")

        assert result == project
        mock_br.assert_awaited_once_with("GET", "/projects/p1")

    async def test_scope_check_allows_matching(self):
        """get_project succeeds when project_id is in scopes."""
        project = {"id": "p1", "name": "Alpha"}
        with _auth_mock(scopes=["p1", "p2"]), _resolve_mock(), _br_mock(return_value=project):
            result = await get_project(project_id="p1")

        assert result == project

    async def test_scope_check_denies_non_matching(self):
        """get_project raises McpAuthError when project_id is not in scopes."""
        with _auth_mock(scopes=["p2"]), _resolve_mock():
            with pytest.raises(McpAuthError, match="No access to project p1"):
                await get_project(project_id="p1")


# ---------------------------------------------------------------------------
# get_project_summary
# ---------------------------------------------------------------------------

class TestGetProjectSummary:

    async def test_returns_summary_dict(self):
        """get_project_summary fetches and returns the summary."""
        summary = {
            "project_id": "p1",
            "total_tasks": 10,
            "by_status": {"todo": 3, "in_progress": 4, "done": 3},
            "completion_rate": 0.3,
        }
        with _auth_mock(), _resolve_mock(), _br_mock(return_value=summary) as mock_br:
            result = await get_project_summary(project_id="p1")

        assert result == summary
        mock_br.assert_awaited_once_with("GET", "/projects/p1/summary")

    async def test_scope_check_allows_matching(self):
        """get_project_summary succeeds when project_id is in scopes."""
        summary = {"project_id": "p1"}
        with _auth_mock(scopes=["p1"]), _resolve_mock(), _br_mock(return_value=summary):
            result = await get_project_summary(project_id="p1")

        assert result == summary

    async def test_scope_check_denies_non_matching(self):
        """get_project_summary raises McpAuthError for out-of-scope projects."""
        with _auth_mock(scopes=["p2"]), _resolve_mock():
            with pytest.raises(McpAuthError, match="No access to project p1"):
                await get_project_summary(project_id="p1")
