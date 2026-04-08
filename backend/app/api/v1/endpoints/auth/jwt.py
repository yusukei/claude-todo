"""Password login + refresh token + session introspection + logout."""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from .....core.deps import get_current_user
from .....core.security import (
    clear_auth_cookies,
    create_access_token,
    decode_refresh_token,
    set_auth_cookies,
    verify_password,
)
from .....models import User
from .....models.user import AuthType
from ._shared import (
    TokenResponse,
    _check_rate_limit,
    _clear_login_attempts,
    _create_and_store_refresh_token,
    _record_failed_login,
    _validate_and_revoke_jti,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response) -> TokenResponse:
    await _check_rate_limit(body.username)
    user = await User.find_one(User.email == body.username, User.auth_type == AuthType.admin)
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        await _record_failed_login(body.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    if user.password_disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password login is disabled. Use passkey instead.",
        )

    await _clear_login_attempts(body.username)
    access_token = create_access_token(str(user.id))
    refresh_token = await _create_and_store_refresh_token(str(user.id))
    set_auth_cookies(response, access_token, refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    payload = decode_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Validate and revoke old JTI (one-time use)
    jti = payload.get("jti")
    if not await _validate_and_revoke_jti(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token already used")

    user = await User.get(payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(str(user.id))
    new_refresh_token = await _create_and_store_refresh_token(str(user.id))
    set_auth_cookies(response, access_token, new_refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "picture_url": user.picture_url,
        "auth_type": user.auth_type,
        "has_passkeys": len(user.webauthn_credentials) > 0,
        "password_disabled": user.password_disabled,
    }


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear auth cookies unconditionally.

    Intentionally not gated by ``get_current_user``: when the access
    token has already expired (or was never issued) the client still
    needs a way to wipe the residual cookies. Requiring auth here
    would force the SPA to handle a 401 by ignoring it, which in
    turn used to drive an interceptor loop where /logout's 401
    re-triggered /refresh.
    """
    clear_auth_cookies(response)
    return {"detail": "Logged out"}
