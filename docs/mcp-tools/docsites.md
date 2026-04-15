# ドックサイト管理ツール仕様書

`backend/app/mcp/tools/docsites.py` の外部ドキュメント管理ツール（全9関数）を記載します。

## 概要

Pydantic、Django 等の外部プロジェクトのドキュメンテーションを「ドックサイト」として登録・検索できます。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `list_docsites` | 登録済みドックサイト一覧 |
| `get_docsite` | ドックサイト詳細 |
| `search_docpages` | ページ全文検索 |
| `get_docpage` | ドキュメントページ取得 |
| `update_docpage` | ページメタデータ編集 |
| `create_docpage` | ページ新規作成 |
| `delete_docpage` | ページ削除 |
| `upload_docsite_asset` | 静的アセット（画像等）アップロード |

**合計: 9 ツール関数**

---

## ドックサイト管理

### list_docsites

**概要**: 登録済みドックサイト一覧

**戻り値** (list[dict]):
```json
[
  {
    "id": "...",
    "name": "Pydantic v2 Documentation",
    "source_url": "https://docs.pydantic.dev",
    "description": "Pydantic validation library documentation",
    "created_at": "...",
    "page_count": 156
  }
]
```

---

### get_docsite

**概要**: ドックサイト詳細

**戻り値** (dict): list_docsites と同じ + sections（ページ階層）

---

## ページ検索・取得

### search_docpages

**概要**: ドックサイト内ページ全文検索

**シグネチャ**:
```python
async def search_docpages(
    docsite_id: str,
    query: str,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**検索対象**: ページ title、content

**戻り値** (dict):
```json
{
  "items": [
    {
      "id": "...",
      "title": "...",
      "content_preview": "...",
      "url": "..."
    }
  ],
  "total": 5,
  "limit": 20,
  "skip": 0
}
```

---

### get_docpage

**概要**: ドキュメントページ取得（full content）

**シグネチャ**:
```python
async def get_docpage(
    docsite_id: str,
    page_path: str,
) -> dict
```

**パラメータ**:
- `docsite_id`: ドックサイト ID
- `page_path`: ページパス（例: `"api/main"`, `"tutorial/quickstart"`）

**戻り値** (dict):
```json
{
  "id": "...",
  "title": "...",
  "content": "...",
  "url": "...",
  "docsite_id": "...",
  "created_at": "...",
  "updated_at": "..."
}
```

---

## ページ編集・作成

### update_docpage

**概要**: ページメタデータ編集

**シグネチャ**:
```python
async def update_docpage(
    docsite_id: str,
    page_path: str,
    title: str | None = None,
    content: str | None = None,
) -> dict
```

---

### create_docpage

**概要**: 新規ページ作成

**シグネチャ**:
```python
async def create_docpage(
    docsite_id: str,
    page_path: str,
    title: str,
    content: str = "",
) -> dict
```

---

### delete_docpage

**概要**: ページ削除

---

## アセット管理

### upload_docsite_asset

**概要**: 静的アセット（画像等）アップロード

**シグネチャ**:
```python
async def upload_docsite_asset(
    docsite_id: str,
    file_path: str,
    asset_path: str,
) -> dict
```

**用途**:
- ドックサイト内で参照する画像、スクリーンショット等

---

## 使用パターン

### ドキュメント検索→確認フロー

```
1. search_docpages(docsite_id, query="Pydantic validation")
2. ヒット → get_docpage(docsite_id, page_path) で full content
3. 実装に参考
```

---

**ツール総数**: 9 / 9

**最終更新**: 2025-04-15
