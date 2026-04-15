# シークレット管理ツール仕様書

`backend/app/mcp/tools/secrets.py` のシークレット関連ツール（全3関数）を記載します。

## 概要

プロジェクト内の暗号化シークレット（API キー、トークン等）を安全に管理。すべてアクセスが監査ログに記録されます。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `list_secrets` | シークレット一覧（キーのみ） |
| `set_secret` | シークレット設定・更新 |
| `get_secret` | シークレット値取得 |
| `delete_secret` | シークレット削除 |

**合計: 4 ツール関数**

---

## CRUD

### set_secret

**概要**: シークレット設定・更新

**シグネチャ**:
```python
async def set_secret(
    project_id: str,
    key: str,
    value: str,
    description: str = "",
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `project_id` | str | ○ | — | プロジェクト ID または名前 |
| `key` | str | ○ | — | シークレット キー（英数字・アンダースコアのみ） |
| `value` | str | ○ | — | シークレット値（暗号化保存） |
| `description` | str | — | `""` | 説明（用途等） |

**バリデーション**:
- key: `[a-zA-Z0-9_]+` マッチ（先頭は英数字）

**副作用**:
- 暗号化して DB に保存
- 監査ログに記録（who accessed when）

**戻り値** (dict):
```json
{
  "key": "API_KEY",
  "project_id": "...",
  "description": "...",
  "updated_at": "...",
  "message": "Secret set successfully"
}
```

**注意**: 値そのものは返さない（監査ログにも露出させない）

---

### get_secret

**概要**: シークレット値取得

**シグネチャ**:
```python
async def get_secret(
    project_id: str,
    key: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "key": "API_KEY",
  "value": "abc123...",
  "description": "..."
}
```

**副作用**:
- 監査ログに「誰が」「いつ」「何を」 access した記録

**WHEN TO USE**:
- リモートコマンド実行時、環境変数に注入（`inject_secrets=true`）
- スクリプトに秘密値が必要な場合

**セキュリティ推奨**:
- 秘密値を会話に出さない
- 可能なら `remote_exec(inject_secrets=true)` で自動注入

---

### list_secrets

**概要**: シークレット一覧（キーと説明のみ）

**シグネチャ**:
```python
async def list_secrets(
    project_id: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "items": [
    {
      "key": "API_KEY",
      "description": "...",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "total": 3
}
```

**注意**: 値は含まれない（一覧表示は safe）

---

### delete_secret

**概要**: シークレット削除

**シグネチャ**:
```python
async def delete_secret(
    project_id: str,
    key: str,
) -> dict
```

**戻り値** (dict):
```json
{
  "success": true,
  "key": "API_KEY"
}
```

---

## 監査ログ

すべてのシークレット access はログに記録：

```
{
  "action": "get_secret" | "set_secret" | "delete_secret",
  "project_id": "...",
  "key": "API_KEY",
  "accessed_by": "mcp:my-key",
  "accessed_at": "2025-04-15T10:00:00+00:00",
  "success": true|false
}
```

Admin は監査ログを確認して、不正 access を検出可能。

---

## 使用パターン

### リモートコマンド実行（秘密注入）

```python
# 推奨: inject_secrets=true
await remote_exec(
    project_id="...",
    command="curl -H 'Authorization: Bearer $API_KEY' ...",
    inject_secrets=True  # 環境変数 API_KEY に自動注入
)

# 非推奨: get_secret で手動
secret = await get_secret(project_id="...", key="API_KEY")
# 秘密値が会話に露出 ← 避けるべき
```

---

## セキュリティ

- **暗号化**: Fernet（AES-128） で対称暗号化
- **キー管理**: `ENCRYPTION_KEY` 環境変数で管理
- **監査**: すべての access を ログに記録
- **アクセス制限**: プロジェクトオーナーのみ

---

**ツール総数**: 4 / 4

**最終更新**: 2025-04-15
