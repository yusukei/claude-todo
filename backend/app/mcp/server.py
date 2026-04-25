"""MCP Todo Server 定義

FastMCP サーバインスタンスを作成し、各ツールモジュールを登録する。
OAuth 2.1 (TodoOAuthProvider) による認証をサポートし、
MCP Todo ユーザーと OAuth トークンを紐付ける。
"""

import logging

from fastmcp import FastMCP
from mcp.server.auth.settings import ClientRegistrationOptions

from ..core.config import settings
from .oauth import TodoOAuthProvider

logger = logging.getLogger(__name__)

MOUNT_PREFIX = "/mcp"
MCP_PATH = "/"

# OAuth プロバイダの構築
# base_url にマウントプレフィックスを含める（FastMCP の規約）
_base = settings.BASE_URL.rstrip("/") if settings.BASE_URL else "http://localhost:8000"
_base_url = f"{_base}{MOUNT_PREFIX}"

if not settings.BASE_URL:
    logger.warning(
        "BASE_URL is not set — OAuth URLs will use %s. "
        "Set BASE_URL to the public HTTPS URL for production.",
        _base_url,
    )
else:
    logger.info("MCP OAuth base_url: %s", _base_url)

_oauth_provider = TodoOAuthProvider(
    base_url=_base_url,
    client_registration_options=ClientRegistrationOptions(
        enabled=True,
    ),
)

mcp = FastMCP(
    name="McpTodo",
    instructions=(
        "MCP Todo is a task management system. "
        "Authenticate with the X-API-Key header. "
        "Rate limits: 120 requests/minute per IP. "
        "Field limits: title max 255 chars, description max 10000 chars, comment max 10000 chars.\n\n"
        "## Task lifecycle\n"
        "Tasks follow this workflow:\n"
        "1. Created (status=todo) → may have needs_detail=true if the task needs investigation\n"
        "2. Investigation complete → user decides: approved=true (proceed) or cancel/archive (skip)\n"
        "3. approved=true → ready for implementation (status=in_progress → done)\n\n"
        "## needs_detail flag workflow\n"
        "needs_detail=true means the user cannot yet decide whether or how to address the task. "
        "When asked to handle needs_detail tasks:\n"
        "1. Investigate WHY the task was created (background, context, root cause)\n"
        "2. Present multiple options/approaches if applicable\n"
        "3. Describe trade-offs for each option (cost, risk, complexity, impact)\n"
        "4. Record findings as a comment (via add_comment) to preserve the original description\n"
        "5. Do NOT start implementation — wait for the user's decision\n"
        "After the user reviews, they will either:\n"
        "- Approve: set approved=true (automatically clears needs_detail)\n"
        "- Reject: cancel or archive the task\n\n"
        "## Knowledge base\n"
        "Cross-project reusable technical know-how. "
        "Search knowledge first (search_knowledge) before researching from scratch. "
        "Save non-obvious solutions or patterns via create_knowledge.\n\n"
        "## Project documents\n"
        "Documents are the authoritative source for project specifications — "
        "read relevant documents before starting implementation. "
        "Documents are versioned automatically on each update_document call. "
        "Pass task_id when updating to link changes to the task. "
        "Content supports Markdown with Mermaid diagrams (```mermaid blocks).\n\n"
        "## Bookmarks\n"
        "create_bookmark saves a URL and triggers background web clipping "
        "(Playwright extracts article content as Markdown + thumbnail). "
        "Use clip_bookmark to re-trigger clipping.\n\n"
        "## Project secrets\n"
        "Encrypted secrets with audited access. "
        "Prefer inject_secrets=True on remote_exec over calling get_secret — "
        "this avoids exposing secret values in the conversation.\n\n"
        "## Onboarding\n"
        "When a user asks to set up mcp-todo for their project, "
        "call get_setup_guide to get the recommended CLAUDE.md snippet, "
        "then write it to the project's CLAUDE.md (create if needed). "
        "Prerequisite: .mcp.json is already configured manually by the user.\n\n"
        "## API feedback\n"
        "When you notice an MCP tool limitation during work, "
        "use request_api_improvement to record it. Examples:\n"
        "- A missing parameter that would have avoided a multi-step workaround\n"
        "- Two tools that are always called together and could be merged\n"
        "- A tool that is unexpectedly slow or returns an unhelpful error\n"
        "- A tool that could be deprecated because another tool covers its use case\n"
        "Do not interrupt the current task — submit after completing "
        "the operation that revealed the limitation. "
        "Use list_api_feedback to check for existing requests before submitting duplicates."
    ),
    auth=_oauth_provider,
)


def register_tools() -> None:
    from .middleware import UsageTrackingMiddleware
    from .tools import bookmarks, documents, docsites, error_tracker, feedback, knowledge, projects, remote, secrets, setup, supervisor, tasks  # noqa: F401

    # Install usage-tracking middleware once. Hot path is fire-and-forget,
    # so even if Mongo briefly stalls the tool call itself is unaffected.
    mcp.add_middleware(UsageTrackingMiddleware())
