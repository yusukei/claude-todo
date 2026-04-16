"""Tests for the /projects/{pid}/secrets REST API endpoints."""

import pytest
import pytest_asyncio

from app.models import Project, User
from app.models.project import MemberRole, ProjectMember
from app.models.secret import ProjectSecret, SecretAccessLog
from app.core.security import create_access_token, hash_password
from app.models.user import AuthType


@pytest_asyncio.fixture
async def owner_user():
    user = User(
        email="owner@test.com",
        name="Owner",
        auth_type=AuthType.admin,
        password_hash=hash_password("pass"),
        is_admin=False,
        is_active=True,
    )
    await user.insert()
    return user


@pytest_asyncio.fixture
async def member_user():
    user = User(
        email="member@test.com",
        name="Member",
        auth_type=AuthType.google,
        is_admin=False,
        is_active=True,
    )
    await user.insert()
    return user


@pytest_asyncio.fixture
async def secret_project(owner_user, member_user):
    project = Project(
        name="Secret Test Project",
        created_by=owner_user,
        members=[
            ProjectMember(user_id=str(owner_user.id), role=MemberRole.owner),
            ProjectMember(user_id=str(member_user.id), role=MemberRole.member),
        ],
    )
    await project.insert()
    return project


@pytest.fixture
def owner_headers(owner_user):
    return {"Authorization": f"Bearer {create_access_token(str(owner_user.id))}"}


@pytest.fixture
def member_headers(member_user):
    return {"Authorization": f"Bearer {create_access_token(str(member_user.id))}"}


class TestListSecrets:
    async def test_empty_list(self, client, secret_project, owner_headers):
        r = await client.get(f"/api/v1/projects/{secret_project.id}/secrets/", headers=owner_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_after_create(self, client, secret_project, owner_headers):
        # Create a secret directly
        s = ProjectSecret(
            project_id=str(secret_project.id),
            key="MY_KEY",
            value="val",
            description="test",
            created_by="test",
            updated_by="test",
        )
        await s.insert()

        r = await client.get(f"/api/v1/projects/{secret_project.id}/secrets/", headers=owner_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["key"] == "MY_KEY"
        assert "value" not in data["items"][0]  # value never in list

    async def test_member_can_list(self, client, secret_project, member_headers):
        r = await client.get(f"/api/v1/projects/{secret_project.id}/secrets/", headers=member_headers)
        assert r.status_code == 200


class TestCreateSecret:
    async def test_create_success(self, client, secret_project, owner_headers):
        r = await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "API_KEY", "value": "secret123", "description": "test key"},
            headers=owner_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["key"] == "API_KEY"
        assert data["description"] == "test key"
        assert "value" not in data

    async def test_duplicate_key_409(self, client, secret_project, owner_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "DUP_KEY", "value": "v1"},
            headers=owner_headers,
        )
        r = await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "DUP_KEY", "value": "v2"},
            headers=owner_headers,
        )
        assert r.status_code == 409

    async def test_member_cannot_create(self, client, secret_project, member_headers):
        r = await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "BLOCKED", "value": "val"},
            headers=member_headers,
        )
        assert r.status_code == 403

    async def test_invalid_key_rejected(self, client, secret_project, owner_headers):
        r = await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "invalid-key!", "value": "val"},
            headers=owner_headers,
        )
        assert r.status_code == 400


class TestUpdateSecret:
    async def test_update_value(self, client, secret_project, owner_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "UPD_KEY", "value": "old"},
            headers=owner_headers,
        )
        r = await client.put(
            f"/api/v1/projects/{secret_project.id}/secrets/UPD_KEY",
            json={"value": "new"},
            headers=owner_headers,
        )
        assert r.status_code == 200

        # Verify the value changed
        r2 = await client.get(
            f"/api/v1/projects/{secret_project.id}/secrets/UPD_KEY/value",
            headers=owner_headers,
        )
        assert r2.json()["value"] == "new"

    async def test_update_description_only(self, client, secret_project, owner_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "DESC_KEY", "value": "keep"},
            headers=owner_headers,
        )
        r = await client.put(
            f"/api/v1/projects/{secret_project.id}/secrets/DESC_KEY",
            json={"description": "updated desc"},
            headers=owner_headers,
        )
        assert r.status_code == 200
        assert r.json()["description"] == "updated desc"

    async def test_update_not_found(self, client, secret_project, owner_headers):
        r = await client.put(
            f"/api/v1/projects/{secret_project.id}/secrets/NOPE",
            json={"value": "x"},
            headers=owner_headers,
        )
        assert r.status_code == 404

    async def test_member_cannot_update(self, client, secret_project, owner_headers, member_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "LOCKED", "value": "v"},
            headers=owner_headers,
        )
        r = await client.put(
            f"/api/v1/projects/{secret_project.id}/secrets/LOCKED",
            json={"value": "hacked"},
            headers=member_headers,
        )
        assert r.status_code == 403


class TestDeleteSecret:
    async def test_delete_success(self, client, secret_project, owner_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "DEL_KEY", "value": "v"},
            headers=owner_headers,
        )
        r = await client.delete(
            f"/api/v1/projects/{secret_project.id}/secrets/DEL_KEY",
            headers=owner_headers,
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

        # Verify gone
        r2 = await client.get(
            f"/api/v1/projects/{secret_project.id}/secrets/DEL_KEY/value",
            headers=owner_headers,
        )
        assert r2.status_code == 404

    async def test_member_cannot_delete(self, client, secret_project, owner_headers, member_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "NODELETE", "value": "v"},
            headers=owner_headers,
        )
        r = await client.delete(
            f"/api/v1/projects/{secret_project.id}/secrets/NODELETE",
            headers=member_headers,
        )
        assert r.status_code == 403


class TestGetSecretValue:
    async def test_get_value(self, client, secret_project, owner_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "READ_KEY", "value": "my-secret-value"},
            headers=owner_headers,
        )
        r = await client.get(
            f"/api/v1/projects/{secret_project.id}/secrets/READ_KEY/value",
            headers=owner_headers,
        )
        assert r.status_code == 200
        assert r.json()["value"] == "my-secret-value"

    async def test_member_can_read_value(self, client, secret_project, owner_headers, member_headers):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "MEMBER_READ", "value": "visible"},
            headers=owner_headers,
        )
        r = await client.get(
            f"/api/v1/projects/{secret_project.id}/secrets/MEMBER_READ/value",
            headers=member_headers,
        )
        assert r.status_code == 200
        assert r.json()["value"] == "visible"

    async def test_get_value_creates_audit_log(self, client, secret_project, owner_headers, owner_user):
        await client.post(
            f"/api/v1/projects/{secret_project.id}/secrets/",
            json={"key": "AUDIT_KEY", "value": "v"},
            headers=owner_headers,
        )
        await client.get(
            f"/api/v1/projects/{secret_project.id}/secrets/AUDIT_KEY/value",
            headers=owner_headers,
        )
        logs = await SecretAccessLog.find(
            SecretAccessLog.project_id == str(secret_project.id),
            SecretAccessLog.secret_key == "AUDIT_KEY",
            SecretAccessLog.operation == "get",
        ).to_list()
        assert len(logs) >= 1

    async def test_not_found(self, client, secret_project, owner_headers):
        r = await client.get(
            f"/api/v1/projects/{secret_project.id}/secrets/MISSING/value",
            headers=owner_headers,
        )
        assert r.status_code == 404
