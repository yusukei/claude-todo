from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..models import McpApiKey, User
from .security import decode_access_token, hash_api_key

bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_user_from_api_key(api_key: str) -> User | None:
    """Resolve an ``X-API-Key`` header value to the owning ``User``.

    Returns ``None`` when the key is unknown, inactive, orphaned, or when
    the owner is disabled — the caller is responsible for turning that
    into a 401/403 consistent with the rest of the endpoint's auth.
    """
    if not api_key:
        return None
    doc = await McpApiKey.find_one(
        McpApiKey.key_hash == hash_api_key(api_key),
        McpApiKey.is_active == True,  # noqa: E712
    )
    if not doc or not doc.created_by:
        return None
    owner = await User.get(doc.created_by.ref.id)
    if not owner or not owner.is_active:
        return None
    # Cheap throttled bookkeeping so the admin UI still shows recent
    # usage (every 60s is plenty — we're not building an SLA here).
    now = datetime.now(UTC)
    last_used = doc.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=UTC)
    if last_used is None or (now - last_used).total_seconds() > 60:
        doc.last_used_at = now
        await doc.save()
    return owner


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    # 1. Try Bearer token from Authorization header (existing behavior)
    token: str | None = credentials.credentials if credentials else None

    # 2. Fall back to HttpOnly cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await User.get(payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_user_flexible(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """Authenticate via JWT (Bearer/cookie) **or** ``X-API-Key`` header.

    Parallels :func:`get_current_user` but accepts an MCP API key as a
    fallback so automation (CLIs, CI, agent release uploaders) doesn't
    need a browser login. The resolved ``User`` is the key's ``created_by``
    owner — permission decisions downstream use that user's scopes.
    """
    # Prefer the interactive (JWT) path when available so cookie-based
    # admin sessions keep behaving exactly as before.
    token: str | None = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get("access_token")
    if token:
        payload = decode_access_token(token)
        if payload:
            user = await User.get(payload["sub"])
            if user and user.is_active:
                return user

    api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if api_key:
        user = await _resolve_user_from_api_key(api_key)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


async def get_admin_user_flexible(
    user: User = Depends(get_current_user_flexible),
) -> User:
    """Admin check that also accepts an admin-owner's X-API-Key.

    Use this on operator endpoints (agent release upload, config
    reload, …) so scripts can run unattended without a browser login.
    The key still has to belong to an admin user — non-admin keys get
    the same 403 as non-admin sessions.
    """
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
