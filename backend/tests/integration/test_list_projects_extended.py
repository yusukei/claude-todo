"""Phase 0.5 / API-3 — GET /projects response extension tests.

Verifies the new ``task_count`` field — the unfinished-task counter
that drives the sidebar project rows.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import Project, Task, User
from app.models.project import ProjectMember
from app.models.task import TaskPriority, TaskStatus
from app.models.user import AuthType
from app.core.security import create_access_token


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def two_projects(admin_user, regular_user) -> tuple[Project, Project]:
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
        created_by=str(admin_user.id),
        members=[ProjectMember(user_id=str(admin_user.id))],
    )
    await p1.insert()
    await p2.insert()
    return p1, p2


async def _seed(project_id: str, status: TaskStatus = TaskStatus.todo, **kw):
    t = Task(
        project_id=project_id,
        title=kw.pop("title", "t"),
        priority=TaskPriority.medium,
        status=status,
        created_by="seed",
        **kw,
    )
    await t.insert()
    return t


async def test_list_projects_includes_task_count(
    client: AsyncClient, admin_headers, two_projects: tuple[Project, Project]
):
    p1, p2 = two_projects
    pid1, pid2 = str(p1.id), str(p2.id)

    # 3 open tasks in P1, 1 done (must be excluded)
    await _seed(pid1, status=TaskStatus.todo)
    await _seed(pid1, status=TaskStatus.in_progress)
    await _seed(pid1, status=TaskStatus.on_hold)
    await _seed(pid1, status=TaskStatus.done)
    # 1 open + 1 cancelled in P2 (cancelled stays counted as open per spec)
    await _seed(pid2, status=TaskStatus.todo)
    await _seed(pid2, status=TaskStatus.cancelled)

    r = await client.get("/api/v1/projects", headers=admin_headers)
    assert r.status_code == 200
    items = {item["name"]: item for item in r.json()}
    assert items["P1"]["task_count"] == 3
    assert items["P2"]["task_count"] == 2


async def test_list_projects_excludes_deleted_tasks(
    client: AsyncClient, admin_headers, two_projects: tuple[Project, Project]
):
    p1, _ = two_projects
    pid = str(p1.id)
    await _seed(pid, status=TaskStatus.todo)
    await _seed(pid, status=TaskStatus.todo, is_deleted=True)

    r = await client.get("/api/v1/projects", headers=admin_headers)
    assert r.status_code == 200
    items = {item["name"]: item for item in r.json()}
    assert items["P1"]["task_count"] == 1


async def test_list_projects_zero_for_empty_project(
    client: AsyncClient, admin_headers, two_projects: tuple[Project, Project]
):
    r = await client.get("/api/v1/projects", headers=admin_headers)
    assert r.status_code == 200
    items = {item["name"]: item for item in r.json()}
    # Both fixtures have no tasks
    assert items["P1"]["task_count"] == 0
    assert items["P2"]["task_count"] == 0


async def test_list_projects_non_member_excluded(
    client: AsyncClient,
    user_headers,
    two_projects: tuple[Project, Project],
):
    """Non-member regular_user only sees P1 (where they're a member).

    ``user_headers`` is a session fixture for ``regular_user``, who is a
    member of P1 only (per the ``two_projects`` fixture above).
    """
    _, p2 = two_projects
    await _seed(str(p2.id), status=TaskStatus.todo)

    r = await client.get("/api/v1/projects", headers=user_headers)
    assert r.status_code == 200
    names = {item["name"] for item in r.json()}
    assert "P1" in names
    assert "P2" not in names
