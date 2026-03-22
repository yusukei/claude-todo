"""Tests for app.auth — API key authentication and project scope checks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from app.auth import McpAuthError, authenticate, check_project_access


class TestAuthenticate:
    """Tests for authenticate()."""

    async def test_valid_api_key(self):
        """authenticate() returns key info when backend validates the key."""
        mock_request = MagicMock()
        mock_request.headers = {"x-api-key": "valid-key-123"}

        expected = {"key_id": "key-1", "project_scopes": ["proj-1"]}

        with (
            patch("app.auth.get_http_request", return_value=mock_request),
            patch("app.auth.backend_request", new_callable=AsyncMock, return_value=expected) as mock_br,
        ):
            result = await authenticate()

        assert result == expected
        mock_br.assert_awaited_once_with("POST", "/auth/api-key", json={"key": "valid-key-123"})

    async def test_missing_api_key_header_raises(self):
        """authenticate() raises McpAuthError when x-api-key header is absent."""
        mock_request = MagicMock()
        mock_request.headers = {}

        with (
            patch("app.auth.get_http_request", return_value=mock_request),
            pytest.raises(McpAuthError, match="X-API-Key header required"),
        ):
            await authenticate()

    async def test_no_http_context_raises(self):
        """authenticate() raises McpAuthError when HTTP request context is unavailable."""
        with (
            patch("app.auth.get_http_request", side_effect=RuntimeError("no context")),
            pytest.raises(McpAuthError, match="HTTP request context unavailable"),
        ):
            await authenticate()

    async def test_backend_error_raises(self):
        """authenticate() raises McpAuthError when backend returns an error."""
        mock_request = MagicMock()
        mock_request.headers = {"x-api-key": "bad-key"}

        with (
            patch("app.auth.get_http_request", return_value=mock_request),
            patch("app.auth.backend_request", new_callable=AsyncMock, side_effect=Exception("backend down")),
            pytest.raises(McpAuthError, match="Invalid API key"),
        ):
            await authenticate()


class TestCheckProjectAccess:
    """Tests for check_project_access()."""

    def test_empty_scopes_allows_all(self):
        """Empty scopes list means full access; no exception should be raised."""
        check_project_access("any-project", [])

    def test_matching_scope_allows(self):
        """Access is granted when project_id is in the scopes list."""
        check_project_access("proj-1", ["proj-1", "proj-2"])

    def test_non_matching_scope_raises(self):
        """Access is denied when project_id is not in the scopes list."""
        with pytest.raises(McpAuthError, match="No access to project proj-99"):
            check_project_access("proj-99", ["proj-1", "proj-2"])

    def test_mcp_auth_error_is_tool_error(self):
        """McpAuthError should be a subclass of ToolError for MCP protocol compliance."""
        assert issubclass(McpAuthError, ToolError)
