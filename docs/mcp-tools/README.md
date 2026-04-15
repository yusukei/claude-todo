# MCPツール仕様書

MCP Todo は、タスク管理・プロジェクト管理・ドキュメント管理などを提供する FastMCP サーバです。このディレクトリはすべてのツール関数の仕様をまとめた公式リファレンスです。

## クイックリンク

MCPツールは11モジュール・29個のツール関数で構成されています。詳細は各モジュール別ファイルを参照してください。

| モジュール | ファイル | ツール数 | 概要 |
|----------|---------|--------|------|
| タスク管理 | [`tasks.md`](tasks.md) | 24 | タスク CRUD、サブタスク、コンテキスト取得、検索 |
| プロジェクト管理 | [`projects.md`](projects.md) | 6 | プロジェクト CRUD、プロジェクトサマリー |
| ブックマーク | [`bookmarks.md`](bookmarks.md) | 10 | ブックマーク CRUD、コレクション、Web クリップ |
| ドキュメント | [`documents.md`](documents.md) | 8 | 仕様書 CRUD、バージョン管理、検索 |
| ドックサイト | [`docsites.md`](docsites.md) | 9 | 外部ドキュメンション管理、ページ検索 |
| エラートラッカー | [`error-tracker.md`](error-tracker.md) | 12 | Sentry 統合、エラー issue 管理、自動タスク生成 |
| ナレッジベース | [`knowledge.md`](knowledge.md) | 6 | クロスプロジェクト技術ナレッジ保存・検索 |
| シークレット | [`secrets.md`](secrets.md) | 3 | 暗号化シークレット管理、監査ログ |
| APIフィードバック | [`feedback.md`](feedback.md) | 2 | MCPツール改善リクエスト提出・一覧 |
| リモート操作 | [`remote.md`](remote.md) | 15 | リモートコマンド実行、ファイル操作、grep等 |
| セットアップ | [`setup.md`](setup.md) | 1 | CLAUDE.md スニペット生成 |

## 共通仕様

### 認証

すべてのツールは X-API-Key ヘッダによる認証を必須とします。

- **X-API-Key**: MCP API キー（Base64 エンコード）
- 検証は `backend/app/mcp/auth.py` の `authenticate()` で行われる
- キーは `mcp_api_keys` MongoDB コレクションに登録
- キーが無効な場合、ToolError が返される

### エラー処理

エラーは `fastmcp.exceptions.ToolError` で返されます。形式:

```json
{
  "error": "ToolError",
  "message": "Human-readable error message"
}
```

典型的なエラーコード（ツール実装で返される）:
- "Authentication required" — X-API-Key が無効
- "Project not found" — プロジェクトが見つからない
- "Task not found" — タスクが見つからない
- "Project is locked" — プロジェクトがロック中、変更不可
- "Invalid {field}" — パラメータが不正

### プロジェクトの指定方法

ほとんどのツール関数は `project_id` パラメータを受け取ります。以下の形式で指定可能:

1. **ObjectId（24文字の16進数文字列）** — 例: `507f1f77bcf86cd799439011`
2. **プロジェクト名（文字列）** — 例: `"MyProject"`

内部的に `_resolve_project_id()` で正規化されます（タスク・プロジェクトモジュール参照）。

### レート制限

- 制限: **120 リクエスト/分** （IP単位）
- MCP server.py で設定

### フィールド長制限（ツール説明に明記）

- タイトル: 最大 255 文字
- 説明: 最大 10,000 文字
- コメント: 最大 10,000 文字
- API フィードバック説明: 最大 2,000 文字

### Beanie ORM 直接アクセス

すべてのツール関数は Beanie MongoDB ORM を直接使用します。HTTP 経由の間接呼び出しではありません。

- `from ...models import Project, Task, User, ...`
- `await Model.find(...).to_list()` / `await Model.get(id)`
- `await Model.save_updated()` — 自動 timestamp 更新（`updated_at`）

### イベント発行

タスク・プロジェクト変更時は SSE イベント発行:

```python
from ...services.events import publish_event
await publish_event(project_id, "task.updated", task_dict)
```

イベント種別:
- `task.created`, `task.updated`, `task.deleted`, `task.completed`, `task.archived`
- `project.created`, `project.updated`, `project.deleted`

### 削除の扱い

削除は **soft delete** です。`is_deleted: true` フラグで マーク。物理削除はしません。

## ツール分類

### 統計・状態確認系

これらのツールはセッション開始時に呼び出すことが推奨されています:

- `get_work_context(project_id, limit, skip)` — 承認済み・進行中・期限超過・詳細要調査タスク一覧
- `get_task_context(task_id, activity_limit)` — タスク詳細 + サブタスク + 活動ログを一度に取得
- `get_project_summary(project_id)` — プロジェクト進捗率・ステータス別集計

### needs_detail フラグのライフサイクル

（詳細は `tasks.md` を参照）

1. `create_task()` で `needs_detail=true` を指定 — 詳細要調査タスクを作成
2. AI エージェントが調査を実施 → `add_comment()` で所見を記録
3. `update_task()` で `approved=true` を設定 — needs_detail は自動クリア
4. or 不要であれば `archive_task()` / `delete_task()`

### approved フラグの遷移

（詳細は `tasks.md` を参照）

- `approved=false`（デフォルト）— 実装待ち、仕様確認中
- `approved=true` — 実装 OK、`status=in_progress` で進行中に変更可能

approved=true に変更すると needs_detail は自動で false になります。

## 既知の暗黙ルール（API ドキュメントより抽出）

### タスク管理

- **needs_detail タスクは実装ではなく調査対象** — 背景調査、複数選択肢提示、トレードオフ説明など（`feedback_needs_detail_workflow.md` 参照）
- **サブタスク** — 親タスクの完了はサブタスク完了を強制しない（独立管理）
- **タスク一覧** — `archived=false` がデフォルト（アーカイブ済みは非表示）。`archived=null` で全件取得
- **日付フィルタ** — ISO 8601 + ショートハンド（today, tomorrow, +7d, -3d, this_week, this_month）

### プロジェクト

- **プロジェクトロック** — `is_locked=true` のプロジェクトではタスク・ドキュメント変更が拒否される
- **プロジェクト削除** — soft delete（`status=archived`）。所属タスクも自動で soft delete
- **プロジェクト名から ID へ** — 5 分間キャッシュ（`_resolve_project_id`）

### ドキュメント

- **バージョン管理** — `update_document()` 呼び出しのたびにバージョン増加
- **Markdown + Mermaid** — ドキュメント内容は Markdown、Mermaid ブロック対応
- **タスク関連付け** — `task_id` を指定するとドキュメント更新がそのタスクに関連付けられる

### ブックマーク

- **Web クリップ** — `create_bookmark()` は 自動で Playwright でクリップ開始（`clip_status=pending`）
- **再クリップ** — `clip_bookmark()` で 再度クリップ試行
- **Clip Status**: `pending`, `success`, `failed`

### リモート実行

- **セッション持続** — リモートコマンド実行中に再接続が必要な場合、`remote_exec()` は セッション復帰を試みる
- **秘密注入** — `inject_secrets=true` でシークレット値を自動環境変数注入。秘密値を会話に露出させない
- **監査ログ** — すべてのリモートコマンド実行は監査テーブルに記録

## 使用パターン

### セッション開始（推奨ワークフロー）

```
1. list_projects() → 利用可能プロジェクト一覧
2. get_work_context(project_id) → 注力すべきタスク 4 カテゴリ
3. get_task_context(task_id) → 選択タスクの詳細
4. 作業開始...
```

### タスク作成→完了フロー

```
1. create_task(project_id, title, description)
2. [必要に応じて] add_comment(task_id, comment)
3. update_task(task_id, status="in_progress")
4. [実装...]
5. complete_task(task_id, completion_report="...")
```

### needs_detail タスク対応

```
1. list_tasks(project_id, needs_detail=true)
2. get_task_context(task_id)
3. [調査実施...]
4. add_comment(task_id, "## 調査結果\n...")
5. update_task(task_id, approved=true) または delete_task()
```

## トラブルシューティング

### "Project not found" エラー

- プロジェクト ID/名が正しいか確認
- プロジェクトがアーカイブされていないか確認
- ユーザーがプロジェクトメンバーであるか確認（admin は全プロジェクト可）

### "Project is locked" エラー

- プロジェクト管理者に、`update_project(project_id, is_locked=false)` で ロック解除を依頼

### X-API-Key エラー

- キーが Base64 エンコードされているか
- キーが有効期限内か
- キーが正しい MCP プロジェクトに割り当てられているか

## ファイルナビゲーション

- **メインファイル**: [`tasks.md`](tasks.md) （タスク管理はツール数が最多）
- **認証・共通**: 各ファイルの冒頭に認証処理について記載
- **索引**: 最下部に関連ツール・参考 API リンク

---

最終更新: 2025-04-15
