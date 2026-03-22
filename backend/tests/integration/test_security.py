"""Security-related integration tests.

Tests for:
- Path traversal attack prevention on attachments endpoint
- Comment content size validation
- MCP API key authentication (missing key, invalid key)
"""

import pytest
import pytest_asyncio

from app.core.security import create_access_token, hash_api_key
from app.models import McpApiKey, Task, User
from app.models.task import Attachment
from tests.helpers.factories import make_task


def _task_url(project_id: str, task_id: str | None = None) -> str:
    base = f"/api/v1/projects/{project_id}/tasks"
    return f"{base}/{task_id}" if task_id else base


class TestPathTraversalAttachments:
    """Verify that path traversal attacks on the attachments endpoint are blocked."""

    async def test_path_traversal_in_filename_is_rejected(
        self, client, admin_user, test_project, admin_headers
    ):
        """Attempting ../../etc/passwd in the filename should return 404 (not in attachments list)."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.get(
            f"/api/v1/attachments/{task.id}/..%2F..%2Fetc%2Fpasswd",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_path_traversal_with_dotdot_slash(
        self, client, admin_user, test_project, admin_headers
    ):
        """../../ sequences in the filename should not serve arbitrary files."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.get(
            f"/api/v1/attachments/{task.id}/../../etc/passwd",
            headers=admin_headers,
        )
        # FastAPI path routing may result in 404 or 400; either is acceptable
        assert resp.status_code in (400, 404, 422)

    async def test_path_traversal_with_attachment_in_db(
        self, client, admin_user, test_project, admin_headers
    ):
        """Even if an attachment record contains traversal chars, the path check blocks it."""
        task = await make_task(str(test_project.id), admin_user)

        # Manually inject a malicious attachment filename into the task
        malicious_filename = "../../etc/passwd"
        task.attachments.append(
            Attachment(
                filename=malicious_filename,
                content_type="image/png",
                size=100,
            )
        )
        await task.save()

        resp = await client.get(
            f"/api/v1/attachments/{task.id}/{malicious_filename}",
            headers=admin_headers,
        )
        # Should be blocked - file won't exist on disk and/or path traversal check catches it
        assert resp.status_code in (400, 404)

    async def test_null_byte_in_filename(
        self, client, admin_user, test_project, admin_headers
    ):
        """Null bytes in filename should be rejected."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.get(
            f"/api/v1/attachments/{task.id}/file%00.png",
            headers=admin_headers,
        )
        assert resp.status_code in (400, 404)


class TestCommentContentValidation:
    """Verify comment content size limits are enforced."""

    async def test_comment_within_size_limit(
        self, client, admin_user, test_project, admin_headers
    ):
        """A comment within the max_length should succeed."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.post(
            f"{_task_url(str(test_project.id), str(task.id))}/comments",
            json={"content": "A" * 1000},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    async def test_comment_at_max_length(
        self, client, admin_user, test_project, admin_headers
    ):
        """A comment exactly at max_length (10000) should succeed."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.post(
            f"{_task_url(str(test_project.id), str(task.id))}/comments",
            json={"content": "A" * 10000},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    async def test_comment_exceeding_max_length_rejected(
        self, client, admin_user, test_project, admin_headers
    ):
        """A comment exceeding max_length (10000) should be rejected with 422."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.post(
            f"{_task_url(str(test_project.id), str(task.id))}/comments",
            json={"content": "A" * 10001},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_very_large_comment_rejected(
        self, client, admin_user, test_project, admin_headers
    ):
        """A very large comment (100k chars) should be rejected."""
        task = await make_task(str(test_project.id), admin_user)

        resp = await client.post(
            f"{_task_url(str(test_project.id), str(task.id))}/comments",
            json={"content": "X" * 100_000},
            headers=admin_headers,
        )
        assert resp.status_code == 422


class TestMcpApiKeyAuthentication:
    """Test MCP API key management endpoint authentication."""

    async def test_missing_auth_returns_401_for_list(self, client):
        """GET /mcp-keys without auth token returns 401."""
        resp = await client.get("/api/v1/mcp-keys")
        assert resp.status_code == 401

    async def test_missing_auth_returns_401_for_create(self, client):
        """POST /mcp-keys without auth token returns 401."""
        resp = await client.post("/api/v1/mcp-keys", json={"name": "Test"})
        assert resp.status_code == 401

    async def test_missing_auth_returns_401_for_revoke(self, client):
        """DELETE /mcp-keys/:id without auth token returns 401."""
        resp = await client.delete("/api/v1/mcp-keys/000000000000000000000000")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client):
        """An invalid/expired JWT token should return 401."""
        resp = await client.get(
            "/api/v1/mcp-keys",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert resp.status_code == 401

    async def test_non_admin_cannot_access_mcp_keys(
        self, client, regular_user, user_headers
    ):
        """A regular (non-admin) user should get 403 on MCP key endpoints."""
        resp = await client.get("/api/v1/mcp-keys", headers=user_headers)
        assert resp.status_code == 403

        resp = await client.post(
            "/api/v1/mcp-keys",
            json={"name": "Forbidden"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_admin_can_create_and_use_key(
        self, client, admin_user, admin_headers
    ):
        """Admin can create a key and the raw key is returned only on creation."""
        resp = await client.post(
            "/api/v1/mcp-keys",
            json={"name": "Security Test Key"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "key" in data
        assert data["key"].startswith("mtodo_")

        # The key should be stored as a hash in DB
        key_doc = await McpApiKey.get(data["id"])
        assert key_doc is not None
        assert key_doc.key_hash == hash_api_key(data["key"])
        assert key_doc.key_hash != data["key"]

    async def test_revoked_key_not_in_active_list(
        self, client, admin_user, admin_headers
    ):
        """After revoking a key, it should not appear in the active keys list."""
        # Create
        create_resp = await client.post(
            "/api/v1/mcp-keys",
            json={"name": "To Revoke"},
            headers=admin_headers,
        )
        key_id = create_resp.json()["id"]

        # Revoke
        revoke_resp = await client.delete(
            f"/api/v1/mcp-keys/{key_id}", headers=admin_headers
        )
        assert revoke_resp.status_code == 204

        # Verify not in list
        list_resp = await client.get("/api/v1/mcp-keys", headers=admin_headers)
        ids = [k["id"] for k in list_resp.json()]
        assert key_id not in ids

        # Verify DB has is_active=False
        db_key = await McpApiKey.get(key_id)
        assert db_key.is_active is False
