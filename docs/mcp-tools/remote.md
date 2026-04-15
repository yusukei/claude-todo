# リモート操作ツール仕様書

`backend/app/mcp/tools/remote.py` のリモートコマンド実行・ファイル操作ツール（全15関数）を記載します。

## 概要

GitHub Actions / SSH トンネル経由でリモートマシンのコマンド実行・ファイル操作を実行します。秘密注入、監査ログ、リトライ機能を備えています。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `list_remote_agents` | リモートエージェント一覧 |
| `remote_exec` | コマンド実行（シェル） |
| `remote_read_file` | ファイル読み込み |
| `remote_write_file` | ファイル作成・上書き |
| `remote_edit_file` | ファイル編集（find & replace） |
| `remote_list_dir` | ディレクトリ一覧 |
| `remote_stat` | ファイル情報取得 |
| `remote_file_exists` | ファイル存在確認 |
| `remote_mkdir` | ディレクトリ作成 |
| `remote_delete_file` | ファイル削除 |
| `remote_move_file` | ファイル移動・リネーム |
| `remote_copy_file` | ファイル複製 |
| `remote_glob` | パターンマッチでファイル検索 |
| `remote_grep` | grep 検索 |

**合計: 14 ツール関数**

---

## コマンド実行

### remote_exec

**概要**: リモートコマンド実行

**シグネチャ**:
```python
async def remote_exec(
    project_id: str,
    command: str,
    cwd: str | None = None,
    timeout: int = 30,
    inject_secrets: bool = False,
    env: dict[str, str] | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `command` | str | ○ | — | 実行するコマンド（bash） |
| `cwd` | str | — | None | ワーキングディレクトリ |
| `timeout` | int | — | 30 | タイムアウト（秒） |
| `inject_secrets` | bool | — | False | **True で環境変数にシークレット自動注入** |
| `env` | dict | — | None | 環境変数追加（秘密値は避ける） |

**inject_secrets = True の動作**:
- プロジェクトの全シークレット (set_secret で登録) を環境変数として注入
- 秘密値をコマンドラインに expose しない
- 監査ログには環境変数 key のみ記録（値は非記録）

**戻り値** (dict):
```json
{
  "success": true,
  "exit_code": 0,
  "stdout": "command output...",
  "stderr": "",
  "duration_seconds": 1.23
}
```

**エラー**:
- `exit_code != 0` でも dict 返却（stderr 含む）
- タイムアウト → `ToolError`
- リモートエージェント接続失敗 → `ToolError`

**WHEN TO USE**:
- npm install, make build, docker compose up
- デプロイ・テスト実行
- データベース migration

**セキュリティ推奨**:
```python
# 推奨
await remote_exec(
    project_id="...",
    command="curl -H 'Authorization: Bearer $DB_TOKEN' ...",
    inject_secrets=True  # DB_TOKEN は環境変数から取得
)

# 非推奨（秘密値が stdout に出力される可能性）
await remote_exec(
    project_id="...",
    command="curl -H 'Authorization: Bearer my-secret-token' ..."
)
```

---

## ファイル操作

### remote_read_file

**概要**: ファイル読み込み

**シグネチャ**:
```python
async def remote_read_file(
    project_id: str,
    path: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "path": "path/to/file",
  "content": "file contents",
  "size_bytes": 1024
}
```

---

### remote_write_file

**概要**: ファイル作成・上書き

**シグネチャ**:
```python
async def remote_write_file(
    project_id: str,
    path: str,
    content: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "path": "...",
  "size_bytes": 1024,
  "message": "File written successfully"
}
```

---

### remote_edit_file

**概要**: ファイル編集（find & replace）

**シグネチャ**:
```python
async def remote_edit_file(
    project_id: str,
    path: str,
    find: str,
    replace: str,
) -> dict
```

**動作**:
- `find` にマッチする最初の部分を `replace` に置換
- 複数マッチの場合は最初の 1 つのみ

---

### remote_list_dir

**概要**: ディレクトリ一覧

**シグネチャ**:
```python
async def remote_list_dir(
    project_id: str,
    path: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "path": "path/to/dir",
  "items": [
    {
      "name": "file.txt",
      "type": "file",
      "size_bytes": 1024,
      "modified_at": "2025-04-15T10:00:00+00:00"
    },
    {
      "name": "subdir",
      "type": "directory"
    }
  ]
}
```

---

### remote_stat

**概要**: ファイル情報取得

**シグネチャ**:
```python
async def remote_stat(
    project_id: str,
    path: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "path": "...",
  "type": "file" | "directory",
  "size_bytes": 1024,
  "permissions": "644",
  "modified_at": "2025-04-15T10:00:00+00:00",
  "created_at": "..."
}
```

---

### remote_file_exists

**概要**: ファイル存在確認

**シグネチャ**:
```python
async def remote_file_exists(
    project_id: str,
    path: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "exists": true | false,
  "path": "..."
}
```

---

### remote_mkdir

**概要**: ディレクトリ作成

**シグネチャ**:
```python
async def remote_mkdir(
    project_id: str,
    path: str,
    parents: bool = True,
) -> dict
```

**パラメータ**:
- `parents`: True なら親ディレクトリも自動作成（mkdir -p）

---

### remote_delete_file

**概要**: ファイル削除

**シグネチャ**:
```python
async def remote_delete_file(
    project_id: str,
    path: str,
) -> dict
```

---

### remote_move_file

**概要**: ファイル移動・リネーム

**シグネチャ**:
```python
async def remote_move_file(
    project_id: str,
    src: str,
    dest: str,
) -> dict
```

---

### remote_copy_file

**概要**: ファイル複製

**シグネチャ**:
```python
async def remote_copy_file(
    project_id: str,
    src: str,
    dest: str,
) -> dict
```

---

## 検索操作

### remote_glob

**概要**: パターンマッチでファイル検索

**シグネチャ**:
```python
async def remote_glob(
    project_id: str,
    pattern: str,
    cwd: str | None = None,
) -> dict
```

**パラメータ**:
- `pattern`: glob パターン（例: `"*.py"`, `"src/**/*.ts"`）
- `cwd`: 検索開始ディレクトリ

**戻り値** (dict):
```json
{
  "pattern": "*.py",
  "cwd": "src",
  "results": [
    "src/main.py",
    "src/utils.py"
  ],
  "total": 2
}
```

---

### remote_grep

**概要**: grep 検索

**シグネチャ**:
```python
async def remote_grep(
    project_id: str,
    pattern: str,
    path: str,
    recursive: bool = False,
    ignore_case: bool = False,
) -> dict
```

**パラメータ**:
- `pattern`: 正規表現パターン
- `path`: 検索対象ファイル or ディレクトリ
- `recursive`: True なら再帰検索
- `ignore_case`: True なら大文字小文字を区別しない

**戻り値** (dict):
```json
{
  "pattern": "TODO",
  "results": [
    {
      "file": "src/main.py",
      "line_number": 42,
      "line": "  # TODO: implement this"
    }
  ],
  "total": 1
}
```

---

## エージェント管理

### list_remote_agents

**概要**: リモートエージェント一覧

**シグネチャ**:
```python
async def list_remote_agents() -> list[dict]
```

**戻り値** (list):
```json
[
  {
    "id": "...",
    "name": "prod-github-actions",
    "binding": "github_actions",
    "transport": "ssh",
    "status": "connected" | "disconnected",
    "last_heartbeat": "2025-04-15T10:00:00+00:00"
  }
]
```

---

## 監査ログ

すべてのリモート操作は監査ログに記録：

```
{
  "operation": "remote_exec",
  "project_id": "...",
  "command": "npm install",  # grep/find は mask される
  "executed_by": "mcp:my-key",
  "executed_at": "...",
  "exit_code": 0,
  "duration_seconds": 12.3,
  "denied": false
}
```

秘密値は ログに露出しない。

---

## 使用パターン

### ビルド・デプロイ

```python
# 1. リポジトリ clone / pull
await remote_exec(
    project_id="...",
    command="git clone ... || git pull"
)

# 2. 依存インストール
await remote_exec(
    project_id="...",
    command="npm install",
    cwd="frontend"
)

# 3. ビルド
await remote_exec(
    project_id="...",
    command="npm run build",
    cwd="frontend"
)

# 4. デプロイ（秘密注入）
await remote_exec(
    project_id="...",
    command="docker push $REGISTRY_TOKEN",
    inject_secrets=True
)
```

### ファイル検索→読み込み

```
1. remote_glob(project_id, "src/**/*.py") → ファイル一覧
2. remote_read_file(project_id, "src/main.py") → コンテンツ確認
3. remote_edit_file(...) で修正
```

---

## エラーハンドリング

```python
result = await remote_exec(project_id="...", command="...")

if result["exit_code"] == 0:
    # 成功
    print(result["stdout"])
else:
    # 失敗
    print(f"Error: {result['stderr']}")
```

---

**ツール総数**: 14 / 14

**最終更新**: 2025-04-15
