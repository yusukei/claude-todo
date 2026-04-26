"""Phase 0.5 / API-4 — GET /users (admin) response extension tests.

Verifies the new admin-table fields:
  * ``status`` (active / invited / suspended)
  * ``last_active_at``
  * ``projects_count`` (batch-aggregated from Project.members)
  * ``ai_runs_30d``    (batch-aggregated from McpToolUsageBucket)

Existing public fields (``is_active``, ``is_admin``, etc.) must remain
unchanged for backwards compatibility.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import McpToolUsageBucket, Project, User, UserStatus
from app.models.mcp_api_key import McpApiKey
from app.models.project import ProjectMember
from app.models.user import AuthType


pytestmark = pytest.mark.asyncio


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


@pytest_asyncio.fixture
async def populated_users(admin_user, regular_user) -> tuple[User, User, User]:
    """admin_user (1 project), regular_user (2 projects), invitee (0 projects)."""
    invitee = User(
        email="invitee@test.com",
        name="Invitee",
        auth_type=AuthType.admin,
        status=UserStatus.invited,
        is_active=True,
    )
    await invitee.insert()

    p1 = Project(
        name="P1",
        color="#fc618d",
        created_by=str(admin_user.id),
        members=[
            ProjectMember(user_id=str(admin_user.id)),
            ProjectMember(user_id=str(regular_user.id)),
        ],
    )
    p2 = Project(
        name="P2",
        color="#a9dc76",
        created_by=str(regular_user.id),
        members=[ProjectMember(user_id=str(regular_user.id))],
    )
    await p1.insert()
    await p2.insert()

    return admin_user, regular_user, invitee


async def test_list_users_returns_status_and_last_active(
    client: AsyncClient, admin_headers, populated_users
):
    admin, regular, invitee = populated_users
    # Set last_active timestamps
    admin.last_active_at = datetime.now(UTC) - timedelta(minutes=10)
    await admin.save()

    r = await client.get("/api/v1/users", headers=admin_headers)
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()["items"]}

    assert by_email["admin@test.com"]["status"] == "active"
    assert by_email["admin@test.com"]["last_active_at"] is not None
    assert by_email["user@test.com"]["status"] == "active"
    assert by_email["user@test.com"]["last_active_at"] is None
    assert by_email["invitee@test.com"]["status"] == "invited"


async def test_list_users_projects_count(
    client: AsyncClient, admin_headers, populated_users
):
    r = await client.get("/api/v1/users", headers=admin_headers)
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()["items"]}
    # admin in 1 project, regular in 2, invitee in 0
    assert by_email["admin@test.com"]["projects_count"] == 1
    assert by_email["user@test.com"]["projects_count"] == 2
    assert by_email["invitee@test.com"]["projects_count"] == 0


async def test_list_users_ai_runs_30d(
    client: AsyncClient, admin_headers, populated_users
):
    admin, regular, _ = populated_users
    # Each user owns one API key that issued some calls
    admin_key = McpApiKey(
        key_hash="hash-admin",
        name="admin key",
        created_by=admin,
    )
    regular_key = McpApiKey(
        key_hash="hash-regular",
        name="regular key",
        created_by=regular,
    )
    await admin_key.insert()
    await regular_key.insert()

    now_h = _floor_hour(datetime.now(UTC))
    # Inside 30d window
    await McpToolUsageBucket(
        tool_name="t1", api_key_id=str(admin_key.id), hour=now_h - timedelta(hours=2),
        call_count=5,
    ).insert()
    await McpToolUsageBucket(
        tool_name="t2", api_key_id=str(admin_key.id), hour=now_h - timedelta(days=10),
        call_count=3,
    ).insert()
    # Outside 30d — must NOT count
    await McpToolUsageBucket(
        tool_name="t3", api_key_id=str(admin_key.id), hour=now_h - timedelta(days=40),
        call_count=99,
    ).insert()
    # Regular user's key
    await McpToolUsageBucket(
        tool_name="t1", api_key_id=str(regular_key.id), hour=now_h - timedelta(hours=1),
        call_count=2,
    ).insert()

    r = await client.get("/api/v1/users", headers=admin_headers)
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()["items"]}

    assert by_email["admin@test.com"]["ai_runs_30d"] == 8  # 5 + 3
    assert by_email["user@test.com"]["ai_runs_30d"] == 2
    assert by_email["invitee@test.com"]["ai_runs_30d"] == 0


async def test_list_users_non_admin_forbidden(
    client: AsyncClient, user_headers, populated_users
):
    r = await client.get("/api/v1/users", headers=user_headers)
    assert r.status_code == 403


async def test_list_users_preserves_legacy_is_active(
    client: AsyncClient, admin_headers, populated_users
):
    """The new ``status`` lives alongside ``is_active`` — it does not
    replace it (yet)."""
    r = await client.get("/api/v1/users", headers=admin_headers)
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()["items"]}
    for email in ("admin@test.com", "user@test.com", "invitee@test.com"):
        assert "is_active" in by_email[email]
