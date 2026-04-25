"""Supervisor CRUD + rotate-token admin endpoints.

Mirrors ``agents.py`` for the ``RemoteSupervisor`` collection. The
two endpoint families are deliberately parallel so an operator who
already understands the agent admin surface can navigate the
supervisor one without surprises.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .....core.deps import get_admin_user_flexible
from .....core.security import hash_api_key
from .....models import User
from .....models.remote import RemoteAgent, RemoteSupervisor
from .....services.supervisor_manager import supervisor_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSupervisorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


async def _supervisor_dict(s: RemoteSupervisor) -> dict[str, Any]:
    """Serialize a RemoteSupervisor for the admin REST surface.

    Includes a derived ``is_online`` flag (in-process), and the joined
    agent id from ``host_id`` so the UI can render the supervisor /
    agent pairing without a second round-trip.
    """
    sid = str(s.id)
    joined_agent_id: str | None = None
    if s.host_id:
        joined = await RemoteAgent.find_one({"host_id": s.host_id})
        if joined is not None:
            joined_agent_id = str(joined.id)
    return {
        "id": sid,
        "name": s.name,
        "host_id": s.host_id,
        "hostname": s.hostname,
        "os_type": s.os_type,
        "is_online": supervisor_manager.is_connected(sid),
        "supervisor_version": s.supervisor_version,
        "agent_version": s.agent_version,
        "agent_pid": s.agent_pid,
        "agent_uptime_s": s.agent_uptime_s,
        "joined_agent_id": joined_agent_id,
        "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
        "created_at": s.created_at.isoformat(),
    }


@router.get("/supervisors")
async def list_supervisors(
    user: User = Depends(get_admin_user_flexible),
) -> list[dict]:
    supervisors = await RemoteSupervisor.find(
        {"owner_id": str(user.id)}
    ).sort("-created_at").to_list()
    return [await _supervisor_dict(s) for s in supervisors]


@router.post("/supervisors", status_code=status.HTTP_201_CREATED)
async def create_supervisor(
    body: CreateSupervisorRequest,
    user: User = Depends(get_admin_user_flexible),
) -> dict:
    raw_token = f"sv_{secrets.token_hex(32)}"
    supervisor = RemoteSupervisor(
        name=body.name,
        key_hash=hash_api_key(raw_token),
        owner_id=str(user.id),
    )
    await supervisor.insert()
    return {**await _supervisor_dict(supervisor), "token": raw_token}


@router.get("/supervisors/{supervisor_id}")
async def get_supervisor(
    supervisor_id: str,
    user: User = Depends(get_admin_user_flexible),
) -> dict:
    s = await RemoteSupervisor.get(supervisor_id)
    if not s or s.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail="Supervisor not found")
    return await _supervisor_dict(s)


@router.delete(
    "/supervisors/{supervisor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_supervisor(
    supervisor_id: str,
    user: User = Depends(get_admin_user_flexible),
) -> None:
    s = await RemoteSupervisor.get(supervisor_id)
    if not s or s.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail="Supervisor not found")
    # Force unregister so any live WS is evicted and pending RPCs
    # fail fast instead of hanging until their timeout.
    await supervisor_manager.unregister(supervisor_id)
    await s.delete()


@router.post("/supervisors/{supervisor_id}/rotate-token")
async def rotate_supervisor_token(
    supervisor_id: str,
    user: User = Depends(get_admin_user_flexible),
) -> dict:
    """Issue a new ``sv_`` token and invalidate the old one.

    Per spec §3.4, ``sv_`` tokens are higher-privilege than agent
    tokens, so rotation is mandatory after any suspected leak. The
    in-flight WS (if any) is force-disconnected so it must
    re-authenticate with the new token.
    """
    s = await RemoteSupervisor.get(supervisor_id)
    if not s or s.owner_id != str(user.id):
        raise HTTPException(status_code=404, detail="Supervisor not found")

    raw_token = f"sv_{secrets.token_hex(32)}"
    s.key_hash = hash_api_key(raw_token)
    await s.save()

    if supervisor_manager.is_connected(supervisor_id):
        await supervisor_manager.unregister(supervisor_id)

    logger.info(
        "Rotated token for supervisor %s (%s)", s.name, supervisor_id
    )
    return {**await _supervisor_dict(s), "token": raw_token}
