"""Shared fixtures for MCP server tests."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def mock_authenticate():
    """Patch authenticate to return an unscoped key (full access)."""
    with patch("app.auth.authenticate", new_callable=AsyncMock) as m:
        m.return_value = {"key_id": "test-key", "project_scopes": []}
        yield m


@pytest.fixture()
def mock_authenticate_scoped():
    """Patch authenticate to return a key scoped to proj-1 only."""
    with patch("app.auth.authenticate", new_callable=AsyncMock) as m:
        m.return_value = {"key_id": "test-key", "project_scopes": ["proj-1"]}
        yield m


@pytest.fixture()
def mock_backend_request():
    """Patch backend_request as an AsyncMock configurable per test."""
    with patch("app.api_client.backend_request", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture()
def sample_task():
    """Return a dict matching the task structure from backend."""
    return {
        "id": "task-1",
        "project_id": "proj-1",
        "title": "Test task",
        "description": "A task for testing",
        "status": "todo",
        "priority": "medium",
        "due_date": None,
        "assignee_id": None,
        "parent_task_id": None,
        "tags": [],
        "comments": [],
        "created_by": "mcp",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


@pytest.fixture()
def sample_project():
    """Return a dict matching the project structure from backend."""
    return {
        "id": "proj-1",
        "name": "Test Project",
        "description": "A project for testing",
        "members": [
            {"user_id": "user-1", "role": "owner"},
        ],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
