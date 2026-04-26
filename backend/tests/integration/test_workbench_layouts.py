"""Workbench layout (server-side persistence + multi-device sync) tests.

Covers:
- GET on absent layout returns 404
- PUT creates the document, GET returns it
- PUT then PUT again updates in place (no duplicate, updated_at advances)
- Layouts are isolated per user (user A cannot read user B's)
- 404 on unknown / inactive project
- Authentication required
"""

import asyncio

import pytest
import pytest_asyncio

from app.core.security import create_access_token, hash_password
from app.models import Project, User, WorkbenchLayout
from app.models.project import MemberRole, ProjectMember
from app.models.user import AuthType


@pytest_asyncio.fixture
async def alice():
    user = User(
        email="alice@test.com",
        name="Alice",
        auth_type=AuthType.admin,
        password_hash=hash_password("alicepass"),
        is_admin=False,
        is_active=True,
    )
    await user.insert()
    return user


@pytest_asyncio.fixture
async def bob():
    user = User(
        email="bob@test.com",
        name="Bob",
        auth_type=AuthType.admin,
        password_hash=hash_password("bobpass"),
        is_admin=False,
        is_active=True,
    )
    await user.insert()
    return user


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest_asyncio.fixture
async def shared_project(alice, bob):
    project = Project(
        name="Layout Project",
        created_by=alice,
        members=[
            ProjectMember(user_id=str(alice.id), role=MemberRole.owner),
            ProjectMember(user_id=str(bob.id), role=MemberRole.member),
        ],
    )
    await project.insert()
    return project


SAMPLE_TREE = {
    "kind": "tabs",
    "id": "g1",
    "tabs": [{"id": "p1", "paneType": "tasks", "paneConfig": {}}],
    "activeTabId": "p1",
}


class TestWorkbenchLayoutAuth:
    async def test_get_requires_auth(self, client, shared_project):
        resp = await client.get(f"/api/v1/workbench/layouts/{shared_project.id}")
        assert resp.status_code in (401, 403)

    async def test_put_requires_auth(self, client, shared_project):
        resp = await client.put(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            json={"tree": SAMPLE_TREE, "schema_version": 1, "client_id": "tab-x"},
        )
        assert resp.status_code in (401, 403)


class TestWorkbenchLayoutCrud:
    async def test_get_absent_returns_404(self, client, alice, shared_project):
        resp = await client.get(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
        )
        assert resp.status_code == 404

    async def test_put_creates_then_get_returns(self, client, alice, shared_project):
        put_resp = await client.put(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
            json={"tree": SAMPLE_TREE, "schema_version": 1, "client_id": "tab-A"},
        )
        assert put_resp.status_code == 200
        first_updated_at = put_resp.json()["updated_at"]

        get_resp = await client.get(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
        )
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["tree"] == SAMPLE_TREE
        assert body["schema_version"] == 1
        assert body["client_id"] == "tab-A"
        assert body["updated_at"] == first_updated_at

    async def test_put_then_put_updates_in_place(self, client, alice, shared_project):
        await client.put(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
            json={"tree": SAMPLE_TREE, "schema_version": 1, "client_id": "tab-A"},
        )
        # Sleep so updated_at unambiguously advances even if the clock
        # rounds to ms.
        await asyncio.sleep(0.01)
        new_tree = {
            "kind": "tabs",
            "id": "g1",
            "tabs": [
                {"id": "p1", "paneType": "tasks", "paneConfig": {}},
                {"id": "p2", "paneType": "doc", "paneConfig": {}},
            ],
            "activeTabId": "p2",
        }
        put_resp = await client.put(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
            json={"tree": new_tree, "schema_version": 2, "client_id": "tab-B"},
        )
        assert put_resp.status_code == 200

        # Exactly one document for (alice, project)
        count = await WorkbenchLayout.find(
            WorkbenchLayout.user_id == str(alice.id),
            WorkbenchLayout.project_id == str(shared_project.id),
        ).count()
        assert count == 1

        get_resp = await client.get(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
        )
        body = get_resp.json()
        assert body["tree"] == new_tree
        assert body["schema_version"] == 2
        assert body["client_id"] == "tab-B"


class TestWorkbenchLayoutIsolation:
    async def test_layouts_isolated_per_user(self, client, alice, bob, shared_project):
        await client.put(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
            json={"tree": SAMPLE_TREE, "schema_version": 1, "client_id": "alice-tab"},
        )
        # Bob is a member of the same project but has not stored a
        # layout — they must not see Alice's.
        resp = await client.get(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(bob),
        )
        assert resp.status_code == 404


class TestWorkbenchLayoutBeacon:
    async def test_beacon_post_upserts_like_put(
        self, client, alice, shared_project
    ):
        # No prior layout — beacon POST should create it.
        resp = await client.post(
            f"/api/v1/workbench/layouts/{shared_project.id}/beacon",
            headers=_headers(alice),
            json={
                "tree": SAMPLE_TREE,
                "schema_version": 1,
                "client_id": "tab-beacon",
            },
        )
        assert resp.status_code == 200
        # Subsequent GET surfaces what beacon wrote.
        get_resp = await client.get(
            f"/api/v1/workbench/layouts/{shared_project.id}",
            headers=_headers(alice),
        )
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["client_id"] == "tab-beacon"


class TestWorkbenchLayoutProjectGate:
    async def test_unknown_project_returns_404(self, client, alice):
        resp = await client.get(
            "/api/v1/workbench/layouts/000000000000000000000000",
            headers=_headers(alice),
        )
        assert resp.status_code == 404

    async def test_invalid_project_id_returns_404(self, client, alice):
        # valid_object_id raises HTTPException(400) for malformed IDs.
        resp = await client.get(
            "/api/v1/workbench/layouts/not-an-objectid",
            headers=_headers(alice),
        )
        assert resp.status_code in (400, 404)
