"""Auth endpoints package.

Splits the former 548-line ``auth.py`` into 4 submodules by auth scheme:
- ``_shared``  — rate limiting, refresh-token JTI helpers, TokenResponse
- ``jwt``      — /login, /refresh, /me, /logout
- ``google``   — /google, /google/callback (OAuth 2.0)
- ``webauthn`` — /webauthn/* (passkey registration, authentication, management)

The underscore-prefixed helpers and constants (``_check_rate_limit``,
``_record_failed_login``, ``_clear_login_attempts``, ``_LOGIN_MAX_ATTEMPTS``,
``_LOGIN_LOCKOUT_SECONDS``) are re-exported at the package level so the
unit tests in ``tests/unit/test_rate_limit.py`` can import them unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter

from . import _shared
from ._shared import (
    _LOGIN_LOCKOUT_SECONDS,
    _LOGIN_MAX_ATTEMPTS,
    _check_rate_limit,
    _clear_login_attempts,
    _create_and_store_refresh_token,
    _record_failed_login,
    _store_refresh_jti,
    _validate_and_revoke_jti,
)
from .google import router as _google_router
from .jwt import router as _jwt_router
from .webauthn import router as _webauthn_router

router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(_jwt_router)
router.include_router(_google_router)
router.include_router(_webauthn_router)

__all__ = [
    "router",
    "_check_rate_limit",
    "_record_failed_login",
    "_clear_login_attempts",
    "_store_refresh_jti",
    "_validate_and_revoke_jti",
    "_create_and_store_refresh_token",
    "_LOGIN_MAX_ATTEMPTS",
    "_LOGIN_LOCKOUT_SECONDS",
]
