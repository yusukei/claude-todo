"""Integration tests for /workspaces/agents endpoints, focused on token rotation.

The agent CRUD path (create / delete) is exercised end-to-end here so that
the rotate-token flow can be verified against a realistic database state.
"""

from app.core.security import hash_api_key
from app.models import McpApiKey
from app.models.remote import RemoteAgent


class TestCreateAgent:
    async def test_admin_can_create_agent(self, client, admin_user, admin_headers):
        resp = await client.post(
            "/api/v1/workspaces/agents",
            json={"name": "build-host"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "build-host"
        assert body["token"].startswith("ta_")
        assert "id" in body

        stored = await RemoteAgent.get(body["id"])
        assert stored is not None
        assert stored.key_hash == hash_api_key(body["token"])

    async def test_regular_user_cannot_create_agent(self, client, regular_user, user_headers):
        resp = await client.post(
            "/api/v1/workspaces/agents",
            json={"name": "should-fail"},
            headers=user_headers,
        )
        assert resp.status_code == 403


class TestRotateAgentToken:
    async def test_rotate_issues_new_token_and_invalidates_old(
        self, client, admin_user, admin_headers
    ):
        create_resp = await client.post(
            "/api/v1/workspaces/agents",
            json={"name": "rotate-target"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["id"]
        old_token = create_resp.json()["token"]
        old_hash = hash_api_key(old_token)

        rotate_resp = await client.post(
            f"/api/v1/workspaces/agents/{agent_id}/rotate-token",
            headers=admin_headers,
        )
        assert rotate_resp.status_code == 200
        new_token = rotate_resp.json()["token"]
        assert new_token.startswith("ta_")
        assert new_token != old_token

        stored = await RemoteAgent.get(agent_id)
        assert stored is not None
        assert stored.key_hash == hash_api_key(new_token)
        assert stored.key_hash != old_hash  # old token can no longer authenticate

    async def test_rotate_unknown_agent_returns_404(self, client, admin_user, admin_headers):
        resp = await client.post(
            "/api/v1/workspaces/agents/000000000000000000000000/rotate-token",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_rotate_agent_owned_by_other_admin_returns_404(
        self, client, admin_user, regular_user, admin_headers, user_headers
    ):
        # Create as admin
        create_resp = await client.post(
            "/api/v1/workspaces/agents",
            json={"name": "admin-only"},
            headers=admin_headers,
        )
        agent_id = create_resp.json()["id"]

        # Regular user is not admin → 403 from get_admin_user
        resp = await client.post(
            f"/api/v1/workspaces/agents/{agent_id}/rotate-token",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_unauthenticated_rotate_rejected(self, client):
        resp = await client.post(
            "/api/v1/workspaces/agents/000000000000000000000000/rotate-token"
        )
        assert resp.status_code == 401


class TestApiKeyFlexibleAuth:
    """The admin endpoints accept an admin-owned MCP API key so CI / CLIs
    can run unattended.

    The flexible dependency delegates to the same ``is_admin`` check, so a
    key owned by a regular user still gets 403 — we're widening the *auth*
    surface, not the *permission* surface.
    """

    async def _create_api_key(self, owner, token: str) -> McpApiKey:
        key = McpApiKey(
            key_hash=hash_api_key(token),
            name="test-key",
            created_by=owner,
        )
        await key.insert()
        return key

    async def test_admin_api_key_can_list_agents(self, client, admin_user):
        token = "mcp_admin_flex_0001"
        await self._create_api_key(admin_user, token)

        resp = await client.get(
            "/api/v1/workspaces/agents",
            headers={"X-API-Key": token},
        )
        assert resp.status_code == 200

    async def test_non_admin_api_key_rejected_403(self, client, regular_user):
        token = "mcp_user_flex_0002"
        await self._create_api_key(regular_user, token)

        resp = await client.get(
            "/api/v1/workspaces/agents",
            headers={"X-API-Key": token},
        )
        assert resp.status_code == 403

    async def test_unknown_api_key_rejected_401(self, client):
        resp = await client.get(
            "/api/v1/workspaces/agents",
            headers={"X-API-Key": "mcp_definitely_not_real"},
        )
        assert resp.status_code == 401

    async def test_inactive_api_key_rejected_401(self, client, admin_user):
        token = "mcp_admin_inactive_0003"
        key = await self._create_api_key(admin_user, token)
        key.is_active = False
        await key.save()

        resp = await client.get(
            "/api/v1/workspaces/agents",
            headers={"X-API-Key": token},
        )
        assert resp.status_code == 401

    async def test_jwt_still_works(self, client, admin_user, admin_headers):
        """Flexible auth must not regress the existing cookie/Bearer path."""
        resp = await client.get(
            "/api/v1/workspaces/agents",
            headers=admin_headers,
        )
        assert resp.status_code == 200


class TestDeleteAgent:
    async def test_delete_agent_unregisters_live_connection(
        self, client, admin_user, admin_headers
    ):
        """Regression: ``DELETE /agents/{id}`` MUST await ``unregister``.

        The earlier implementation called ``agent_manager.unregister``
        without ``await``, which silently discarded the coroutine and
        left WebSocket / pending state intact. This test registers a
        fake connection, deletes the agent, and asserts the
        in-process state is actually torn down.
        """
        create_resp = await client.post(
            "/api/v1/workspaces/agents",
            json={"name": "delete-target"},
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["id"]

        # Register a fake WebSocket so unregister has something to clean up.
        from app.services.agent_manager import agent_manager

        class _FakeWS:
            async def send_text(self, _payload: str) -> None:
                pass

            async def close(self, code: int = 1000, reason: str = "") -> None:
                pass

        await agent_manager.register(agent_id, _FakeWS())  # type: ignore[arg-type]
        assert agent_manager.is_connected(agent_id)

        del_resp = await client.delete(
            f"/api/v1/workspaces/agents/{agent_id}",
            headers=admin_headers,
        )
        assert del_resp.status_code == 204
        # If unregister was not awaited, the in-process state would
        # still report the agent as connected.
        assert not agent_manager.is_connected(agent_id)
        assert await RemoteAgent.get(agent_id) is None
