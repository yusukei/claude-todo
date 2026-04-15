# エラートラッカーツール仕様書

`backend/app/mcp/tools/error_tracker.py` のエラートラッキング関連ツール（全12関数）を記載します。

## 概要

Sentry 統合による エラートラッキング管理。自動的にエラーを issue に集約し、手動でタスク化・解決できます。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `list_error_issues` | エラー issue 一覧（フィルタ対応） |
| `get_error_issue` | issue 詳細 |
| `list_error_events` | issue 配下のイベント一覧 |
| `get_error_event` | イベント詳細 |
| `resolve_error_issue` | issue 解決マーク |
| `ignore_error_issue` | issue 無視（期間指定可） |
| `reopen_error_issue` | issue 再開 |
| `link_error_to_task` | error issue ↔ task リンク |
| `unlink_error_from_task` | リンク削除 |
| `create_task_from_error` | error issue からタスク自動作成 |
| `get_error_stats` | プロジェクトのエラー統計 |
| `rotate_error_dsn` | Sentry DSN ローテーション |
| `configure_error_auto_task` | エラー自動タスク化設定 |

**合計: 13 ツール関数**

---

## Issue CRUD

### list_error_issues

**概要**: エラー issue 一覧（status別、日付範囲等でフィルタ）

**シグネチャ**:
```python
async def list_error_issues(
    project_id: str,
    status: str | None = None,
    since: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `status` | str | — | None | フィルタ: `unresolved`, `resolved`, `ignored` |
| `since` | str | — | None | 日付フィルタ（ISO 8601 または相対形式） |
| `limit` | int | — | 20 | 最大返却件数 |
| `skip` | int | — | 0 | スキップ件数 |

**戻り値** (dict):
```json
{
  "items": [
    {
      "id": "...",
      "title": "AttributeError: 'NoneType' object has no attribute 'id'",
      "status": "unresolved",
      "first_seen": "2025-04-10T...",
      "last_seen": "2025-04-15T...",
      "event_count": 15,
      "user_count": 3,
      "level": "error",
      "linked_task_id": "..." or null
    }
  ],
  "total": 42,
  "limit": 20,
  "skip": 0
}
```

---

### get_error_issue

**概要**: issue 詳細

**シグネチャ**:
```python
async def get_error_issue(issue_id: str) -> dict
```

**戻り値**: list_error_issues と同じ + 詳細情報

---

## イベント・活動ログ

### list_error_events

**概要**: issue 配下のイベント一覧

**シグネチャ**:
```python
async def list_error_events(
    issue_id: str,
    limit: int = 10,
) -> list[dict]
```

**戻り値** (list):
```json
[
  {
    "id": "...",
    "timestamp": "2025-04-15T10:00:00+00:00",
    "level": "error",
    "message": "...",
    "exception": { ... },
    "stacktrace": [ ... ],
    "tags": { ... },
    "context": { ... }
  }
]
```

---

### get_error_event

**概要**: イベント詳細

**シグネチャ**:
```python
async def get_error_event(
    event_id: str,
    project_id: str,
) -> dict
```

---

## Issue ステータス遷移

### resolve_error_issue

**概要**: issue を解決済みマーク

**シグネチャ**:
```python
async def resolve_error_issue(
    issue_id: str,
    resolution: str | None = None,
) -> dict
```

**パラメータ**:
- `issue_id`: issue ID
- `resolution`: 解決方法（例: `"fixed_in_v1.2.3"`）

---

### ignore_error_issue

**概要**: issue を無視（期間指定可）

**シグネチャ**:
```python
async def ignore_error_issue(
    issue_id: str,
    until: str | None = None,
) -> dict
```

**パラメータ**:
- `until`: 無視期間（ISO 8601 または相対形式 `-7d`）

---

### reopen_error_issue

**概要**: issue を再開

**シグネチャ**:
```python
async def reopen_error_issue(issue_id: str) -> dict
```

---

## Issue ↔ Task リンク

### link_error_to_task

**概要**: error issue をタスクに関連付け

**シグネチャ**:
```python
async def link_error_to_task(
    issue_id: str,
    task_id: str,
) -> dict
```

---

### unlink_error_from_task

**概要**: リンク削除

**シグネチャ**:
```python
async def unlink_error_from_task(
    issue_id: str,
    task_id: str,
) -> dict
```

---

### create_task_from_error

**概要**: error issue からタスク自動作成

**シグネチャ**:
```python
async def create_task_from_error(
    issue_id: str,
    project_id: str,
    title: str | None = None,
    priority: str = "high",
) -> dict
```

**パラメータ**:
- `issue_id`: error issue ID
- `project_id`: タスク作成先プロジェクト
- `title`: カスタムタイトル（省略時は issue title）
- `priority`: デフォルト `"high"`

**副作用**:
- Task 作成
- error issue と task を自動リンク

---

## 統計・設定

### get_error_stats

**概要**: プロジェクト全体のエラー統計

**シグネチャ**:
```python
async def get_error_stats(
    project_id: str,
    period: str = "24h",
) -> dict
```

**period**: `"24h"`, `"7d"`, `"30d"`

**戻り値** (dict):
```json
{
  "period": "24h",
  "total_events": 152,
  "total_issues": 18,
  "new_issues": 3,
  "resolved_count": 2,
  "by_level": {
    "error": 140,
    "warning": 12
  },
  "by_status": {
    "unresolved": 15,
    "resolved": 2,
    "ignored": 1
  }
}
```

---

### rotate_error_dsn

**概要**: Sentry DSN ローテーション（キーローテーション）

**シグネチャ**:
```python
async def rotate_error_dsn(project_id: str) -> dict
```

**用途**: セキュリティキー定期更新

---

### configure_error_auto_task

**概要**: エラー自動タスク化設定

**シグネチャ**:
```python
async def configure_error_auto_task(
    project_id: str,
    enabled: bool,
    min_event_count: int = 5,
    auto_priority: str = "high",
) -> dict
```

**パラメータ**:
- `enabled`: 自動タスク化の有効/無効
- `min_event_count`: タスク化のイベント数閾値
- `auto_priority`: 自動作成タスクの priority

---

## 使用パターン

### エラー監視→対応フロー

```
1. get_error_stats(project_id) で統計確認
2. list_error_issues(status="unresolved") で未解決 issue 確認
3. get_error_issue(issue_id) で詳細確認
4. create_task_from_error(issue_id, project_id) でタスク作成
5. task 完了後、resolve_error_issue(issue_id) でマーク
```

---

**ツール総数**: 13 / 13

**最終更新**: 2025-04-15
