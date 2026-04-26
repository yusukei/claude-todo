"""Per-user, per-project Workbench layout persistence + multi-device sync.

The layout (pane tree + paneConfig including TerminalPane sessionIds) is
stored server-side keyed by ``(user_id, project_id)`` so it follows the
user across devices and reloads. Each PUT publishes a
``workbench.layout.updated`` SSE event scoped to that user; the writing
tab compares ``client_id`` to ignore its own echo.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ....core.deps import get_current_user
from ....core.validators import valid_object_id
from ....models import Project, User, WorkbenchLayout
from ....models.project import ProjectStatus
from ....services.events import publish_user_event

router = APIRouter(prefix="/workbench/layouts", tags=["workbench"])


class LayoutPayload(BaseModel):
    """Body for PUT /workbench/layouts/{project_id}.

    ``tree`` is the opaque ``PersistedLayout`` blob owned by the
    frontend; the backend never inspects its shape beyond storing /
    returning it. ``schema_version`` lets clients detect a mismatched
    server payload (older client reads a v3 layout written by a newer
    tab → can fall back to default rather than crashing on unknown
    pane types).
    """

    tree: dict = Field(..., description="Frontend-owned PersistedLayout JSON")
    schema_version: int = Field(..., ge=1)
    client_id: str = Field(..., min_length=1, max_length=128)


class LayoutResponse(BaseModel):
    tree: dict
    schema_version: int
    client_id: str
    updated_at: str


class PutResponse(BaseModel):
    updated_at: str


async def _ensure_project_active(project_id: str) -> None:
    valid_object_id(project_id)
    project = await Project.get(project_id)
    if not project or project.status != ProjectStatus.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/{project_id}", response_model=LayoutResponse)
async def get_layout(
    project_id: str,
    user: User = Depends(get_current_user),
) -> LayoutResponse:
    await _ensure_project_active(project_id)
    layout = await WorkbenchLayout.find_one(
        WorkbenchLayout.user_id == str(user.id),
        WorkbenchLayout.project_id == project_id,
    )
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    return LayoutResponse(
        tree=layout.tree,
        schema_version=layout.schema_version,
        client_id=layout.client_id,
        updated_at=layout.updated_at.isoformat(),
    )


@router.put("/{project_id}", response_model=PutResponse)
async def put_layout(
    project_id: str,
    payload: LayoutPayload = Body(...),
    user: User = Depends(get_current_user),
) -> PutResponse:
    return await _upsert_layout(project_id, payload, user)


@router.post("/{project_id}/beacon", response_model=PutResponse)
async def beacon_layout(
    project_id: str,
    payload: LayoutPayload = Body(...),
    user: User = Depends(get_current_user),
) -> PutResponse:
    """POST alias for PUT — used by ``navigator.sendBeacon`` on
    ``beforeunload`` / ``pagehide``. The Beacon API only emits POSTs,
    so a regular PUT cannot survive a tab close mid-debounce. This
    endpoint exists solely to absorb that path; semantics are
    identical to ``put_layout``.
    """
    return await _upsert_layout(project_id, payload, user)


async def _upsert_layout(
    project_id: str, payload: LayoutPayload, user: User
) -> PutResponse:
    await _ensure_project_active(project_id)

    now = datetime.now(UTC)
    layout = await WorkbenchLayout.find_one(
        WorkbenchLayout.user_id == str(user.id),
        WorkbenchLayout.project_id == project_id,
    )
    if layout is None:
        layout = WorkbenchLayout(
            user_id=str(user.id),
            project_id=project_id,
            tree=payload.tree,
            schema_version=payload.schema_version,
            client_id=payload.client_id,
            created_at=now,
            updated_at=now,
        )
        await layout.insert()
    else:
        layout.tree = payload.tree
        layout.schema_version = payload.schema_version
        layout.client_id = payload.client_id
        layout.updated_at = now
        await layout.save()

    # Re-read so the response surfaces exactly what the database
    # stored (some drivers strip tzinfo / round microseconds, and a
    # subsequent GET would otherwise return a different string than
    # this PUT response — breaking client-side LWW comparisons).
    saved = await WorkbenchLayout.find_one(
        WorkbenchLayout.user_id == str(user.id),
        WorkbenchLayout.project_id == project_id,
    )
    assert saved is not None  # we just wrote it
    saved_updated_at = saved.updated_at.isoformat()

    await publish_user_event(
        user_id=str(user.id),
        event_type="workbench.layout.updated",
        data={
            "project_id": project_id,
            "client_id": payload.client_id,
            "schema_version": payload.schema_version,
            "updated_at": saved_updated_at,
        },
        project_id=project_id,
    )

    return PutResponse(updated_at=saved_updated_at)
