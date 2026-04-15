# ブックマーク管理ツール仕様書

`backend/app/mcp/tools/bookmarks.py` のブックマーク関連ツール（全10関数）を記載します。

## 概要

Web ページをブックマーク・クリップしクロスプロジェクトで管理します。Playwright による自動 Web クリップで記事内容を Markdown として保存。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `create_bookmark_collection` | ブックマークコレクション（フォルダ）作成 |
| `list_bookmark_collections` | コレクション一覧 |
| `update_bookmark_collection` | コレクション編集 |
| `delete_bookmark_collection` | コレクション削除 |
| `create_bookmark` | ブックマーク作成（自動 Web クリップ開始） |
| `get_bookmark` | ブックマーク詳細取得 |
| `update_bookmark` | ブックマーク編集 |
| `delete_bookmark` | ブックマーク削除 |
| `batch_bookmark_action` | バッチ操作（複数ブックマーク） |
| `list_bookmarks` | ブックマーク一覧 |
| `search_bookmarks` | ブックマーク全文検索 |
| `clip_bookmark` | Web クリップ再試行 |

**合計: 12 関数（収集関数を含む）**

---

## コレクション CRUD

### create_bookmark_collection

**概要**: ブックマークフォルダ作成

**シグネチャ**:
```python
async def create_bookmark_collection(
    name: str,
    description: str = "",
    icon: str = "folder",
    color: str = "#6366f1",
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `name` | str | ○ | — | コレクション名（最大 255 文字） |
| `description` | str | — | `""` | 説明 |
| `icon` | str | — | `"folder"` | Lucide アイコン名 |
| `color` | str | — | `"#6366f1"` | 16進数カラーコード |

**戻り値** (dict): 作成されたコレクション dict

**WHEN TO USE**:
- `"Design References"`, `"API Documentation"` など、テーマごとにブックマーク整理

---

### list_bookmark_collections

**概要**: コレクション一覧

**戻り値** (dict):
```json
{
  "items": [{ collection... }],
  "total": 5
}
```

---

### update_bookmark_collection / delete_bookmark_collection

**概要**: コレクション編集・削除

コレクション削除時、所属ブックマークは uncategorized に自動移動。

---

## ブックマーク CRUD

### create_bookmark

**概要**: ブックマーク作成（自動 Web クリップ開始）

**シグネチャ**:
```python
async def create_bookmark(
    url: str,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    collection_id: str | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `url` | str | ○ | — | URL（最大 2,048 文字） |
| `title` | str | — | `""` | ブックマークタイトル（空なら自動取得） |
| `description` | str | — | `""` | 説明 |
| `tags` | list[str] | — | None | タグ（自動小文字化） |
| `collection_id` | str | — | None | 所属コレクション ID |

**Web クリップ**:
- create_bookmark 直後、`clip_status = pending` で挙列
- バックグラウンドで Playwright が実行、`clip_status` → `success` or `failed`
- 成功時、clipped_content（Markdown）+ thumbnail（PNG） を保存
- clipped_content は get_bookmark で取得可能

**戻り値** (dict):
```json
{
  "id": "...",
  "url": "...",
  "title": "...",
  "description": "...",
  "tags": [...],
  "collection_id": "...",
  "clip_status": "pending",
  "clipped_content": null,
  "is_starred": false,
  "created_by": "mcp:my-key",
  "created_at": "...",
  "updated_at": "..."
}
```

**WHEN TO USE**:
- 参考記事を保存
- API ドキュメントをクリップ

---

### get_bookmark

**概要**: ブックマーク詳細取得

**戻り値**: clipped_content（Markdown）を含む

```json
{
  "id": "...",
  "url": "...",
  "title": "...",
  "clip_status": "success",
  "clipped_content": "# Title\n\nContent...",
  ...
}
```

---

### update_bookmark

**概要**: ブックマーク編集

**パラメータ**:
- title, description, tags, collection_id（`""` で None に設定）, is_starred

---

### delete_bookmark

**概要**: ブックマーク削除（soft delete）

**副作用**:
- is_deleted → true
- thumbnail・clipped_content を削除

---

## バッチ操作

### batch_bookmark_action

**概要**: 複数ブックマーク一括操作

**シグネチャ**:
```python
async def batch_bookmark_action(
    bookmark_ids: list[str],
    action: str,
    collection_id: str | None = None,
    tags: list[str] | None = None,
) -> dict
```

**action の値**:
- `delete` — 削除
- `star` / `unstar` — スター
- `set_collection` — コレクション設定（collection_id 必須）
- `add_tags` / `remove_tags` — タグ追加/削除（tags 必須）

**制限**: 最大 200 個のブックマーク

---

## リスト・検索

### list_bookmarks

**概要**: ブックマーク一覧（フィルタ対応）

**シグネチャ**:
```python
async def list_bookmarks(
    collection_id: str | None = None,
    tag: str | None = None,
    is_starred: bool | None = None,
    clip_status: str | None = None,
    limit: int = 50,
    skip: int = 0,
) -> dict
```

**clip_status の値**: `pending`, `success`, `failed`

---

### search_bookmarks

**概要**: ブックマーク全文検索

**検索対象**: title, description, tags, clipped_content（クリップ済みのみ）

**戻り値**: タスク検索と同じ形式（_meta に search_engine 含む）

---

## Web クリップ再試行

### clip_bookmark

**概要**: Web クリップ再試行（失敗時のリトライ）

**シグネチャ**:
```python
async def clip_bookmark(bookmark_id: str) -> dict
```

**用途**:
- クリップ失敗（clip_status=failed）時、再度試行
- URL 先のコンテンツが修正された場合、再クリップ

**戻り値**: clip_status → pending で更新されたブックマーク

**WHEN TO USE**:
- クリップ失敗タスク（ネットワーク問題、サイト変更等）の復旧

---

## クリップ成功時の格納形式

**clipped_content** (Markdown):
```markdown
# Article Title

## Section 1

This is the extracted content.

- Bullet point 1
- Bullet point 2
```

**thumbnail** (PNG): フロントエンド表示用の サムネイル画像

---

## 使用パターン

### セッション中に参考記事検索

```
1. search_bookmarks(query="Tantivy search")
2. ヒット → clipped_content を確認
3. 実装に活用
```

### 新規記事保存

```
1. create_bookmark(url="https://example.com/article")
   → clip_status = pending で返却
2. バックグラウンドでクリップ実行
3. 数秒後 → clip_status = success、clipped_content 利用可能
4. 以降、get_bookmark で いつでも確認可能
```

---

**ツール総数**: 12（うち 2 は収集用補助関数）

**最終更新**: 2025-04-15
