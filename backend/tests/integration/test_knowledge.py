"""ナレッジエンドポイントの統合テスト"""

from app.models.knowledge import Knowledge, KnowledgeCategory


class TestKnowledgeCRUD:
    async def test_create_knowledge(self, client, admin_headers):
        resp = await client.post(
            "/api/v1/knowledge/",
            json={
                "title": "Docker Tips",
                "content": "Use multi-stage builds",
                "tags": ["docker", "tips"],
                "category": "tip",
                "source": "experience",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Docker Tips"
        assert data["category"] == "tip"
        assert "docker" in data["tags"]
        assert data["source"] == "experience"

    async def test_create_invalid_category(self, client, admin_headers):
        resp = await client.post(
            "/api/v1/knowledge/",
            json={"title": "Bad", "category": "nonexistent"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_get_knowledge(self, client, admin_user, admin_headers):
        k = Knowledge(
            title="Existing",
            content="content",
            category=KnowledgeCategory.reference,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.get(f"/api/v1/knowledge/{k.id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Existing"

    async def test_get_not_found(self, client, admin_headers):
        resp = await client.get(
            "/api/v1/knowledge/000000000000000000000000", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_update_knowledge(self, client, admin_user, admin_headers):
        k = Knowledge(
            title="Original",
            content="old",
            category=KnowledgeCategory.recipe,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.patch(
            f"/api/v1/knowledge/{k.id}",
            json={"title": "Updated", "content": "new", "tags": ["updated"], "source": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated"
        assert data["content"] == "new"
        assert data["source"] is None  # empty string → None

    async def test_update_invalid_category(self, client, admin_user, admin_headers):
        k = Knowledge(
            title="X",
            content="x",
            category=KnowledgeCategory.tip,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.patch(
            f"/api/v1/knowledge/{k.id}",
            json={"category": "invalid"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_delete_knowledge(self, client, admin_user, admin_headers):
        k = Knowledge(
            title="ToDelete",
            content="x",
            category=KnowledgeCategory.troubleshooting,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.delete(f"/api/v1/knowledge/{k.id}", headers=admin_headers)
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/knowledge/{k.id}", headers=admin_headers)
        assert resp.status_code == 404


class TestKnowledgeList:
    async def test_list_empty(self, client, admin_headers):
        resp = await client.get("/api/v1/knowledge/", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_list_with_category(self, client, admin_user, admin_headers):
        for cat in ["tip", "recipe"]:
            k = Knowledge(
                title=f"{cat} entry",
                content="x",
                category=KnowledgeCategory(cat),
                created_by=str(admin_user.id),
            )
            await k.insert()

        resp = await client.get("/api/v1/knowledge/?category=tip", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_list_invalid_category(self, client, admin_headers):
        resp = await client.get("/api/v1/knowledge/?category=bad", headers=admin_headers)
        assert resp.status_code == 400

    async def test_list_with_tag(self, client, admin_user, admin_headers):
        k = Knowledge(
            title="Tagged",
            content="x",
            tags=["python"],
            category=KnowledgeCategory.reference,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.get("/api/v1/knowledge/?tag=python", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_list_with_search(self, client, admin_user, admin_headers):
        k = Knowledge(
            title="Unique Keyword",
            content="x",
            category=KnowledgeCategory.reference,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.get("/api/v1/knowledge/?search=Unique", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_regular_user_can_access(self, client, regular_user, user_headers, admin_user):
        k = Knowledge(
            title="Public",
            content="x",
            category=KnowledgeCategory.tip,
            created_by=str(admin_user.id),
        )
        await k.insert()

        resp = await client.get("/api/v1/knowledge/", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
