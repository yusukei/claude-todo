"""Install-token issue / list / revoke / exchange (supervisor-only flow).

Issues a one-time bootstrap token an admin hands to a target machine
(via URL, in 1-line install). The target machine's supervisor consumes
the token via :func:`exchange_install_token` and gets the persistent
``sv_`` and initial ``ta_`` tokens back.

The flow keeps operators from ever touching the agent token: the
install URL is the only secret the human sees, and it dies on first
use (or after ``ttl_minutes``).

Endpoints:
- ``POST   /api/v1/workspaces/install-tokens``           — admin: issue
- ``GET    /api/v1/workspaces/install-tokens``           — admin: list mine
- ``DELETE /api/v1/workspaces/install-tokens/{code}``    — admin: revoke
- ``POST   /api/v1/workspaces/supervisors/exchange``     — install_token auth: consume

The public ``GET /install/{code}`` endpoint that streams the PowerShell
bootstrap script lives in :mod:`app.api.v1.endpoints.install_public`
and is mounted at the app root for shorter URLs.
"""
from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from beanie.exceptions import RevisionIdWasChanged
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from .....core.config import settings
from .....core.deps import get_admin_user_flexible
from .....core.security import hash_api_key
from .....models import InstallToken, RemoteAgent, RemoteSupervisor, User

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Constants & helpers ────────────────────────────────────────────────

#: Default install-token lifetime when the caller omits ``ttl_minutes``.
DEFAULT_TTL_MINUTES = 60
#: Hard cap on ``ttl_minutes``; longer-lived install URLs are rejected
#: because the install_token is *the* secret in the URL.
MAX_TTL_MINUTES = 24 * 60  # 24 hours


def _backend_base_url() -> str:
    """Backend public origin for embedding in install URLs.

    Falls back to ``FRONTEND_URL`` when ``BASE_URL`` is unset (single-host
    deploys where both share the same external URL).
    """
    base = (settings.BASE_URL or settings.FRONTEND_URL).rstrip("/")
    if not base:
        # Defensive: in tests pytest-env populates FRONTEND_URL but a
        # broken config would otherwise emit a relative URL that
        # PowerShell can't resolve.
        return "http://localhost:8000"
    return base


def _build_install_url(code: str) -> str:
    return f"{_backend_base_url()}/install/{code}"


def _agent_ws_url() -> str:
    base = _backend_base_url()
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + \
        "/api/v1/workspaces/agent/ws"


def _supervisor_ws_url() -> str:
    base = _backend_base_url()
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + \
        "/api/v1/workspaces/supervisor/ws"


def _as_utc(dt: datetime) -> datetime:
    """Force a UTC tzinfo on naive datetimes (MongoDB strips tz on read)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _install_token_dict(t: InstallToken) -> dict[str, Any]:
    expires_utc = _as_utc(t.expires_at)
    return {
        "code": t.code,
        "name": t.name,
        "created_by": t.created_by,
        "created_at": _as_utc(t.created_at).isoformat(),
        "expires_at": expires_utc.isoformat(),
        "consumed_at": _as_utc(t.consumed_at).isoformat() if t.consumed_at else None,
        "consumed_by_supervisor_id": t.consumed_by_supervisor_id,
        "paired_existing_agent_id": t.paired_existing_agent_id,
        "install_url": _build_install_url(t.code),
        "is_active": t.consumed_at is None and expires_utc > datetime.now(UTC),
    }


# ── Request / response schemas ────────────────────────────────────────


class CreateInstallTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    ttl_minutes: int = Field(
        DEFAULT_TTL_MINUTES, gt=0, le=MAX_TTL_MINUTES,
        description="Lifetime in minutes. Capped at 24h.",
    )
    paired_existing_agent_id: str | None = Field(
        None,
        description=(
            "If set, the exchange step will adopt this RemoteAgent "
            "(rotates its token and links it to the new supervisor). "
            "Use during migration of legacy agents to the supervisor-only "
            "model — leave unset for fresh installs."
        ),
    )


class ExchangeResponse(BaseModel):
    """Returned to the *supervisor* (Rust client running --bootstrap)."""
    supervisor_id: str
    supervisor_token: str  # sv_<hex>
    supervisor_name: str
    agent_id: str
    agent_token: str  # ta_<hex>
    agent_name: str
    backend_urls: dict[str, str]  # {"supervisor_ws": "...", "agent_ws": "..."}


# ── Admin REST: issue / list / revoke ─────────────────────────────────


@router.post(
    "/install-tokens",
    status_code=status.HTTP_201_CREATED,
)
async def create_install_token(
    body: CreateInstallTokenRequest,
    user: User = Depends(get_admin_user_flexible),
) -> dict[str, Any]:
    """Issue a one-time install token. Admin only.

    The returned ``install_url`` is the only thing the operator hands
    to the target machine — visit it (or pipe through ``iex``) and the
    full bootstrap completes.
    """
    if body.paired_existing_agent_id:
        # Validate up front so admins get a 422 *now* instead of at
        # exchange time (when the human in the loop has moved on).
        existing = await RemoteAgent.get(body.paired_existing_agent_id)
        if not existing or existing.owner_id != str(user.id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "paired_existing_agent_id refers to an agent that does "
                    "not exist or that you do not own."
                ),
            )

    code = f"in_{secrets.token_hex(16)}"
    token = InstallToken(
        code=code,
        name=body.name,
        created_by=str(user.id),
        expires_at=datetime.now(UTC) + timedelta(minutes=body.ttl_minutes),
        paired_existing_agent_id=body.paired_existing_agent_id,
    )
    await token.insert()
    logger.info(
        "Install token issued: code=%s name=%s owner=%s ttl_min=%d paired=%s",
        code, body.name, user.id, body.ttl_minutes, body.paired_existing_agent_id,
    )
    return _install_token_dict(token)


@router.get("/install-tokens")
async def list_install_tokens(
    user: User = Depends(get_admin_user_flexible),
) -> list[dict[str, Any]]:
    """List install tokens issued by the current admin (active + consumed)."""
    tokens = await InstallToken.find(
        {"created_by": str(user.id)}
    ).sort("-created_at").to_list()
    return [_install_token_dict(t) for t in tokens]


@router.delete(
    "/install-tokens/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_install_token(
    code: str,
    user: User = Depends(get_admin_user_flexible),
) -> None:
    """Revoke (delete) an install token early. Idempotent — already-
    consumed tokens are also deleted."""
    token = await InstallToken.find_one({"code": code})
    if not token or token.created_by != str(user.id):
        # Mirror the agent / supervisor admin endpoints: don't leak
        # existence to non-owners.
        raise HTTPException(status_code=404, detail="Install token not found")
    await token.delete()
    logger.info("Install token revoked: code=%s owner=%s", code, user.id)


# ── Anonymous: exchange (consume) ─────────────────────────────────────


@router.post(
    "/supervisors/exchange",
    response_model=ExchangeResponse,
)
async def exchange_install_token(
    x_install_token: str | None = Header(None, alias="X-Install-Token"),
) -> ExchangeResponse:
    """Consume an install_token; mint persistent ``sv_`` + ``ta_`` tokens.

    Called by the Rust supervisor's ``--bootstrap`` mode. The endpoint
    is **anonymous** at the framework level (no admin check) — the
    install_token itself is the bearer credential, validated below.

    Atomicity: the install_token is consumed *before* the supervisor /
    agent records are mutated. If a concurrent caller wins the race,
    only one supervisor is created; the loser gets a 410.
    """
    if not x_install_token or not x_install_token.startswith("in_"):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed X-Install-Token header",
        )

    token = await InstallToken.find_one({"code": x_install_token})
    if not token:
        raise HTTPException(status_code=410, detail="Install token not found or revoked")
    if token.consumed_at is not None:
        raise HTTPException(status_code=410, detail="Install token already consumed")
    if _as_utc(token.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=410, detail="Install token expired")

    # ── Mint supervisor record ─────────────────────────────────────
    raw_sv_token = f"sv_{secrets.token_hex(32)}"
    supervisor = RemoteSupervisor(
        name=token.name,
        key_hash=hash_api_key(raw_sv_token),
        owner_id=token.created_by,
    )
    await supervisor.insert()
    sv_id = str(supervisor.id)

    # ── Mint or adopt the paired agent record ──────────────────────
    raw_agent_token = f"ta_{secrets.token_hex(32)}"
    agent_key_hash = hash_api_key(raw_agent_token)

    if token.paired_existing_agent_id:
        agent = await RemoteAgent.get(token.paired_existing_agent_id)
        if not agent or agent.owner_id != token.created_by:
            # Roll back the supervisor we just minted — the install
            # contract was "exchange or fail", not "exchange and leak
            # half a record".
            await supervisor.delete()
            raise HTTPException(
                status_code=409,
                detail="Paired agent record no longer exists or owner changed.",
            )
        agent.key_hash = agent_key_hash
        await agent.save()
    else:
        agent = RemoteAgent(
            name=f"{token.name}-agent",
            key_hash=agent_key_hash,
            owner_id=token.created_by,
        )
        await agent.insert()

    agent_id = str(agent.id)

    # ── Pair the supervisor → agent and remember the issued token ──
    supervisor.paired_agent_id = agent_id
    supervisor.agent_token_hash = agent_key_hash
    await supervisor.save()

    # ── Consume the install_token (last write so a panic above
    #    leaves the token reusable instead of stranding the operator) ─
    token.consumed_at = datetime.now(UTC)
    token.consumed_by_supervisor_id = sv_id
    try:
        await token.save()
    except RevisionIdWasChanged:
        # Another concurrent caller beat us to the consume. Roll back
        # the records we created and surface the conflict.
        await supervisor.delete()
        if not token.paired_existing_agent_id:
            await agent.delete()
        raise HTTPException(
            status_code=410, detail="Install token consumed by a concurrent request"
        )

    logger.info(
        "Install token exchanged: code=%s -> supervisor=%s agent=%s (paired=%s)",
        token.code, sv_id, agent_id, bool(token.paired_existing_agent_id),
    )

    return ExchangeResponse(
        supervisor_id=sv_id,
        supervisor_token=raw_sv_token,
        supervisor_name=supervisor.name,
        agent_id=agent_id,
        agent_token=raw_agent_token,
        agent_name=agent.name,
        backend_urls={
            "supervisor_ws": _supervisor_ws_url(),
            "agent_ws": _agent_ws_url(),
        },
    )
