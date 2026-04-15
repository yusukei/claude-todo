# ナレッジベースツール仕様書

`backend/app/mcp/tools/knowledge.py` のナレッジ関連ツール（全6関数）を記載します。

## 概要

ナレッジベースは**クロスプロジェクト**の技術ナレッジを保存・検索するシステムです。特定プロジェクトに属さず、すべての MCP クライアントからアクセス可能な共有知識ベースです。

タスク説明を汚さないまま、暗黙的な解決策やベストプラクティスを記録・再利用できます。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `create_knowledge` | ナレッジ記事作成 |
| `search_knowledge` | キーワード検索（Tantivy + MongoDB） |
| `get_knowledge` | 記事詳細取得 |
| `update_knowledge` | 記事編集 |
| `delete_knowledge` | 記事削除（soft delete） |
| `list_knowledge` | カテゴリ・タグでフィルタして一覧 |

**合計: 6 ツール関数**

---

## CRUD 系

### create_knowledge

**概要**: ナレッジ記事作成

**シグネチャ**:
```python
async def create_knowledge(
    title: str,
    content: str,
    tags: list[str] | None = None,
    category: str = "reference",
    source: str | None = None,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `title` | str | ○ | — | 記事タイトル（最大 255 文字） |
| `content` | str | ○ | — | 記事本文（Markdown 対応、最大 50,000 文字） |
| `tags` | list[str] | — | None | 検索用タグ（例: ["tantivy", "search", "japanese"]） |
| `category` | str | — | `"reference"` | カテゴリ: `recipe`, `reference`, `tip`, `troubleshooting`, `architecture` |
| `source` | str | — | None | 出典（URL、ファイルパス、参考文献等） |

**カテゴリの意味**:
- **recipe**: 手順書・チュートリアル
- **reference**: API リファレンス、データモデル説明
- **tip**: ワンライナー、小ネタ
- **troubleshooting**: よくある問題と解決法
- **architecture**: システム設計パターン

**バリデーション**:
- title: 最大 255 文字
- content: 最大 50,000 文字
- category: enum チェック

**副作用**:
- DB に Knowledge 挿入
- Tantivy インデックスに追加
- tags は自動で小文字正規化

**戻り値** (dict):
```json
{
  "id": "...",
  "title": "...",
  "content": "...",
  "tags": [...],
  "category": "reference",
  "source": "...",
  "created_by": "mcp:my-key",
  "created_at": "2025-04-15T10:00:00+00:00",
  "updated_at": "2025-04-15T10:00:00+00:00",
  "is_deleted": false
}
```

**WHEN TO USE**:
- 実装中に発見した暗黙的な解決策
- プロジェクト横断的なベストプラクティス
- リファレンス情報（API 仕様等）

---

### get_knowledge

**概要**: ナレッジ記事詳細取得

**シグネチャ**:
```python
async def get_knowledge(knowledge_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `knowledge_id` | str | ○ | — | ナレッジ記事 ID |

**戻り値** (dict): create_knowledge と同じ構造

**エラー**:
- `"Knowledge entry not found: {id}"`

---

### update_knowledge

**概要**: ナレッジ記事編集（指定フィール のみ更新）

**シグネチャ**:
```python
async def update_knowledge(
    knowledge_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    category: str | None = None,
    source: str | None = None,
) -> dict
```

**パラメータ**: create_knowledge と同じ（全て optional）

**特殊な点**:
- source に空文字列を pass すると None に設定（クリア）

**副作用**:
- updated_at 自動更新
- Tantivy インデックス再索引

**戻り値** (dict): 更新後の記事 dict

---

### delete_knowledge

**概要**: ナレッジ記事削除（soft delete）

**シグネチャ**:
```python
async def delete_knowledge(knowledge_id: str) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `knowledge_id` | str | ○ | — | ナレッジ記事 ID |

**戻り値** (dict):
```json
{
  "success": true,
  "knowledge_id": "..."
}
```

**副作用**:
- is_deleted → true
- Tantivy インデックスから削除

---

## 検索・一覧系

### search_knowledge

**概要**: キーワード検索（Tantivy + MongoDB $regex フォールバック）

**シグネチャ**:
```python
async def search_knowledge(
    query: str,
    category: str | None = None,
    tag: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `query` | str | ○ | — | 検索キーワード |
| `category` | str | — | None | カテゴリでフィルタ |
| `tag` | str | — | None | タグでフィルタ（1 つのタグのみ） |
| `limit` | int | — | 20 | 最大返却件数（max 100） |
| `skip` | int | — | 0 | スキップ件数 |

**検索対象** (Tantivy):
- title, content, tags

**フォールバック** (MongoDB):
- title, content, tags に対する $regex マッチング

**戻り値** (dict):
```json
{
  "items": [
    {
      "id": "...",
      "title": "...",
      "content": "...",
      "tags": [...],
      "category": "reference",
      "source": "...",
      "created_by": "...",
      "created_at": "...",
      "updated_at": "...",
      "_score": 0.95
    }
  ],
  "total": 5,
  "limit": 20,
  "skip": 0,
  "_meta": {
    "search_engine": "tantivy" or "regex"
  }
}
```

**_score**: Tantivy の関連度スコア（0-1）。regex 検索時は含まれない

**WHEN TO USE**:
- タスク実装前に、類似のナレッジがないか検索
- 特定カテゴリ・タグの記事を検索

---

### list_knowledge

**概要**: ナレッジ一覧（カテゴリ・タグフィルタ対応）

**シグネチャ**:
```python
async def list_knowledge(
    category: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    skip: int = 0,
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `category` | str | — | None | カテゴリフィルタ |
| `tag` | str | — | None | タグフィルタ |
| `limit` | int | — | 50 | 最大返却件数（max 100） |
| `skip` | int | — | 0 | スキップ件数 |

**ソート順**: updated_at（最新順）

**戻り値** (dict): search_knowledge と同じ（_score は無し）

**WHEN TO USE**:
- ブラウジング（カテゴリ別に読む）
- 特定タグの記事一覧

---

## ナレッジの活用例

### セッション開始時

```
1. タスク を見かけたら「これって以前解いたっけ?」と思い出す
2. search_knowledge(query=task_title_or_keyword)
3. ヒット → 既存ナレッジ活用
4. ノーヒット → 新規ナレッジ作成候補
```

### 実装中に解決法を発見

```
1. 実装完了後、create_knowledge(
     title="Tantivy で日本語全文検索",
     content="## 問題\n...\n## 解決法\n...",
     category="recipe",
     tags=["tantivy", "search", "japanese"]
   )
2. 同じ問題に直面した別プロジェクトで再利用可能
```

---

## カテゴリ・タグ設計ガイド

### カテゴリの使い分け

- **recipe**: `"How to setup Tantivy"`, `"Git rebase workflow"`
- **reference**: `"Task model fields"`, `"Redis Streams API"`
- **tip**: `"Use uv instead of pip"`, `"Debug asyncio with uvloop"`
- **troubleshooting**: `"Fix mongomock-motor connection error"`, `"Solve circular import"`
- **architecture**: `"Multi-worker sidecar topology"`, `"SSE session persistence"`

### タグ命名規則

- 小文字 + ハイフン（自動正規化）
- 例: `["search", "japanese-language", "tantivy-py-fork"]`
- 同じ概念に複数の表現がある場合、1 つの統一タグで集約（例: 「日本語検索」= `"japanese-search"`）

---

## データモデル

```json
Knowledge {
  "id": ObjectId,
  "title": string,
  "content": string (markdown),
  "tags": [string],
  "category": enum ("recipe", "reference", "tip", "troubleshooting", "architecture"),
  "source": string | null,
  "created_by": string,
  "created_at": datetime,
  "updated_at": datetime,
  "is_deleted": boolean
}
```

---

**ツール総数**: 6 / 6

**最終更新**: 2025-04-15
