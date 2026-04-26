"""Phase 0.5 / API-2 — GET /projects/:id/tasks response extension tests.

Verifies that the list endpoint includes the new batch-enriched fields:

* ``subtask_count``
* ``blocked_by_count``
* ``assignee_name``
* ``decider_name``
* ``decider_id`` / ``decision_requested_at`` (passed through from model)

and that single-task endpoints still expose the cheap ``blocked_by_count``
field while batch-only fields fall through to ``None``.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import Project, Task, User
from app.models.project import ProjectMember
from app.models.task import TaskPriority, TaskStatus, TaskType
from app.models.user import AuthType


pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def people() -> tuple[User, User]:
    koji = User(email="koji@test.com", name="Koji", auth_type=AuthType.admin)
    yusuke = User(email="yusuke@test.com", name="Yusuke", auth_type=AuthType.admin)
    await koji.insert()
    await yusuke.insert()
    return koji, yusuke


@pytest_asyncio.fixture
async def project_for_list(admin_user, regular_user) -> Project:
    project = Project(
        name="List Tasks Project",
        color="#fc618d",
        created_by=str(admin_user.id),
        members=[
            ProjectMember(user_id=str(admin_user.id)),
            ProjectMember(user_id=str(regular_user.id)),
        ],
    )
    await project.insert()
    return project


# ── Tests ────────────────────────────────────────────────────────


async def test_list_tasks_includes_batch_enriched_fields(
    client: AsyncClient,
    admin_headers,
    project_for_list: Project,
    people: tuple[User, User],
):
    koji, yusuke = people
    pid = str(project_for_list.id)

    # Decision parent with assignee + decider, plus 2 subtasks
    parent = Task(
        project_id=pid,
        title="Decision Parent",
        priority=TaskPriority.high,
        status=TaskStatus.in_progress,
        task_type=TaskType.decision,
        assignee_id=str(yusuke.id),
        decider_id=str(koji.id),
        decision_requested_at=datetime.now(UTC),
        created_by="seed",
    )
    await parent.insert()

    sub1 = Task(
        project_id=pid,
        title="Sub 1",
        parent_task_id=str(parent.id),
        priority=TaskPriority.low,
        created_by="seed",
    )
    await sub1.insert()
    sub2 = Task(
        project_id=pid,
        title="Sub 2",
        parent_task_id=str(parent.id),
        priority=TaskPriority.low,
        created_by="seed",
    )
    await sub2.insert()

    # Standalone task with blocked_by entries
    blocker = Task(
        project_id=pid,
        title="Blocked Task",
        blocked_by=["task-x", "task-y"],
        created_by="seed",
    )
    await blocker.insert()

    r = await client.get(f"/api/v1/projects/{pid}/tasks", headers=admin_headers)
    assert r.status_code == 200
    items = {item["title"]: item for item in r.json()["items"]}

    parent_dict = items["Decision Parent"]
    assert parent_dict["subtask_count"] == 2
    assert parent_dict["assignee_name"] == "Yusuke"
    assert parent_dict["decider_name"] == "Koji"
    assert parent_dict["decider_id"] == str(koji.id)
    assert parent_dict["decision_requested_at"] is not None
    assert parent_dict["blocked_by_count"] == 0

    blocker_dict = items["Blocked Task"]
    assert blocker_dict["blocked_by_count"] == 2
    assert blocker_dict["subtask_count"] == 0
    assert blocker_dict["assignee_name"] is None
    assert blocker_dict["decider_name"] is None


async def test_list_tasks_without_assignee_or_decider(
    client: AsyncClient, admin_headers, project_for_list: Project
):
    """Tasks with no assignee/decider should round-trip with null names."""
    pid = str(project_for_list.id)
    plain = Task(
        project_id=pid,
        title="Plain",
        priority=TaskPriority.medium,
        created_by="seed",
    )
    await plain.insert()

    r = await client.get(f"/api/v1/projects/{pid}/tasks", headers=admin_headers)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["assignee_name"] is None
    assert item["decider_name"] is None
    assert item["subtask_count"] == 0
    assert item["blocked_by_count"] == 0


async def test_list_tasks_handles_invalid_user_id(
    client: AsyncClient, admin_headers, project_for_list: Project
):
    """An assignee_id that doesn't resolve to a User must not crash."""
    pid = str(project_for_list.id)
    t = Task(
        project_id=pid,
        title="Phantom assignee",
        assignee_id="000000000000000000000099",  # valid ObjectId, no user
        created_by="seed",
    )
    await t.insert()

    r = await client.get(f"/api/v1/projects/{pid}/tasks", headers=admin_headers)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["assignee_id"] == "000000000000000000000099"
    assert item["assignee_name"] is None


async def test_get_single_task_exposes_blocked_by_count(
    client: AsyncClient, admin_headers, project_for_list: Project
):
    """``GET /tasks/{id}`` (single) must surface blocked_by_count too,
    so detail views match list cards."""
    pid = str(project_for_list.id)
    t = Task(
        project_id=pid,
        title="Single",
        blocked_by=["a", "b", "c"],
        created_by="seed",
    )
    await t.insert()

    r = await client.get(f"/api/v1/projects/{pid}/tasks/{t.id}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["blocked_by_count"] == 3
    # Single-task endpoint doesn't run batch enrichment, so these are
    # ``None`` — frontend can fetch detail views separately if needed.
    assert body["subtask_count"] is None
    assert body["assignee_name"] is None
    assert body["decider_name"] is None


async def test_list_tasks_batch_count_does_not_blow_up_with_50(
    client: AsyncClient, admin_headers, project_for_list: Project
):
    """50 tasks should still resolve names + subtask counts in one round trip
    (smoke test for the batch enrichment path)."""
    pid = str(project_for_list.id)
    parent = Task(project_id=pid, title="P0", created_by="seed")
    await parent.insert()

    for i in range(50):
        await Task(
            project_id=pid,
            title=f"T{i}",
            parent_task_id=str(parent.id),
            created_by="seed",
        ).insert()

    r = await client.get(
        f"/api/v1/projects/{pid}/tasks?limit=60", headers=admin_headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    parent_dict = next(it for it in items if it["title"] == "P0")
    assert parent_dict["subtask_count"] == 50
