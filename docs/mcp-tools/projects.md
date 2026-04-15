# プロジェクト管理ツール仕様書

`backend/app/mcp/tools/projects.py` のプロジェクト関連ツール（全6関数）を記載します。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `list_projects` | アクセス可能なプロジェクト一覧 |
| `get_project` | プロジェクト詳細 |
| `create_project` | プロジェクト作成 |
| `update_project` | プロジェクト編集 |
| `delete_project` | プロジェクト削除（soft delete） |
| `get_project_summary` | プロジェクト進捗率・ステータス別集計 |

**合計: 6 ツール関数**

---

## プロジェクト CRUD 系

### list_projects

**概要**: アクセス可能なプロジェクト一覧

**シグネチャ**:
```python
async def list_projects() -> list[dict]
```

**特徴**:
- **admin ユーザー**: すべてのアクティブプロジェクトを返却
- **一般ユーザー**: members リストに自分が含まれるプロジェクトのみ返却

**戻り値** (list[dict]):
```json
[
  {
    "id": "...",
    "name": "MyProject",
    "description": "Project description",
    "color": "#6366f1",
    "status": "active",
    "is_locked": false,
    "created_by": { "id": "...", "name": "Admin", "email": "..." },
    "created_at": "2025-01-01T00:00:00+00:00",
    "updated_at": "2025-04-15T10:00:00+00:00",
    "members": [
      {
        "user_id": "...",
        "user": { "id": "...", "name": "Alice", "email": "..." },
        "role": "owner" or "editor" or "viewer"
      }
    ]
  }
]
```

**WHEN TO USE**:
- セッション開始時、利用可能プロジェクト一覧表示
- 複数プロジェクト間の処理時、プロジェクト一覧ループ

---

### get_project

**概要**: プロジェクト詳細取得

**シグネチャ**:
```python
async def get_project(project_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID（24文字の16進数）またはプロジェクト名 |

**戻り値** (dict): list_projects と同じ構造

**エラー**:
- `"Project not found"` — ID が無効またはアーカイブ済み
- `"Authentication required"` — アクセス権限なし

**WHEN TO USE**:
- 単一プロジェクトの詳細確認
- プロジェクト名から ID に解決後の詳細参照

---

### create_project

**概要**: プロジェクト作成

**シグネチャ**:
```python
async def create_project(
    name: str,
    description: str = "",
    color: str = "#6366f1",
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `name` | str | ○ | — | プロジェクト名 |
| `description` | str | — | `""` | プロジェクト説明 |
| `color` | str | — | `"#6366f1"` | 16進数カラーコード（例: #ff5733） |

**副作用**:
- DB に Project 挿入
- admin ユーザーが creator・最初のメンバーに自動追加
- エラートラッキング設定を自動プロビジョニング（Sentry DSN 生成）
- SSE イベント `project.created` 発行

**戻り値** (dict): 作成されたプロジェクト dict（list_projects と同じ構造）

**エラー**:
- `"No admin user found to set as project creator"` — 初期化エラー

**WHEN TO USE**:
- 新規プロジェクト作成

**後処理**:
- プロジェクト作成直後は、members に admin ユーザーのみ含まれる
- 他ユーザーを追加するには REST API `/api/v1/projects/{id}/members` を使用

---

### update_project

**概要**: プロジェクト編集（指定フィール のみ更新）

**シグネチャ**:
```python
async def update_project(
    project_id: str,
    name: str | None = None,
    description: str | None = None,
    color: str | None = None,
    status: str | None = None,
    is_locked: bool | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `name` | str | — | None | 新規プロジェクト名 |
| `description` | str | — | None | 新規説明 |
| `color` | str | — | None | 新規カラーコード |
| `status` | str | — | None | 新規ステータス: `active`, `archived` |
| `is_locked` | bool | — | None | ロック状態（true = 変更禁止） |

**is_locked フラグの効果**:
- `is_locked=true` のプロジェクトではタスク・ドキュメント変更が拒否される
- プロジェクト設定（name, description など）は変更可能

**副作用**:
- updated_at 自動更新
- SSE イベント `project.updated` 発行

**戻り値** (dict): 更新後のプロジェクト dict

**エラー**:
- `"Project not found"`
- `"Invalid status '{value}'. Valid: active, archived"`

**WHEN TO USE**:
- プロジェクト設定変更
- プロジェクトロック・アンロック
- プロジェクトアーカイブ（status=archived）

---

### delete_project

**概要**: プロジェクト削除（soft delete）

**シグネチャ**:
```python
async def delete_project(project_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |

**動作**:
1. プロジェクト status → archived
2. **プロジェクト内のすべてのタスク** （is_deleted → true） に自動 soft delete

**戻り値** (dict):
```json
{
  "success": true,
  "project_id": "..."
}
```

**副作用**:
- SSE イベント `project.deleted` 発行
- 所属タスク・コメント・活動ログはそのまま保持（is_deleted フラグで非表示）

**エラー**:
- `"Project not found"`

**WHEN TO USE**:
- プロジェクト廃止

**注意**: 完全削除ではなく soft delete なので、復元は可能（admin は status=active に戻すことで復活可能）

---

## 統計・分析系

### get_project_summary

**概要**: プロジェクト進捗率・ステータス別タスク集計

**シグネチャ**:
```python
async def get_project_summary(project_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |

**戻り値** (dict):
```json
{
  "project_id": "...",
  "total": 42,
  "by_status": {
    "todo": 10,
    "in_progress": 8,
    "on_hold": 3,
    "done": 20,
    "cancelled": 1
  },
  "completion_rate": 47.6
}
```

**計算方法**:
- `completion_rate = (done_count / total) * 100`（小数点第1位まで）
- total = 0 の場合、completion_rate = 0

**WHEN TO USE**:
- プロジェクト進捗確認
- ダッシュボード表示
- プロジェクト管理者向けレポート

---

## プロジェクト名の解決メカニズム

（内部実装）プロジェクト ID またはプロジェクト名を受け取り、ID に正規化します。

### 解決ロジック

1. 入力が 24 文字の 16 進数 → ObjectId として直接使用
2. 5 分間のメモリキャッシュを確認 → ヒット時はキャッシュ値
3. MongoDB から name で検索 → 一致するアクティブプロジェクト return
4. キャッシュに保存
5. 見つからない → ToolError("Project not found: {name}")

**キャッシュ有効期限**: 5 分（_PROJECT_CACHE_TTL = 300 秒）

**パフォーマンス**: 同じプロジェクト名を繰り返し指定しても、2 回目以降はキャッシュ hit で DB 不問

---

## プロジェクトロック

プロジェクトロック（is_locked=true）時の制約:

| 操作 | 許可 | 備考 |
|-----|------|------|
| list_tasks | ○ | 読み取り OK |
| create_task | ✗ | `"Project is locked..."` エラー |
| update_task | ✗ | `"Project is locked..."` エラー |
| delete_task | ✗ | `"Project is locked..."` エラー |
| create_document | ✗ | ドキュメント作成禁止 |
| update_document | ✗ | ドキュメント編集禁止 |
| update_project | ○ | プロジェクト設定は変更可能 |

**用途**: 完了済みプロジェクト、本番環境でのアクシデント防止

---

## データモデル

```json
Project {
  "id": ObjectId,
  "name": string,
  "description": string,
  "color": string (hex),
  "status": enum ("active", "archived"),
  "is_locked": boolean,
  "created_by": User,
  "created_at": datetime,
  "updated_at": datetime,
  "members": [
    {
      "user_id": ObjectId,
      "user": User,
      "role": enum ("owner", "editor", "viewer")
    }
  ]
}
```

---

**ツール総数**: 6 / 6

**最終更新**: 2025-04-15
