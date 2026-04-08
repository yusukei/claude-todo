"""Shared auth helpers: rate limiting, refresh-token JTI bookkeeping, common schemas.

All submodules (`jwt`, `google`, `webauthn`) funnel through this module for
refresh-token creation and login throttling. The module-level ``get_redis``
binding is intentional: tests monkeypatch ``endpoints.auth._shared.get_redis``
to inject fakeredis, and the rate-limit helpers look it up dynamically via
the module's global scope so patches flow through.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from pydantic import BaseModel

from .....core.config import settings
from .....core.redis import get_redis
from .....core.security import create_refresh_token

# Sourced from settings so deployments can tune them via env vars
# (LOGIN_MAX_ATTEMPTS / LOGIN_LOCKOUT_SECONDS). Module-level aliases
# are kept so tests can monkeypatch the constants directly.
_LOGIN_MAX_ATTEMPTS = settings.LOGIN_MAX_ATTEMPTS
_LOGIN_LOCKOUT_SECONDS = settings.LOGIN_LOCKOUT_SECONDS
_REFRESH_JTI_TTL = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400  # seconds
_OAUTH_STATE_TTL = 600  # 10 minutes


# ── Response schemas shared across submodules ───────────────


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ── Refresh-token JTI helpers ────────────────────────────────


async def _store_refresh_jti(jti: str) -> None:
    """Store a refresh token JTI in Redis so it can be validated later."""
    redis = get_redis()
    await redis.set(f"refresh_jti:{jti}", "valid", ex=_REFRESH_JTI_TTL)


async def _validate_and_revoke_jti(jti: str | None) -> bool:
    """Validate a JTI exists in Redis and delete it (one-time use).

    Returns True only if the token carries a JTI and it was present in
    Redis (and thus had not been used yet). Tokens without a JTI are
    rejected — every refresh token we issue via ``create_refresh_token``
    always carries one, so a missing JTI means a forged or corrupt token.
    """
    if jti is None:
        return False
    redis = get_redis()
    result = await redis.delete(f"refresh_jti:{jti}")
    return result > 0


async def _create_and_store_refresh_token(subject: str) -> str:
    """Create a refresh token and store its JTI in Redis."""
    token, jti = create_refresh_token(subject)
    await _store_refresh_jti(jti)
    return token


# ── Rate limiting helpers ────────────────────────────────────


async def _check_rate_limit(email: str) -> None:
    redis = get_redis()
    key = f"login_attempts:{email}"
    attempts = await redis.get(key)
    if attempts and int(attempts) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )


async def _record_failed_login(email: str) -> None:
    redis = get_redis()
    key = f"login_attempts:{email}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, _LOGIN_LOCKOUT_SECONDS)
    await pipe.execute()


async def _clear_login_attempts(email: str) -> None:
    redis = get_redis()
    await redis.delete(f"login_attempts:{email}")
