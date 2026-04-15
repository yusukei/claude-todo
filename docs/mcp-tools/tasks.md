# タスク管理ツール仕様書

`backend/app/mcp/tools/tasks.py` のタスク関連ツール（全24関数）を記載します。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `list_tasks` | プロジェクト内のタスク一覧（フィルタ・ソート対応） |
| `get_task` | タスク詳細取得 |
| `get_task_context` | タスク詳細 + サブタスク + 活動ログを一度に取得 |
| `get_work_context` | 承認済み・進行中・期限超過・needs_detail の 4 カテゴリを一覧 |
| `get_task_activity` | タスク活動ログ（ステータス遷移等の変更履歴） |
| `create_task` | タスク作成 |
| `update_task` | タスク編集（一部フィールド更新） |
| `delete_task` | タスク削除（soft delete） |
| `complete_task` | タスク完了（status=done） |
| `reopen_task` | タスク再開（status=todo） |
| `archive_task` | タスクアーカイブ |
| `unarchive_task` | アーカイブ解除 |
| `add_comment` | コメント追加 |
| `delete_comment` | コメント削除 |
| `search_tasks` | タスク全文検索（Tantivy + MongoDB） |
| `list_overdue_tasks` | 期限超過タスク一覧 |
| `list_users` | ユーザー一覧（assignee 選択用） |
| `batch_create_tasks` | 複数タスク一度作成 |
| `list_review_tasks` | needs_detail=true なタスク |
| `list_approved_tasks` | approved=true なタスク（プロジェクト横断） |
| `batch_update_tasks` | 複数タスク一度更新 |
| `get_subtasks` | サブタスク一覧 |
| `list_tags` | プロジェクト内タグ一覧 |
| `duplicate_task` | タスク複製 |
| `bulk_complete_tasks` | 複数タスク一度完了 |
| `bulk_archive_tasks` | 複数タスク一度アーカイブ |

**合計: 24 ツール関数**

---

## コンテキスト取得系

セッション開始時に呼び出すことが推奨されています。これら 3 つのツールで必要な情報の 90% を取得可能です。

### get_work_context

**概要**: 注力すべきタスクを 4 カテゴリで分類、一度に取得

**シグネチャ**:
```python
async def get_work_context(
    project_id: str,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前。クロスプロジェクトクエリは非対応 |
| `limit` | int | — | 20 | カテゴリあたりの返却最大件数 |
| `skip` | int | — | 0 | カテゴリあたりのスキップ件数（ページネーション用） |

**戻り値** (dict):
```json
{
  "approved": {
    "items": [{ task... }],
    "total": 5,
    "limit": 20,
    "skip": 0
  },
  "in_progress": { ... },
  "overdue": { ... },
  "needs_detail": { ... }
}
```

各カテゴリの意味:

- **approved**: 実装承認済み (approved=true)、実装待ち (status=todo) または進行中 (status=in_progress)
- **in_progress**: 現在進行中 (status=in_progress)
- **overdue**: 期限切れ (due_date < now)、未完了 (status ≠ done/cancelled/on_hold)
- **needs_detail**: 詳細要調査 (needs_detail=true)、未完了

**WHEN TO USE**:
- セッション開始時の優先タスク把握
- プロジェクトの現在の進捗確認

**関連ツール**: `get_task_context`, `list_tasks`, `list_review_tasks`, `list_approved_tasks`

---

### get_task_context

**概要**: タスク詳細 + サブタスク + 活動ログを一度に取得。複数往復を避けたいときに利用。

**シグネチャ**:
```python
async def get_task_context(
    task_id: str,
    activity_limit: int = 20,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |
| `activity_limit` | int | — | 20 | 活動ログの最大返却件数（最新順） |

**戻り値** (dict):
```json
{
  "task": { task details... },
  "parent": {
    "id": "...",
    "title": "親タスク名",
    "status": "in_progress"
  },
  "subtasks": {
    "items": [{ subtask... }],
    "total": 3
  },
  "activity": {
    "entries": [
      {
        "field": "status",
        "old_value": "todo",
        "new_value": "in_progress",
        "changed_by": "mcp:my-key",
        "changed_at": "2025-04-15T10:30:00+00:00"
      }
    ],
    "total": 10
  }
}
```

**副作用**:
- なし（読み取り専用）

**WHEN TO USE**:
- タスク詳細を確認するとき（代わりに `get_task` + `get_subtasks` + `get_task_activity` を 3 回呼ぶ必要がない）
- サブタスク構成を把握したい
- 変更履歴を確認したい

**関連ツール**: `get_task`, `get_subtasks`, `get_task_activity`

---

### get_task_activity

**概要**: タスクの変更履歴（ステータス遷移、優先度変更等）を時系列で取得

**シグネチャ**:
```python
async def get_task_activity(
    task_id: str,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |
| `limit` | int | — | 20 | 最大返却件数（最新順） |
| `skip` | int | — | 0 | スキップ件数（ページネーション） |

**戻り値** (dict):
```json
{
  "task_id": "...",
  "title": "タスク名",
  "entries": [
    {
      "field": "status",
      "old_value": "todo",
      "new_value": "in_progress",
      "changed_by": "mcp:my-key",
      "changed_at": "2025-04-15T10:30:00+00:00"
    }
  ],
  "total": 15,
  "limit": 20,
  "skip": 0
}
```

**WHEN TO USE**:
- タスクの変更経歴を確認する（デバッグ、監査）
- いつ誰が何を変えたかを追跡

---

## タスク CRUD 系

### list_tasks

**概要**: プロジェクト内タスク一覧（フィルタ・ソート対応）

**シグネチャ**:
```python
async def list_tasks(
    project_id: str,
    status: str | None = None,
    priority: str | None = None,
    task_type: str | None = None,
    assignee_id: str | None = None,
    tag: str | None = None,
    needs_detail: bool | None = None,
    approved: bool | None = None,
    archived: bool | None = False,
    due_before: str | None = None,
    due_after: str | None = None,
    sort_by: str = "sort_order",
    order: str = "asc",
    limit: int = 50,
    skip: int = 0,
    summary: bool = False,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `status` | str | — | None | フィルタ: `todo`, `in_progress`, `on_hold`, `done`, `cancelled` |
| `priority` | str | — | None | フィルタ: `low`, `medium`, `high`, `urgent` |
| `task_type` | str | — | None | フィルタ: `action`, `decision` |
| `assignee_id` | str | — | None | 担当者 ID でフィルタ |
| `tag` | str | — | None | タグ名でフィルタ（1 つのタグのみ） |
| `needs_detail` | bool | — | None | needs_detail フラグでフィルタ |
| `approved` | bool | — | None | approved フラグでフィルタ |
| `archived` | bool | — | False | **デフォルト False**: アーカイブ済みは非表示。`null` で全件表示 |
| `due_before` | str | — | None | 期限がこの日付より前（ISO 8601 またはショートハンド） |
| `due_after` | str | — | None | 期限がこの日付より後 |
| `sort_by` | str | — | `sort_order` | ソート対象: `sort_order`, `created_at`, `due_date`, `priority`, `updated_at` |
| `order` | str | — | `asc` | ソート順序: `asc`, `desc` |
| `limit` | int | — | 50 | 最大返却件数 |
| `skip` | int | — | 0 | スキップ件数 |
| `summary` | bool | — | False | true なら comments/attachments を除外（軽量ペイロード） |

**日付フィルタの形式**:
- ISO 8601: `2025-12-31`, `2025-12-31T23:59:59+00:00`
- ショートハンド: `today`, `tomorrow`, `yesterday`, `this_week`, `next_week`, `this_month`, `+7d`, `-3d`

**戻り値** (dict):
```json
{
  "items": [{ task... }],
  "total": 42,
  "limit": 50,
  "skip": 0
}
```

**エラー**:
- `"Invalid sort_by '{field}'..."` — sort_by が不正
- `"Invalid order '{value}'..."` — order が不正

**WHEN TO USE**:
- 特定プロジェクトのタスク一覧表示
- フィルタ・ソート付きで特定条件のタスク抽出

**関連ツール**: `search_tasks` (全文検索用), `list_work_context` (優先タスク用)

---

### get_task

**概要**: タスク詳細取得（comments、attachments 含む）

**シグネチャ**:
```python
async def get_task(task_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |

**戻り値** (dict): Task オブジェクト全体（コメント、添付ファイル含む）

```json
{
  "id": "...",
  "project_id": "...",
  "title": "...",
  "description": "...",
  "status": "in_progress",
  "priority": "high",
  "task_type": "action",
  "decision_context": null,
  "due_date": "2025-12-31T00:00:00+00:00",
  "assignee_id": "...",
  "parent_task_id": null,
  "tags": ["feature", "urgent"],
  "needs_detail": false,
  "approved": true,
  "archived": false,
  "created_at": "2025-04-01T10:00:00+00:00",
  "updated_at": "2025-04-15T10:00:00+00:00",
  "created_by": "mcp:my-key",
  "completed_at": null,
  "completion_report": null,
  "comments": [
    {
      "id": "...",
      "content": "...",
      "author_id": "mcp",
      "author_name": "Claude",
      "created_at": "2025-04-15T10:30:00+00:00"
    }
  ],
  "attachments": [
    {
      "id": "...",
      "filename": "screenshot.png",
      "size": 1024,
      "created_at": "..."
    }
  ],
  "activity_log": [...]
}
```

**エラー**:
- `"Task not found"` — タスク ID が無効または deleted

**WHEN TO USE**:
- 単一タスクの詳細確認
- コメント・添付ファイルを含めたい

---

### create_task

**概要**: タスク作成

**シグネチャ**:
```python
async def create_task(
    project_id: str,
    title: str,
    description: str = "",
    priority: str = "medium",
    status: str = "todo",
    task_type: str = "action",
    decision_context: dict | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    parent_task_id: str | None = None,
    tags: list[str] | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `title` | str | ○ | — | タスクタイトル（最大 255 文字） |
| `description` | str | — | `""` | タスク説明（Markdown 対応、最大 10,000 文字） |
| `priority` | str | — | `"medium"` | 優先度: `low`, `medium`, `high`, `urgent` |
| `status` | str | — | `"todo"` | 初期ステータス: `todo`, `in_progress`, `on_hold`, `done`, `cancelled` |
| `task_type` | str | — | `"action"` | タスク種別: `action`, `decision` |
| `decision_context` | dict | — | None | **task_type="decision" の場合必須**。以下の構造: |
| | | | | `{ "background": "背景", "decision_point": "決定事項", "options": [{"label": "選択肢 A", "description": "..."}], "recommendation": "推奨..." }` |
| `due_date` | str | — | None | 期限（ISO 8601 形式） |
| `assignee_id` | str | — | None | 担当者ユーザー ID |
| `parent_task_id` | str | — | None | 親タスク ID（サブタスク化） |
| `tags` | list[str] | — | None | タグ名リスト |

**戻り値**: 作成されたタスク dict

**バリデーション**:
- タイトル: 最大 255 文字
- 説明: 最大 10,000 文字
- task_type が "decision" の場合、decision_context.decision_point 必須
- priority、status、task_type は enum 値チェック

**副作用**:
- DB に insert
- SSE イベント `task.created` 発行
- Tantivy インデックスに追加

**エラー**:
- `"Title exceeds maximum length of 255 characters"`
- `"Description exceeds maximum length of 10000 characters"`
- `"Invalid task_type..."`, `"Invalid priority..."`, `"Invalid status..."`
- `"decision_context with at least 'decision_point' is required when task_type='decision'"`
- `"Project is locked..."` — プロジェクトロック状態

**WHEN TO USE**:
- 新規タスク作成
- needs_detail=true タスクを作成したい場合は `update_task()` で その後設定

**関連ツール**: `batch_create_tasks` (複数作成), `update_task`

---

### update_task

**概要**: タスク編集（指定フィールドのみ更新）

**シグネチャ**:
```python
async def update_task(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    decision_context: dict | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    tags: list[str] | None = None,
    completion_report: str | None = None,
    needs_detail: bool | None = None,
    approved: bool | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |
| `title`, `description`, ... | 各型 | — | None | 更新する フィール。None なら変更なし |
| `needs_detail` | bool | — | None | **needs_detail=true** — 詳細要調査フラグ。設定時に自動で approved=false へ |
| `approved` | bool | — | None | **approved=true** — 実装承認フラグ。設定時に自動で needs_detail=false へ |

**needs_detail と approved の関係**:
- needs_detail=true に設定 → approved は自動で false に
- approved=true に設定 → needs_detail は自動で false に
- 両者は相互排他的

**フィールド長チェック**:
- title: 最大 255 文字
- description: 最大 10,000 文字
- completion_report: 最大 10,000 文字

**副作用**:
- 変更フィールド（status, priority, assignee_id, task_type, needs_detail, approved）は activity_log に記録
- SSE イベント `task.updated` 発行
- Tantivy インデックス更新

**エラー**:
- `"Task not found"`
- `"Project is locked..."`
- フィールド長バリデーション

**WHEN TO USE**:
- タスクの一部フィール更新
- needs_detail/approved フラグの遷移
- **注**: 一度に複数フィールド更新可能（複数往復回避）

**関連ツール**: `complete_task`, `archive_task`, `batch_update_tasks`

---

### delete_task

**概要**: タスク削除（soft delete）

**シグネチャ**:
```python
async def delete_task(task_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |

**戻り値** (dict):
```json
{ "success": true, "task_id": "..." }
```

**副作用**:
- is_deleted = true へマーク（物理削除ではなく soft delete）
- SSE イベント `task.deleted` 発行
- Tantivy インデックスから削除

**エラー**:
- `"Task not found"`
- `"Project is locked..."`

**WHEN TO USE**:
- タスク削除
- needs_detail タスクの調査後、不要と判断して削除

---

## タスク状態遷移系

### complete_task

**概要**: タスク完了（status を done に設定）

**シグネチャ**:
```python
async def complete_task(
    task_id: str,
    completion_report: str | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |
| `completion_report` | str | — | None | 完了報告（Markdown 対応、最大 10,000 文字） |

**副作用**:
- status → TaskStatus.done
- completed_at に現在時刻を設定
- activity_log に status 変更を記録
- SSE イベント発行

**エラー**:
- `"Completion report exceeds maximum length of 10000 characters"`

**WHEN TO USE**:
- タスク完了マーク（これで自動的に完了日時が記録される）

---

### reopen_task

**概要**: 完了・キャンセル済みタスクを再開（status → todo）

**シグネチャ**:
```python
async def reopen_task(task_id: str) -> dict
```

**副作用**:
- status → TaskStatus.todo
- completed_at → None
- activity_log に記録

**WHEN TO USE**:
- 誤入力で完了してしまったタスク の再開

---

### archive_task / unarchive_task

**概要**: タスクアーカイブ（表示非表示制御）

**シグネチャ**:
```python
async def archive_task(task_id: str) -> dict
async def unarchive_task(task_id: str) -> dict
```

**副作用**:
- archived フラグを true/false に設定
- list_tasks で archived=false がデフォルトなので、アーカイブ後は non-default リストから非表示

**WHEN TO USE**:
- 完了済みタスクをリストから非表示にしたい（削除ではなく保持）
- 後で見直すことがあるときはアーカイブが便利

---

## コメント系

### add_comment

**概要**: タスクにコメント追加（needs_detail 調査結果の記録等）

**シグネチャ**:
```python
async def add_comment(task_id: str, content: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |
| `content` | str | ○ | — | コメント本文（最大 10,000 文字、Markdown 対応） |

**戻り値**: 更新後のタスク dict（comments リスト含む）

**コメント構造**:
```json
{
  "id": "unique-id",
  "content": "...",
  "author_id": "mcp",
  "author_name": "Claude",
  "created_at": "2025-04-15T10:30:00+00:00"
}
```

**副作用**:
- comment を task.comments リストに append
- SSE イベント `comment.added` 発行
- Tantivy インデックス更新

**エラー**:
- `"Comment content exceeds maximum length of 10000 characters"`

**WHEN TO USE**:
- needs_detail タスクの調査結果記録（タスク説明を変更せず、findings だけコメント）
- タスク進捗の中間報告
- 実装時の注記・トラブルシューティング

**推奨ワークフロー**（needs_detail の場合）:
```
1. get_task(task_id) # needs_detail=true 確認
2. [調査実施...]
3. add_comment(task_id, "## 調査結果\n- 選択肢 A のメリット: ...\n- 選択肢 B のデメリット: ...")
4. update_task(task_id, approved=true) # または delete_task
```

---

### delete_comment

**概要**: コメント削除

**シグネチャ**:
```python
async def delete_comment(task_id: str, comment_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | タスク ID |
| `comment_id` | str | ○ | — | コメント ID（get_task 返却の comments[].id） |

**副作用**:
- comments リストから該当コメント削除
- SSE イベント `comment.deleted` 発行

**エラー**:
- `"Comment not found"`

---

## 検索・フィルタ系

### search_tasks

**概要**: タスク全文検索（Tantivy + MongoDB $regex フォールバック）

**シグネチャ**:
```python
async def search_tasks(
    query: str,
    project_id: str,
    status: str | None = None,
    needs_detail: bool | None = None,
    approved: bool | None = None,
    limit: int = 50,
    skip: int = 0,
    summary: bool = False,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `query` | str | ○ | — | 検索キーワード（Tantivy が有効な場合、Tantivy クエリ構文対応） |
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `status`, `needs_detail`, `approved` | 各型 | — | None | フィルタ（AND 条件） |
| `limit` | int | — | 50 | 最大返却件数 |
| `skip` | int | — | 0 | スキップ件数 |
| `summary` | bool | — | False | true なら comments/attachments 除外 |

**検索対象**:
- title, description, tags, comments（Tantivy が有効な場合）
- title, description（MongoDB $regex フォールバック） 
- 日本語形態素解析対応（Lindera）

**戻り値** (dict):
```json
{
  "items": [{ task... }],
  "total": 12,
  "limit": 50,
  "skip": 0,
  "_meta": {
    "search_engine": "tantivy" or "regex"
  }
}
```

**フォールバック動作**:
- Tantivy が利用不可または失敗時、自動で MongoDB $regex にフォールバック
- `_meta.search_engine` で実際に使われたエンジンを判定可能

**WHEN TO USE**:
- キーワード検索
- 複数プロジェクトの検索は `list_projects()` でループして複数回呼び出し

**関連ツール**: `list_tasks` (構造化フィルタ用)

---

### list_overdue_tasks

**概要**: 期限超過タスク（due_date < now、未完了）

**シグネチャ**:
```python
async def list_overdue_tasks(
    project_id: str,
    limit: int = 50,
    skip: int = 0,
    summary: bool = False,
) -> dict
```

**パラメータ**: list_tasks と同じ（フィルタ機能なし）

**フィルタ条件** (自動):
- due_date < 現在時刻
- status NOT IN [on_hold, done, cancelled]
- is_deleted = false

**WHEN TO USE**:
- 期限超過タスク の緊急処理

---

## ユーザー・リスト系

### list_users

**概要**: ユーザー一覧（assignee 選択用）

**シグネチャ**:
```python
async def list_users() -> list[dict]
```

**戻り値** (list):
```json
[
  {
    "id": "...",
    "name": "Alice",
    "email": "alice@example.com"
  }
]
```

---

### list_tags

**概要**: プロジェクト内のタグ一覧

**シグネチャ**:
```python
async def list_tags(project_id: str) -> list[str]
```

**戻り値** (list):
```json
["feature", "bug", "documentation", "refactoring"]
```

---

## バッチ・一括系

### batch_create_tasks

**概要**: 複数タスク一度作成

**シグネチャ**:
```python
async def batch_create_tasks(
    project_id: str,
    tasks: list[dict],
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `tasks` | list[dict] | ○ | — | 各 dict は create_task と同じフィール (title 必須) |

**戻り値** (dict):
```json
{
  "created": [{ task... }, ...],
  "failed": [
    {
      "title": "...",
      "error": "Title exceeds maximum length of 255 characters"
    }
  ]
}
```

**エラー処理**:
- バリデーション失敗したアイテムは `failed` リストに追加
- 成功したアイテムは `created` リストに追加
- 部分的な失敗でも ToolError は返さず、結果に failed を含める

**WHEN TO USE**:
- 複数タスクの一度作成（例：マイグレーション、インポート）

---

### batch_update_tasks

**概要**: 複数タスク一度更新

**シグネチャ**:
```python
async def batch_update_tasks(updates: list[dict]) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `updates` | list[dict] | ○ | — | 各 dict は "task_id" 必須、後は update_task と同じフィール |

**構造例**:
```json
[
  {
    "task_id": "...",
    "status": "in_progress",
    "priority": "high"
  },
  {
    "task_id": "...",
    "approved": true
  }
]
```

**戻り値** (dict):
```json
{
  "updated": [{ task... }, ...],
  "failed": [
    {
      "task_id": "...",
      "error": "..."
    }
  ]
}
```

---

### bulk_complete_tasks

**概要**: 複数タスク一度完了

**シグネチャ**:
```python
async def bulk_complete_tasks(
    task_ids: list[str],
    completion_report: str | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_ids` | list[str] | ○ | — | タスク ID リスト |
| `completion_report` | str | — | None | 全タスク共通の完了報告（あれば各タスクに付与） |

**戻り値** (dict):
```json
{
  "completed": [{ task... }],
  "failed": [{ "task_id": "...", "error": "..." }]
}
```

---

### bulk_archive_tasks

**概要**: 複数タスク一度アーカイブ

**シグネチャ**:
```python
async def bulk_archive_tasks(task_ids: list[str]) -> dict
```

**戻り値** (dict):
```json
{
  "archived": [{ task... }],
  "failed": [...]
}
```

---

## 特殊ツール

### list_review_tasks

**概要**: needs_detail=true なタスク（調査対象タスク）

**シグネチャ**:
```python
async def list_review_tasks(
    project_id: str,
    limit: int = 50,
    skip: int = 0,
) -> dict
```

**等価**:
```python
list_tasks(project_id, needs_detail=True)
```

---

### list_approved_tasks

**概要**: approved=true なタスク（実装準備OK）— **プロジェクト横断**

**シグネチャ**:
```python
async def list_approved_tasks(
    limit: int = 50,
    skip: int = 0,
) -> dict
```

**特徴**:
- project_id 不要（ユーザーがアクセス可能なすべてのプロジェクトを横断）
- status=todo または in_progress、approved=true のみ返却

**WHEN TO USE**:
- セッション開始時、複数プロジェクトの実装待ちタスク一覧

---

### get_subtasks

**概要**: サブタスク一覧（親タスク ID で指定）

**シグネチャ**:
```python
async def get_subtasks(
    parent_task_id: str,
    limit: int = 50,
    skip: int = 0,
) -> dict
```

**戻り値** (dict):
```json
{
  "items": [{ subtask... }],
  "total": 5,
  "limit": 50,
  "skip": 0
}
```

**注意**:
- 親タスク完了 ≠ サブタスク自動完了（独立管理）

---

### duplicate_task

**概要**: タスク複製（新規タスク作成）

**シグネチャ**:
```python
async def duplicate_task(
    task_id: str,
    new_title: str | None = None,
    new_project_id: str | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `task_id` | str | ○ | — | 複製元タスク ID |
| `new_title` | str | — | None | 新規タイトル（省略時は元タイトル + " (copy)"） |
| `new_project_id` | str | — | None | 新規プロジェクト（省略時は元プロジェクト） |

**複製対象フィール**:
- title, description, priority, task_type, decision_context, due_date, assignee_id, tags
- **複製されない**: status, approved, needs_detail, completed_at, completion_report, comments, attachments

**戻り値**: 新規作成タスク dict

---

## リレーション・アーカイブメント図

```
Task
├─ parent_task_id → Task (サブタスク構造)
├─ assignee_id → User
├─ comments[]: Comment
│  ├─ author_id
│  └─ content
├─ activity_log[]: ActivityEntry
│  └─ field, old_value, new_value, changed_by, changed_at
└─ attachments[]: Attachment
   ├─ filename
   └─ size
```

---

## needs_detail ライフサイクル図

```
作成時: needs_detail = false（デフォルト）
        or needs_detail = true（調査対象として）

needs_detail = true の場合:
  │
  ├─ get_work_context() で needs_detail カテゴリに表示
  ├─ AI が調査実施
  ├─ add_comment() で findings 記録
  └─ update_task(needs_detail=false) or update_task(approved=true) or delete_task()

update_task(approved=true) の場合:
  └─ needs_detail は自動で false に（相互排他）
```

---

## サンプルコード

### セッション開始フロー

```
1. get_work_context(project_id) 
   → approved, in_progress, overdue, needs_detail 確認

2. needs_detail タスク発見時:
   get_task_context(task_id)
   → 詳細 + サブタスク + activity 取得

3. 調査開始:
   add_comment(task_id, "## 調査結果\n...")

4. 完了判定:
   update_task(task_id, approved=true)  # または delete_task()
```

### needs_detail タスク対応フロー

```python
# 1. needs_detail タスク一覧
tasks = await list_review_tasks(project_id)

for task in tasks["items"]:
    # 2. 詳細取得
    context = await get_task_context(task["id"])
    
    # 3. 調査実施（省略）
    # ...
    
    # 4. 所見記録
    await add_comment(task["id"], findings)
    
    # 5. 承認またはキャンセル
    if decision == "approve":
        await update_task(task["id"], approved=true)
    else:
        await delete_task(task["id"])
```

---

## エラーハンドリング

すべてのエラーは `ToolError` で返されます。共通パターン:

```python
try:
    await update_task(task_id, title="...")
except ToolError as e:
    if "Task not found" in str(e):
        # タスク無効
        pass
    elif "Project is locked" in str(e):
        # プロジェクトロック
        pass
    elif "exceeds maximum length" in str(e):
        # フィールド長超過
        pass
    else:
        raise
```

---

**ツール総数**: 24 / 24

**最終更新**: 2025-04-15
