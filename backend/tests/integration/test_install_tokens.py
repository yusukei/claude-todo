"""Integration tests for the install-token flow (supervisor-only deployment).

Covers issue → exchange → consumption, paired-existing-agent migration,
double-consume protection, expiry, and revoke.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import hash_api_key
from app.models import InstallToken, RemoteAgent, RemoteSupervisor


# ── Issue / list / revoke ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_install_token_returns_code_and_url(client, admin_headers):
    resp = await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers,
        json={"name": "TEST-MACHINE"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"].startswith("in_")
    assert body["name"] == "TEST-MACHINE"
    assert body["install_url"].endswith(f"/install/{body['code']}")
    assert body["consumed_at"] is None
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_install_token_rejects_unknown_paired_agent(client, admin_headers):
    resp = await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers,
        json={"name": "X", "paired_existing_agent_id": "1" * 24},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_install_tokens_only_returns_own(client, admin_headers, admin_user):
    await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers,
        json={"name": "M1"},
    )
    # Drop one created by a different user.
    await InstallToken(
        code="in_" + "0" * 32, name="OTHER", created_by="someone-else",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    ).insert()

    resp = await client.get("/api/v1/workspaces/install-tokens", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "M1"


@pytest.mark.asyncio
async def test_revoke_install_token_deletes_and_blocks_exchange(client, admin_headers):
    issued = (await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers, json={"name": "X"},
    )).json()
    code = issued["code"]

    revoke = await client.delete(
        f"/api/v1/workspaces/install-tokens/{code}", headers=admin_headers,
    )
    assert revoke.status_code == 204

    # Exchange must now fail with 410.
    resp = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": code},
    )
    assert resp.status_code == 410


# ── Exchange ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_creates_supervisor_and_agent(client, admin_headers, admin_user):
    issued = (await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers, json={"name": "FRESH-HOST"},
    )).json()

    resp = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": issued["code"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["supervisor_token"].startswith("sv_")
    assert body["agent_token"].startswith("ta_")
    assert body["supervisor_name"] == "FRESH-HOST"
    assert body["agent_name"] == "FRESH-HOST-agent"
    assert "supervisor_ws" in body["backend_urls"]
    assert "agent_ws" in body["backend_urls"]

    sv = await RemoteSupervisor.get(body["supervisor_id"])
    assert sv is not None
    assert sv.paired_agent_id == body["agent_id"]
    assert sv.agent_token_hash == hash_api_key(body["agent_token"])
    assert sv.key_hash == hash_api_key(body["supervisor_token"])
    assert sv.owner_id == str(admin_user.id)

    agent = await RemoteAgent.get(body["agent_id"])
    assert agent is not None
    assert agent.key_hash == hash_api_key(body["agent_token"])
    assert agent.owner_id == str(admin_user.id)


@pytest.mark.asyncio
async def test_exchange_double_consume_returns_410(client, admin_headers):
    issued = (await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers, json={"name": "X"},
    )).json()

    first = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": issued["code"]},
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": issued["code"]},
    )
    assert second.status_code == 410


@pytest.mark.asyncio
async def test_exchange_expired_returns_410(client, admin_headers, admin_user):
    expired = InstallToken(
        code="in_" + "a" * 32,
        name="X",
        created_by=str(admin_user.id),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    await expired.insert()

    resp = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": expired.code},
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_exchange_missing_header_returns_401(client):
    resp = await client.post("/api/v1/workspaces/supervisors/exchange")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exchange_malformed_header_returns_401(client):
    resp = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": "wrong_prefix"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exchange_with_paired_existing_agent_rotates_token(
    client, admin_headers, admin_user,
):
    """Migration path: legacy agent record is preserved, only its token is rotated."""
    legacy = RemoteAgent(
        name="LEGACY",
        key_hash=hash_api_key("ta_" + "old" * 12),
        owner_id=str(admin_user.id),
        hostname="legacy-host",
    )
    await legacy.insert()
    legacy_id = str(legacy.id)
    legacy_old_hash = legacy.key_hash

    issued = (await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers,
        json={"name": "LEGACY-HOST", "paired_existing_agent_id": legacy_id},
    )).json()

    resp = await client.post(
        "/api/v1/workspaces/supervisors/exchange",
        headers={"X-Install-Token": issued["code"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Same agent record id is reused — operator-visible identity preserved.
    assert body["agent_id"] == legacy_id

    refreshed = await RemoteAgent.get(legacy_id)
    assert refreshed is not None
    assert refreshed.name == "LEGACY"  # untouched
    assert refreshed.hostname == "legacy-host"  # untouched
    assert refreshed.key_hash != legacy_old_hash
    assert refreshed.key_hash == hash_api_key(body["agent_token"])
