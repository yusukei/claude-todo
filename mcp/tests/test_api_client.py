"""Tests for app.api_client — backend HTTP client with retry logic."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import app.api_client as api_client_module
from app.api_client import backend_request


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level _client before each test so tests are isolated."""
    api_client_module._client = None
    yield
    # Also close after the test if a real client was created
    if api_client_module._client and not api_client_module._client.is_closed:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(api_client_module._client.aclose())
        except RuntimeError:
            pass
    api_client_module._client = None


@pytest.fixture(autouse=True)
def _fast_retries():
    """Eliminate retry delays so tests run instantly."""
    with patch.object(api_client_module, "RETRY_DELAYS", [0, 0, 0]):
        yield


class TestBackendRequestSuccess:
    """Tests for successful backend_request calls."""

    @respx.mock
    async def test_get_returns_dict(self):
        """Successful GET returns parsed JSON dict."""
        route = respx.get("http://localhost:8000/api/v1/internal/tasks/1").mock(
            return_value=httpx.Response(200, json={"id": "task-1", "title": "Test"})
        )

        result = await backend_request("GET", "/tasks/1")

        assert result == {"id": "task-1", "title": "Test"}
        assert route.called

    @respx.mock
    async def test_post_returns_dict(self):
        """Successful POST returns parsed JSON dict."""
        route = respx.post("http://localhost:8000/api/v1/internal/projects/p1/tasks").mock(
            return_value=httpx.Response(201, json={"id": "task-new", "title": "Created"})
        )

        result = await backend_request("POST", "/projects/p1/tasks", json={"title": "Created"})

        assert result == {"id": "task-new", "title": "Created"}
        assert route.called


    @respx.mock
    async def test_204_returns_none(self):
        """204 No Content response returns None instead of trying to parse JSON."""
        route = respx.delete("http://localhost:8000/api/v1/internal/tasks/1").mock(
            return_value=httpx.Response(204)
        )

        result = await backend_request("DELETE", "/tasks/1")

        assert result is None
        assert route.called


class TestBackendRequestErrorHandling:
    """Tests for error handling and retry behavior."""

    @respx.mock
    async def test_404_raises_tool_error_no_retry(self):
        """4xx errors are NOT retried; ToolError is raised with detail message."""
        route = respx.get("http://localhost:8000/api/v1/internal/tasks/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Task not found"})
        )

        with pytest.raises(ToolError, match="Task not found"):
            await backend_request("GET", "/tasks/missing")

        assert route.call_count == 1  # no retries for 4xx

    @respx.mock
    async def test_422_raises_tool_error_no_retry(self):
        """422 (validation error) is a 4xx and should not be retried."""
        route = respx.post("http://localhost:8000/api/v1/internal/projects/p1/tasks").mock(
            return_value=httpx.Response(422, json={"detail": "Validation error"})
        )

        with pytest.raises(ToolError, match="Validation error"):
            await backend_request("POST", "/projects/p1/tasks", json={})

        assert route.call_count == 1

    @respx.mock
    async def test_500_retries_then_raises(self):
        """5xx triggers retries; after MAX_RETRIES exhausted, raises the last error."""
        route = respx.get("http://localhost:8000/api/v1/internal/tasks/1").mock(
            return_value=httpx.Response(500, json={"detail": "Internal error"})
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await backend_request("GET", "/tasks/1")

        assert exc_info.value.response.status_code == 500
        assert route.call_count == 3  # MAX_RETRIES = 3

    @respx.mock
    async def test_connect_error_retries_then_raises(self):
        """ConnectError triggers retries; after exhaustion, raises."""
        route = respx.get("http://localhost:8000/api/v1/internal/tasks/1").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(httpx.ConnectError):
            await backend_request("GET", "/tasks/1")

        assert route.call_count == 3  # MAX_RETRIES = 3

    @respx.mock
    async def test_500_then_success_on_retry(self):
        """5xx followed by success: retry succeeds and returns data."""
        route = respx.get("http://localhost:8000/api/v1/internal/tasks/1").mock(
            side_effect=[
                httpx.Response(500, json={"detail": "temporary"}),
                httpx.Response(200, json={"id": "task-1", "title": "OK"}),
            ]
        )

        result = await backend_request("GET", "/tasks/1")

        assert result == {"id": "task-1", "title": "OK"}
        assert route.call_count == 2


class TestBackendRequestUrlConstruction:
    """Verify that the internal URL prefix is applied correctly."""

    @respx.mock
    async def test_url_has_internal_prefix(self):
        """The path should be prefixed with /api/v1/internal."""
        route = respx.get("http://localhost:8000/api/v1/internal/projects").mock(
            return_value=httpx.Response(200, json=[])
        )

        await backend_request("GET", "/projects")

        assert route.called

    @respx.mock
    async def test_params_are_forwarded(self):
        """Query parameters passed via kwargs are forwarded to httpx."""
        route = respx.get("http://localhost:8000/api/v1/internal/projects/p1/tasks").mock(
            return_value=httpx.Response(200, json=[])
        )

        await backend_request("GET", "/projects/p1/tasks", params={"status": "todo"})

        assert route.called
        call_request = route.calls[0].request
        assert "status=todo" in str(call_request.url)
