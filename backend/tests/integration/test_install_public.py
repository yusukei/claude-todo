"""Integration tests for the public ``GET /install/{code}`` endpoint.

Verifies the bootstrap PowerShell script is rendered correctly and
that invalid / consumed / expired install tokens return a clear error
script (so ``iex`` surfaces a useful message instead of silently no-op).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import InstallToken, SupervisorRelease


@pytest.mark.asyncio
async def test_install_returns_powershell_script_for_active_token(
    client, admin_headers, admin_user,
):
    # Seed a SupervisorRelease so the endpoint has something to point at.
    sv_release = SupervisorRelease(
        version="9.9.9",
        os_type="win32", arch="x64", channel="stable",
        storage_path="win32/stable/x64/mcp-workspace-supervisor-9.9.9.exe",
        sha256="ab" * 32, size_bytes=12345,
        uploaded_by=str(admin_user.id),
    )
    await sv_release.insert()

    issued = (await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers, json={"name": "BOOT"},
    )).json()

    resp = await client.get(f"/install/{issued['code']}")
    assert resp.status_code == 200
    body = resp.text
    # Must reference the install_token, the SupervisorRelease sha, and the
    # critical PowerShell entry points the user is going to pipe through iex.
    assert issued["code"] in body
    assert sv_release.sha256 in body
    assert "Invoke-WebRequest" in body
    assert "--bootstrap" in body
    assert "X-Install-Token" in body


@pytest.mark.asyncio
async def test_install_returns_410_script_for_unknown_code(client):
    resp = await client.get("/install/in_" + "0" * 32)
    assert resp.status_code == 410
    assert "throw" in resp.text  # error script


@pytest.mark.asyncio
async def test_install_returns_410_script_for_expired_token(client, admin_user):
    expired = InstallToken(
        code="in_" + "b" * 32,
        name="X",
        created_by=str(admin_user.id),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    await expired.insert()

    resp = await client.get(f"/install/{expired.code}")
    assert resp.status_code == 410
    assert "expired" in resp.text.lower()


@pytest.mark.asyncio
async def test_install_returns_410_script_for_consumed_token(client, admin_user):
    consumed = InstallToken(
        code="in_" + "c" * 32,
        name="X",
        created_by=str(admin_user.id),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        consumed_at=datetime.now(UTC),
        consumed_by_supervisor_id="someid",
    )
    await consumed.insert()

    resp = await client.get(f"/install/{consumed.code}")
    assert resp.status_code == 410
    assert "consumed" in resp.text.lower()


@pytest.mark.asyncio
async def test_install_returns_503_script_when_no_supervisor_release(
    client, admin_headers,
):
    # No SupervisorRelease seeded.
    issued = (await client.post(
        "/api/v1/workspaces/install-tokens",
        headers=admin_headers, json={"name": "X"},
    )).json()

    resp = await client.get(f"/install/{issued['code']}")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_install_rejects_malformed_code(client):
    resp = await client.get("/install/not-a-valid-code")
    # FastAPI Path regex enforcement returns 422 before our handler runs.
    assert resp.status_code == 422
