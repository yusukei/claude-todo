"""API key authentication for MCP tools.

Validates X-API-Key header directly against the database.
"""

import logging
import time

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request

from ..core.security import hash_api_key
from ..models import McpApiKey

logger = logging.getLogger(__name__)

# Auth cache: sha256(api_key) -> (result_dict, expiry_timestamp)
_auth_cache: dict[str, tuple[dict, float]] = {}
AUTH_CACHE_TTL = 300  # 5 minutes


class McpAuthError(ToolError):
    pass


async def authenticate() -> dict:
    """Validate the X-API-Key header and return key info.

    Returns:
        {"key_id": str, "project_scopes": list[str]}
    """
    try:
        request = get_http_request()
    except RuntimeError:
        raise McpAuthError("HTTP request context unavailable")

    api_key = request.headers.get("x-api-key")
    if not api_key:
        raise McpAuthError("X-API-Key header required")

    cache_key = hash_api_key(api_key)

    # Check cache
    cached = _auth_cache.get(cache_key)
    if cached is not None:
        result, expiry = cached
        if time.monotonic() < expiry:
            return result
        del _auth_cache[cache_key]

    # Query DB directly
    api_key_doc = await McpApiKey.find_one(
        McpApiKey.key_hash == cache_key, McpApiKey.is_active == True  # noqa: E712
    )
    if not api_key_doc:
        raise McpAuthError("Invalid API key")

    # Update last_used_at (throttled to once per 60s)
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    last_used = api_key_doc.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=UTC)
    if last_used is None or (now - last_used).total_seconds() > 60:
        api_key_doc.last_used_at = now
        await api_key_doc.save()

    result = {
        "key_id": str(api_key_doc.id),
        "project_scopes": api_key_doc.project_scopes,
    }
    _auth_cache[cache_key] = (result, time.monotonic() + AUTH_CACHE_TTL)
    return result


def check_project_access(project_id: str, scopes: list[str]) -> None:
    """Check project access. Empty scopes list means full access to all projects."""
    if scopes and project_id not in scopes:
        raise McpAuthError(f"No access to project {project_id}")
