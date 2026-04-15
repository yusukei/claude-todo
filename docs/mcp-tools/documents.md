# ドキュメント管理ツール仕様書

`backend/app/mcp/tools/documents.py` のドキュメント関連ツール（全8関数）を記載します。

## 概要

プロジェクト内の仕様書・ドキュメントを Markdown で管理します。変更履歴は自動記録され、バージョン管理が可能です。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `create_document` | ドキュメント作成 |
| `get_document` | ドキュメント取得（最新版） |
| `update_document` | ドキュメント編集・更新 |
| `delete_document` | ドキュメント削除（soft delete） |
| `list_documents` | プロジェクト内ドキュメント一覧 |
| `search_documents` | ドキュメント全文検索 |
| `get_document_history` | バージョン履歴一覧 |
| `get_document_version` | 特定バージョン取得 |

**合計: 8 ツール関数**

---

## CRUD 系

### create_document

**概要**: ドキュメント作成

**シグネチャ**:
```python
async def create_document(
    project_id: str,
    title: str,
    content: str = "",
    section: str = "general",
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `title` | str | ○ | — | ドキュメントタイトル（最大 255 文字） |
| `content` | str | — | `""` | Markdown 本文（最大 100,000 文字） |
| `section` | str | — | `"general"` | セクション（例: "spec", "architecture", "general"） |

**content 対応フォーマット**:
- Markdown （見出し、リスト、テーブル等）
- Mermaid ブロック（\`\`\`mermaid ... \`\`\`）

**副作用**:
- DB に Document 挿入
- version = 1 で初期化
- 索引に追加

**戻り値** (dict):
```json
{
  "id": "...",
  "project_id": "...",
  "title": "...",
  "content": "...",
  "section": "general",
  "version": 1,
  "task_id": null,
  "created_by": "mcp:my-key",
  "created_at": "...",
  "updated_at": "...",
  "is_deleted": false
}
```

---

### get_document

**概要**: ドキュメント取得（最新版）

**シグネチャ**:
```python
async def get_document(document_id: str) -> dict
```

**戻り値**: create_document と同じ構造

---

### update_document

**概要**: ドキュメント編集・更新

**シグネチャ**:
```python
async def update_document(
    document_id: str,
    title: str | None = None,
    content: str | None = None,
    section: str | None = None,
    task_id: str | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `document_id` | str | ○ | — | ドキュメント ID |
| `title` | str | — | None | 新規タイトル |
| `content` | str | — | None | 新規内容 |
| `section` | str | — | None | 新規セクション |
| `task_id` | str | — | None | このドキュメント更新を関連付けるタスク ID |

**特徴**:
- 呼び出すたびに **version が 1 増加**
- task_id を指定すると、ドキュメント更新がそのタスクに関連付けられる
- 変更前の version はドキュメント履歴に保存

**副作用**:
- version 自動増加
- updated_at 更新
- 索引再索引

**戻り値** (dict): 更新後のドキュメント（version 増加）

---

### delete_document

**概要**: ドキュメント削除（soft delete）

**シグネチャ**:
```python
async def delete_document(document_id: str) -> dict
```

**戻り値** (dict):
```json
{ "success": true, "document_id": "..." }
```

---

### list_documents

**概要**: プロジェクト内ドキュメント一覧

**シグネチャ**:
```python
async def list_documents(
    project_id: str,
    section: str | None = None,
    limit: int = 50,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `section` | str | — | None | セクション でフィルタ |
| `limit` | int | — | 50 | 最大返却件数 |
| `skip` | int | — | 0 | スキップ件数 |

**戻り値** (dict):
```json
{
  "items": [{ document... }],
  "total": 12,
  "limit": 50,
  "skip": 0
}
```

---

## 検索・履歴系

### search_documents

**概要**: ドキュメント全文検索

**シグネチャ**:
```python
async def search_documents(
    query: str,
    project_id: str,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**検索対象**:
- title, content

**戻り値** (dict):
```json
{
  "items": [{ document... }],
  "total": 3,
  "limit": 20,
  "skip": 0,
  "_meta": { "search_engine": "tantivy" or "regex" }
}
```

---

### get_document_history

**概要**: ドキュメントのバージョン履歴一覧

**シグネチャ**:
```python
async def get_document_history(
    document_id: str,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**戻り値** (dict):
```json
{
  "document_id": "...",
  "title": "...",
  "versions": [
    {
      "version": 3,
      "title": "...",
      "content": "...",
      "section": "spec",
      "task_id": "...",
      "updated_by": "mcp:my-key",
      "updated_at": "2025-04-15T10:00:00+00:00"
    },
    {
      "version": 2,
      "title": "...",
      "content": "...",
      ...
    }
  ],
  "total": 5,
  "limit": 20,
  "skip": 0
}
```

**WHEN TO USE**:
- ドキュメント更新の経歴確認
- 誰が何を、いつ変更したか追跡

---

### get_document_version

**概要**: 特定バージョンのドキュメント取得

**シグネチャ**:
```python
async def get_document_version(
    document_id: str,
    version: int,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `document_id` | str | ○ | — | ドキュメント ID |
| `version` | int | ○ | — | バージョン番号（1 以上） |

**戻り値** (dict): 指定 version のドキュメント

**WHEN TO USE**:
- 過去バージョンの内容確認
- バージョン間の diff 確認（手動比較）

---

## 使用パターン

### タスク実装時のドキュメント活用

```
1. create_task() でタスク作成
2. search_documents(query=task_keywords) で既存仕様確認
3. update_document(task_id=task_id) でドキュメント更新
   → このドキュメント更新がタスクに関連付けられる
4. complete_task() でタスク完了
   → タスクの completion_report でドキュメント参照可能
```

---

**ツール総数**: 8 / 8

**最終更新**: 2025-04-15
