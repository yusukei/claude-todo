"""Phase 0.5 / API-1 — GET /projects/:id/stats/today tests.

Covers:
* Each of the four counters (in_progress / awaiting_decision /
  completed_24h / decisions_pending)
* archived / is_deleted exclusion
* The 24-hour boundary on completed_24h
* Cross-project isolation
* 403 on non-member access
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import Project, Task, User
from app.models.project import ProjectMember
from app.models.task import TaskPriority, TaskStatus, TaskType
from app.models.user import AuthType
from app.core.security import create_access_token


pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def project_for_stats(admin_user, regular_user) -> Project:
    project = Project(
        name="Stats Today Project",
        color="#fc618d",
        created_by=str(admin_user.id),
        members=[
            ProjectMember(user_id=str(admin_user.id)),
            ProjectMember(user_id=str(regular_user.id)),
        ],
    )
    await project.insert()
    return project


@pytest_asyncio.fixture
async def other_project(admin_user) -> Project:
    """Separate project to verify cross-project isolation."""
    project = Project(
        name="Other Project",
        color="#a9dc76",
        created_by=str(admin_user.id),
        members=[ProjectMember(user_id=str(admin_user.id))],
    )
    await project.insert()
    return project


async def _seed(
    project_id: str,
    *,
    status: TaskStatus = TaskStatus.todo,
    task_type: TaskType = TaskType.action,
    completed_at: datetime | None = None,
    archived: bool = False,
    is_deleted: bool = False,
    title: str = "t",
) -> Task:
    t = Task(
        project_id=project_id,
        title=title,
        priority=TaskPriority.medium,
        status=status,
        task_type=task_type,
        completed_at=completed_at,
        archived=archived,
        is_deleted=is_deleted,
        created_by="seed",
    )
    await t.insert()
    return t


# ── Tests ────────────────────────────────────────────────────────


async def test_stats_today_counts_each_bucket(
    client: AsyncClient, admin_headers, project_for_stats: Project
):
    pid = str(project_for_stats.id)
    now = datetime.now(UTC)

    # 3 in_progress (one is also a decision → also counted in awaiting_decision)
    await _seed(pid, status=TaskStatus.in_progress, title="ip-1")
    await _seed(pid, status=TaskStatus.in_progress, title="ip-2")
    await _seed(
        pid,
        status=TaskStatus.in_progress,
        task_type=TaskType.decision,
        title="ip-decision",
    )
    # 1 todo decision (counts toward decisions_pending only)
    await _seed(pid, status=TaskStatus.todo, task_type=TaskType.decision, title="td-decision")
    # 2 done in last 24h
    await _seed(pid, status=TaskStatus.done, completed_at=now - timedelta(hours=2), title="d-fresh-1")
    await _seed(pid, status=TaskStatus.done, completed_at=now - timedelta(hours=20), title="d-fresh-2")
    # 1 done >24h ago — must NOT count
    await _seed(pid, status=TaskStatus.done, completed_at=now - timedelta(hours=30), title="d-old")

    r = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["in_progress"] == 3
    assert body["awaiting_decision"] == 1
    assert body["completed_24h"] == 2
    # 1 todo decision + 1 in_progress decision = 2 pending (anything not done)
    assert body["decisions_pending"] == 2
    assert "as_of" in body


async def test_stats_today_excludes_archived_and_deleted(
    client: AsyncClient, admin_headers, project_for_stats: Project
):
    pid = str(project_for_stats.id)
    await _seed(pid, status=TaskStatus.in_progress, archived=True, title="ip-archived")
    await _seed(pid, status=TaskStatus.in_progress, is_deleted=True, title="ip-deleted")
    await _seed(pid, status=TaskStatus.in_progress, title="ip-real")

    r = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["in_progress"] == 1


async def test_stats_today_24h_boundary(
    client: AsyncClient, admin_headers, project_for_stats: Project
):
    """Tasks completed slightly inside the 24h window count, slightly outside don't."""
    pid = str(project_for_stats.id)
    now = datetime.now(UTC)
    await _seed(pid, status=TaskStatus.done, completed_at=now - timedelta(hours=23, minutes=59), title="just-in")
    await _seed(pid, status=TaskStatus.done, completed_at=now - timedelta(hours=24, minutes=1), title="just-out")

    r = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["completed_24h"] == 1


async def test_stats_today_isolates_other_projects(
    client: AsyncClient,
    admin_headers,
    project_for_stats: Project,
    other_project: Project,
):
    """Stats for one project must not bleed in tasks from another."""
    pid = str(project_for_stats.id)
    other_pid = str(other_project.id)
    await _seed(pid, status=TaskStatus.in_progress, title="ours")
    await _seed(other_pid, status=TaskStatus.in_progress, title="theirs-1")
    await _seed(other_pid, status=TaskStatus.in_progress, title="theirs-2")

    r = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["in_progress"] == 1


async def test_stats_today_forbids_non_member(
    client: AsyncClient, project_for_stats: Project
):
    """A user who is neither admin nor a project member must get 403."""
    outsider = User(
        email="outsider@test.com",
        name="Outsider",
        auth_type=AuthType.admin,
        is_admin=False,
        is_active=True,
    )
    await outsider.insert()
    headers = {"Authorization": f"Bearer {create_access_token(str(outsider.id))}"}

    pid = str(project_for_stats.id)
    r = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=headers)
    assert r.status_code == 403


async def test_stats_today_empty_project(
    client: AsyncClient, admin_headers, project_for_stats: Project
):
    """Brand-new project with zero tasks should return all-zero counters."""
    pid = str(project_for_stats.id)
    r = await client.get(f"/api/v1/projects/{pid}/stats/today", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "in_progress": 0,
        "awaiting_decision": 0,
        "completed_24h": 0,
        "decisions_pending": 0,
        "as_of": body["as_of"],  # any non-empty ISO string
    }
    assert body["as_of"]
