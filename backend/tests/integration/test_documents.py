"""ドキュメントエンドポイントの統合テスト"""

import pytest
import pytest_asyncio

from app.models import Project, ProjectDocument, User
from app.models.document import DocumentCategory, DocumentVersion
from app.models.project import MemberRole, ProjectMember
from app.models.user import AuthType
from app.core.security import create_access_token, hash_password


@pytest_asyncio.fixture
async def owner_user():
    user = User(
        email="owner@test.com",
        name="Owner",
        auth_type=AuthType.admin,
        password_hash=hash_password("ownerpass"),
        is_admin=False,
        is_active=True,
    )
    await user.insert()
    return user


@pytest.fixture
def owner_headers(owner_user):
    return {"Authorization": f"Bearer {create_access_token(str(owner_user.id))}"}


@pytest_asyncio.fixture
async def doc_project(owner_user, regular_user):
    project = Project(
        name="Doc Project",
        created_by=owner_user,
        members=[
            ProjectMember(user_id=str(owner_user.id), role=MemberRole.owner),
            ProjectMember(user_id=str(regular_user.id), role=MemberRole.member),
        ],
    )
    await project.insert()
    return project


@pytest_asyncio.fixture
async def sample_doc(doc_project, owner_user):
    doc = ProjectDocument(
        project_id=str(doc_project.id),
        title="テストドキュメント",
        content="# Hello\n\nテスト内容",
        tags=["test"],
        category=DocumentCategory.spec,
        created_by=str(owner_user.id),
    )
    await doc.insert()
    return doc


# ── Access Control ──────────────────────────────────────────


class TestDocumentAccessControl:
    async def test_non_member_cannot_list_documents(self, client, doc_project, admin_user):
        """Non-member, non-admin user gets 403"""
        outsider = User(
            email="outsider@test.com",
            name="Outsider",
            auth_type=AuthType.google,
            is_admin=False,
            is_active=True,
        )
        await outsider.insert()
        headers = {"Authorization": f"Bearer {create_access_token(str(outsider.id))}"}

        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/",
            headers=headers,
        )
        assert resp.status_code == 403

    async def test_non_member_cannot_create_document(self, client, doc_project):
        outsider = User(
            email="outsider2@test.com",
            name="Outsider2",
            auth_type=AuthType.google,
            is_admin=False,
            is_active=True,
        )
        await outsider.insert()
        headers = {"Authorization": f"Bearer {create_access_token(str(outsider.id))}"}

        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/",
            json={"title": "Forbidden", "content": "x"},
            headers=headers,
        )
        assert resp.status_code == 403

    async def test_admin_can_access_any_project_documents(
        self, client, doc_project, sample_doc, admin_user, admin_headers
    ):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_member_can_list_documents(
        self, client, doc_project, sample_doc, regular_user, user_headers
    ):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ── CRUD ────────────────────────────────────────────────────


class TestDocumentCRUD:
    async def test_create_document(self, client, doc_project, owner_headers):
        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/",
            json={"title": "新規ドキュメント", "content": "内容", "tags": ["api"], "category": "api"},
            headers=owner_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "新規ドキュメント"
        assert data["category"] == "api"
        assert "api" in data["tags"]

    async def test_create_document_invalid_category(self, client, doc_project, owner_headers):
        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/",
            json={"title": "Bad", "category": "invalid"},
            headers=owner_headers,
        )
        assert resp.status_code == 400

    async def test_get_document(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "テストドキュメント"

    async def test_get_document_not_found(self, client, doc_project, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/000000000000000000000000",
            headers=owner_headers,
        )
        assert resp.status_code == 404

    async def test_update_document(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.patch(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            json={"title": "更新タイトル", "change_summary": "タイトル変更"},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "更新タイトル"
        assert data["version"] == 2

    async def test_update_creates_version_snapshot(self, client, doc_project, sample_doc, owner_headers):
        await client.patch(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            json={"content": "新しい内容"},
            headers=owner_headers,
        )
        versions = await DocumentVersion.find(
            DocumentVersion.document_id == str(sample_doc.id)
        ).to_list()
        assert len(versions) == 1
        assert versions[0].version == 1  # snapshot of original version

    async def test_update_invalid_category(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.patch(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            json={"category": "nonexistent"},
            headers=owner_headers,
        )
        assert resp.status_code == 400

    async def test_delete_document(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.delete(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            headers=owner_headers,
        )
        assert resp.status_code == 204

        # Should no longer appear in list
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/",
            headers=owner_headers,
        )
        assert resp.json()["total"] == 0


# ── List with filters ───────────────────────────────────────


class TestDocumentList:
    async def test_list_with_category_filter(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/?category=spec",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/?category=api",
            headers=owner_headers,
        )
        assert resp.json()["total"] == 0

    async def test_list_with_invalid_category(self, client, doc_project, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/?category=invalid",
            headers=owner_headers,
        )
        assert resp.status_code == 400

    async def test_list_with_search(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/?search=Hello",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_list_with_tag_filter(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/?tag=test",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ── Versions ────────────────────────────────────────────────


class TestDocumentVersions:
    async def test_list_versions(self, client, doc_project, sample_doc, owner_headers):
        # Create a version by updating
        await client.patch(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            json={"title": "v2"},
            headers=owner_headers,
        )
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}/versions",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_version"] == 2
        assert len(data["items"]) == 1

    async def test_get_specific_version(self, client, doc_project, sample_doc, owner_headers):
        await client.patch(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}",
            json={"title": "v2"},
            headers=owner_headers,
        )
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}/versions/1",
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "テストドキュメント"

    async def test_get_nonexistent_version(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.get(
            f"/api/v1/projects/{doc_project.id}/documents/{sample_doc.id}/versions/999",
            headers=owner_headers,
        )
        assert resp.status_code == 404


# ── Locked Project ──────────────────────────────────────────


class TestDocumentLockedProject:
    @pytest_asyncio.fixture
    async def locked_project(self, owner_user, regular_user):
        project = Project(
            name="Locked Project",
            is_locked=True,
            created_by=owner_user,
            members=[
                ProjectMember(user_id=str(owner_user.id), role=MemberRole.owner),
                ProjectMember(user_id=str(regular_user.id)),
            ],
        )
        await project.insert()
        return project

    async def test_cannot_create_in_locked_project(self, client, locked_project, owner_headers):
        resp = await client.post(
            f"/api/v1/projects/{locked_project.id}/documents/",
            json={"title": "Locked", "content": "x"},
            headers=owner_headers,
        )
        assert resp.status_code == 423

    async def test_cannot_delete_in_locked_project(self, client, locked_project, owner_user, owner_headers):
        doc = ProjectDocument(
            project_id=str(locked_project.id),
            title="Existing",
            content="x",
            category=DocumentCategory.spec,
            created_by=str(owner_user.id),
        )
        await doc.insert()

        resp = await client.delete(
            f"/api/v1/projects/{locked_project.id}/documents/{doc.id}",
            headers=owner_headers,
        )
        assert resp.status_code == 423

    async def test_can_read_in_locked_project(self, client, locked_project, owner_user, owner_headers):
        doc = ProjectDocument(
            project_id=str(locked_project.id),
            title="Readable",
            content="x",
            category=DocumentCategory.spec,
            created_by=str(owner_user.id),
        )
        await doc.insert()

        resp = await client.get(
            f"/api/v1/projects/{locked_project.id}/documents/{doc.id}",
            headers=owner_headers,
        )
        assert resp.status_code == 200


# ── Export ──────────────────────────────────────────────────


class TestDocumentExport:
    async def test_export_markdown(self, client, doc_project, sample_doc, owner_headers):
        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/export",
            json={"document_ids": [str(sample_doc.id)], "format": "markdown"},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "テストドキュメント" in resp.text

    async def test_export_no_docs_returns_404(self, client, doc_project, owner_headers):
        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/export",
            json={"document_ids": ["000000000000000000000000"], "format": "markdown"},
            headers=owner_headers,
        )
        assert resp.status_code == 404

    async def test_export_invalid_id(self, client, doc_project, owner_headers):
        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/export",
            json={"document_ids": ["not-a-valid-id"], "format": "markdown"},
            headers=owner_headers,
        )
        assert resp.status_code == 400


# ── Reorder ─────────────────────────────────────────────────


class TestDocumentReorder:
    async def test_reorder_documents(self, client, doc_project, owner_user, owner_headers):
        docs = []
        for i in range(3):
            d = ProjectDocument(
                project_id=str(doc_project.id),
                title=f"Doc {i}",
                content="",
                category=DocumentCategory.spec,
                created_by=str(owner_user.id),
            )
            await d.insert()
            docs.append(d)

        # Reverse order
        reversed_ids = [str(d.id) for d in reversed(docs)]
        resp = await client.post(
            f"/api/v1/projects/{doc_project.id}/documents/reorder",
            json={"document_ids": reversed_ids},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["reordered"] >= 2
