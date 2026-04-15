# セットアップツール仕様書

`backend/app/mcp/tools/setup.py` のセットアップ関連ツール（全1関数）を記載します。

## ツール一覧

| ツール | 用途 |
|--------|------|
| `get_setup_guide` | CLAUDE.md スニペット生成 |

**合計: 1 ツール関数**

---

## get_setup_guide

**概要**: mcp-todo 導入時の CLAUDE.md テンプレート取得

**シグネチャ**:
```python
async def get_setup_guide(
    server_url: str = "https://todo.vtech-studios.com",
) -> dict
```

**パラメータ**:

| 名前 | 型 | 必須 | デフォルト | 説明 |
|-----|---|----|---------|------|
| `server_url` | str | — | `"https://todo.vtech-studios.com"` | mcp-todo サーバ URL |

**前提条件**:
- `.mcp.json` がプロジェクトディレクトリに存在
- `.mcp.json` に server_url と API キー を記載済み
- MCP 接続確立済み（このツールはその後に呼び出す）

**戻り値** (dict):
```json
{
  "claude_md_snippet": "## Task Management (required)\n\n..."
}
```

**返却内容** (claude_md_snippet):

```markdown
## Task Management (required)
- **Always use the mcp-todo MCP server for task management** (use MCP tools, NOT TodoWrite)
- See MCP server instructions for tool usage details (task lifecycle, knowledge base, documents, etc.)

### Session start workflow (recommended)
When no specific instructions are given at session start, call `get_work_context` to check current status:
- **approved**: Approved tasks ready for implementation
- **in_progress**: Tasks currently in progress
- **overdue**: Overdue tasks
- **needs_detail**: Tasks requiring investigation

Use `get_task_context` when you need detailed context for a task 
(combines get_task + get_subtasks + get_task_activity into a single call).

### When MCP connection is unavailable (required)
If mcp-todo MCP server tools are not available at session start:
1. Check `.mcp.json` configuration (verify URL and API key)
2. Check server status (`curl -s {server_url}/health`)
3. If unresolved, suggest the user restart the session
4. **Never fall back to TodoWrite or other alternatives — fix the connection**

## Development Workflow
Before modifying code or configuration files:
1. **Task first** — Ensure a task exists via `create_task` (exception: trivial typo/formatting fixes)
2. **Docs first** — Search project documents (`search_documents`) and update relevant specs BEFORE implementation
3. **Implement** — Follow the updated specs; record significant decisions as task comments
4. **Test** — Run the test suite and verify all tests pass
5. **Spec review** — Compare the diff against project documents; fix discrepancies before completing
6. **Complete** — Mark the task done via `complete_task` with a completion report

## Git
- Include the task ID in commit messages for traceability (e.g., `feat: add versioning [task:69c22641]`)
```

**WHEN TO USE**:
- プロジェクトに mcp-todo を導入する際
- CLAUDE.md を新規作成する際

**使用フロー**:
```
1. get_setup_guide() を呼び出し
2. 返却された claude_md_snippet をプロジェクトの CLAUDE.md に追記
3. CLAUDE.md をコミット
4. 以降、このプロジェクトのセッションでは mcp-todo ツール利用可能
```

**注意**: このツール自体は認証チェック（authenticate）を実施していないため、`X-API-Key` ヘッダがなくても動作します。ただし、実運用では MCP 接続が確立していることが前提です。

---

**ツール総数**: 1 / 1

**最終更新**: 2025-04-15
