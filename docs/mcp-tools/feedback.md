# API フィードバックツール仕様書

`backend/app/mcp/tools/feedback.py` のフィードバック関連ツール（全2関数）を記載します。

## 概要

MCPツール改善リクエストを作業中に直接送信できます。ツール設計の問題・不足なパラメータ・パフォーマンス問題などを記録し、admin が後で集計・優先付けできます。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `request_api_improvement` | 改善リクエスト提出 |
| `list_api_feedback` | フィードバック一覧（管理者向け） |

**合計: 2 ツール関数**

---

## request_api_improvement

**概要**: MCPツール改善リクエスト提出

**シグネチャ**:
```python
async def request_api_improvement(
    tool_name: str,
    request_type: str,
    description: str,
    related_tools: list[str] | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `tool_name` | str | ○ | — | 対象ツール名（例: `"list_tasks"`, `"search_tasks"`） |
| `request_type` | str | ○ | — | リクエスト種別（下表参照） |
| `description` | str | ○ | — | 改善リクエストの具体的説明（最大 2,000 文字） |
| `related_tools` | list[str] | — | None | 関連ツール（merge/split 時に必須） |

**request_type の値**:

| 値 | 意味 | related_tools | 使用例 |
|----|------|-----------------|--------|
| `missing_param` | パラメータ不足 | 不要 | `"list_tasks に archived=null オプション追加"` |
| `merge` | 複数ツール統合 | **必須** | `"get_task と get_subtasks を 1 ツールに"` |
| `split` | 1 ツール分割 | **必須** | `"search_tasks を full-text と regex で分割"` |
| `deprecate` | ツール削除・deprecated | 不要 | `"list_review_tasks は list_tasks(needs_detail=true) で十分"` |
| `bug` | バグ報告 | 不要 | `"完了済みタスクが search_tasks で出現"` |
| `performance` | パフォーマンス問題 | 不要 | `"search_tasks で大規模プロジェクト遅い"` |
| `other` | その他 | 不要 | — |

**バリデーション**:
- tool_name: 空でない
- request_type: enum チェック
- description: 空でなく、最大 2,000 文字
- merge/split 時、related_tools は必須・空でない

**副作用**:
- DB に McpApiFeedback ドキュメント挿入
- status = `"open"` で初期化

**戻り値** (dict):
```json
{
  "id": "...",
  "tool_name": "list_tasks",
  "request_type": "missing_param",
  "description": "...",
  "related_tools": [],
  "status": "open",
  "created_at": "2025-04-15T10:00:00+00:00",
  "message": "Improvement request submitted successfully."
}
```

**WHEN TO USE**:
- ツール使用中に「このパラメータがあればな...」と感じた
- 複数ツール呼び出しが常にセット（merge 候補）
- ツール呼び出しが遅い
- ツール A と B の役割が重複

**注意**: 現在のタスク を中断する必要はありません。操作完了後に提出。

**使用例**:
```python
await request_api_improvement(
    tool_name="list_tasks",
    request_type="missing_param",
    description="フィルタ options に hide_archived=true を追加してほしい。"
                "デフォルトで archived=false なので、全件表示時に毎回 archived=null を指定するのが手間"
)
```

---

## list_api_feedback

**概要**: フィードバック一覧（admin による確認・管理用）

**シグネチャ**:
```python
async def list_api_feedback(
    tool_name: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `tool_name` | str | — | None | ツール名でフィルタ |
| `status` | str | — | None | ステータスでフィルタ: `open`, `accepted`, `rejected`, `done` |
| `request_type` | str | — | None | リクエスト種別でフィルタ |
| `limit` | int | — | 20 | 最大返却件数（max 100） |
| `skip` | int | — | 0 | スキップ件数 |

**戻り値** (dict):
```json
{
  "total": 15,
  "items": [
    {
      "id": "...",
      "tool_name": "list_tasks",
      "request_type": "missing_param",
      "description": "...",
      "related_tools": [],
      "status": "open",
      "votes": 2,
      "submitted_by": "mcp:my-key",
      "created_at": "2025-04-15T10:00:00+00:00"
    }
  ]
}
```

**フィルタ動作**: AND 条件で絞り込み

**WHEN TO USE**:
- admin が定期的にフィードバック確認
- 特定ツール・リクエストタイプの改善提案を集約
- 最も投票されたリクエストを確認（votes でソート可能）

---

## フィードバック管理フロー

```
1. 開発中 → request_api_improvement() で改善提案
2. admin 定期確認 → list_api_feedback(status="open")
3. 実装検討 → status を accepted に更新
4. 実装完了 → status を done に更新、新ツール/パラメータリリース
5. ユーザー → 改善後のツール利用
```

---

## ステータス遷移

```
open → accepted → done
  ↓
  rejected
```

- **open**: 新規リクエスト（デフォルト）
- **accepted**: admin が実装予定と判定
- **done**: リリース済み
- **rejected**: 実装不可または優先度低

---

**ツール総数**: 2 / 2

**最終更新**: 2025-04-15
