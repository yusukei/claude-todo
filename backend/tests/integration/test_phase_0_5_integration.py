"""Phase 0.5 / P0.5.7 — end-to-end integration scenarios.

These exercise multiple Phase 0.5 features in concert to verify the
new pieces compose correctly:

1. *Decision lifecycle*: AI creates a decision task → assigns a decider
   via MCP → ``stats/today`` reflects an extra ``awaiting_decision`` →
   the activity log shows the change with ``actor_type=ai``.
2. *Members table*: a user without explicit status defaults to
   ``active`` and round-trips through the admin /users endpoint.
3. *Migration parity*: the migration script reconciles legacy
   ``is_active=False`` rows to ``status='suspended'``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import ActorType, Project, Task, User, UserStatus
from app.models.project import ProjectMember
from app.models.task import TaskStatus, TaskType
from app.models.user import AuthType


pytestmark = pytest.mark.asyncio


def _load_migrate():
    """Inline migrate function — exercises the same logic as
    ``app.cli._migrate_user_status`` without re-initializing Beanie."""
    from app.models import User
    from app.models.user import UserStatus

    async def migrate() -> tuple[int, int]:
        suspended = await User.find(
            {"is_active": False, "status": {"$ne": UserStatus.suspended.value}}
        ).to_list()
        for u in suspended:
            u.status = UserStatus.suspended
            await u.save()
        active = await User.find(
            {
                "is_active": True,
                "status": {
                    "$nin": [UserStatus.active.value, UserStatus.invited.value]
                },
            }
        ).to_list()
        for u in active:
            u.status = UserStatus.active
            await u.save()
        return len(suspended), len(active)

    return migrate


@pytest_asyncio.fixture
async def project_and_decider(admin_user, regular_user) -> tuple[Project, User]:
    project = Project(
        name="Integration Project",
        color="#fc618d",
        created_by=str(admin_user.id),
        members=[
            ProjectMember(user_id=str(admin_user.id)),
            ProjectMember(user_id=str(regular_user.id)),
        ],
    )
    await project.insert()
    return project, regular_user


# ── Scenario 1: full decision-task lifecycle ─────────────────────


async def test_decision_task_lifecycle_e2e(
    client: AsyncClient,
    admin_headers,
    project_and_decider: tuple[Project, User],
):
    project, decider = project_and_decider
    pid = str(project.id)

    # 1. Baseline stats/today — empty project.
    r0 = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r0.status_code == 200
    base = r0.json()
    assert base["awaiting_decision"] == 0
    assert base["decisions_pending"] == 0

    # 2. AI creates a decision task via the MCP tool.
    from app.mcp.tools.tasks import create_task as mcp_create_task

    with patch(
        "app.mcp.tools.tasks.authenticate",
        new_callable=AsyncMock,
        return_value={
            "key_id": "k1",
            "user_id": "u1",
            "key_name": "robot",
            "is_admin": True,
            "auth_kind": "api_key",
        },
    ), patch(
        "app.mcp.tools.tasks.check_project_access"
    ), patch(
        "app.mcp.tools.tasks.publish_event", new_callable=AsyncMock
    ), patch(
        "app.mcp.tools.tasks._resolve_project_id",
        new_callable=AsyncMock,
        return_value=pid,
    ):
        created = await mcp_create_task(
            project_id=pid,
            title="Workbench layout persistence",
            task_type="decision",
            status="in_progress",
            decision_context={
                "decision_point": "Local vs server primary?",
                "background": "Needs cross-device sync",
                "options": [{"label": "local"}, {"label": "server"}],
            },
            decider_id=str(decider.id),
        )
        task_id = created["id"]

    # 3. stats/today now reports +1 in_progress + 1 awaiting_decision.
    r1 = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r1.status_code == 200
    after = r1.json()
    assert after["in_progress"] == 1
    assert after["awaiting_decision"] == 1
    assert after["decisions_pending"] == 1

    # 4. List tasks surfaces the new fields with batch enrichment.
    r2 = await client.get(f"/api/v1/projects/{pid}/tasks", headers=admin_headers)
    assert r2.status_code == 200
    item = r2.json()["items"][0]
    assert item["decider_id"] == str(decider.id)
    assert item["decider_name"] == "Regular User"
    assert item["decision_requested_at"] is not None
    assert item["task_type"] == "decision"
    assert item["subtask_count"] == 0

    # 5. AI updates the priority — activity log records actor_type=ai.
    from app.mcp.tools.tasks import update_task as mcp_update_task
    with patch(
        "app.mcp.tools.tasks.authenticate",
        new_callable=AsyncMock,
        return_value={
            "key_id": "k1",
            "user_id": "u1",
            "key_name": "robot",
            "is_admin": True,
            "auth_kind": "api_key",
        },
    ), patch(
        "app.mcp.tools.tasks.publish_event", new_callable=AsyncMock
    ):
        await mcp_update_task(task_id=task_id, priority="high")

    db_task = await Task.get(task_id)
    ai_entries = [e for e in db_task.activity_log if e.actor_type == ActorType.ai]
    assert ai_entries, "expected at least one AI-recorded activity entry"
    fields = {e.field for e in ai_entries}
    # Note: ``record_change`` only fires on update_task, not on the
    # initial Task constructor — so the activity log captures the
    # priority bump but not the decider_id we set during create.
    assert "priority" in fields

    # 6. Resolving the decision moves it out of awaiting_decision.
    with patch(
        "app.mcp.tools.tasks.authenticate",
        new_callable=AsyncMock,
        return_value={
            "key_id": "k1",
            "user_id": "u1",
            "key_name": "robot",
            "is_admin": True,
            "auth_kind": "api_key",
        },
    ), patch(
        "app.mcp.tools.tasks.publish_event", new_callable=AsyncMock
    ):
        from app.mcp.tools.tasks import complete_task as mcp_complete_task
        await mcp_complete_task(task_id=task_id, completion_report="Picked server-primary")

    r3 = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r3.status_code == 200
    final = r3.json()
    assert final["in_progress"] == 0
    assert final["awaiting_decision"] == 0
    # decisions_pending only counts != done, so it should also be 0 now
    assert final["decisions_pending"] == 0
    assert final["completed_24h"] == 1


# ── Scenario 2: members table reflects extended fields ────────────


async def test_members_table_exposes_phase_0_5_fields(
    client: AsyncClient, admin_headers
):
    invitee = User(
        email="newbie@test.com",
        name="Newbie",
        auth_type=AuthType.admin,
        status=UserStatus.invited,
    )
    await invitee.insert()

    r = await client.get("/api/v1/users", headers=admin_headers)
    assert r.status_code == 200
    by_email = {u["email"]: u for u in r.json()["items"]}
    new_row = by_email["newbie@test.com"]
    assert new_row["status"] == "invited"
    # Optional fields default sensibly when no data is available
    assert new_row["projects_count"] == 0
    assert new_row["ai_runs_30d"] == 0
    assert new_row["last_active_at"] is None


# ── Scenario 3: migration script reconciles legacy users ─────────


async def test_migration_script_reconciles_inactive_users():
    legacy = User(
        email="legacy@test.com",
        name="Legacy",
        auth_type=AuthType.admin,
        is_active=False,
    )
    await legacy.insert()
    # Simulate a pre-migration row that still has the default status.
    legacy.status = UserStatus.active
    await legacy.save()

    migrate = _load_migrate()
    suspended_count, active_count = await migrate()

    assert suspended_count >= 1
    fetched = await User.get(legacy.id)
    assert fetched is not None
    assert fetched.status == UserStatus.suspended

    # Idempotent: a second run should be a no-op for this user.
    suspended2, _ = await migrate()
    assert suspended2 == 0
