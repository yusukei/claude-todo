"""Task attachment upload / delete endpoints.

Only POST /{task_id}/attachments (upload) and DELETE /{task_id}/attachments/{attachment_id}
live here. The ``serve_attachment`` GET endpoint lives in the separate
``endpoints/attachments.py`` module because it requires a different URL prefix.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from .....core.deps import get_current_user
from .....core.validators import valid_object_id
from .....models import Task, User
from .....models.task import Attachment
from .....services.events import publish_event
from .....services.serializers import task_to_dict as _task_dict
from . import _shared
from ._shared import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE,
    check_not_locked,
    check_project_access,
)

router = APIRouter()


@router.post("/{task_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    project_id: str, task_id: str, file: UploadFile, user: User = Depends(get_current_user)
) -> dict:
    valid_object_id(task_id)
    project = await check_project_access(project_id, user)
    check_not_locked(project)
    task = await Task.get(task_id)
    if not task or task.project_id != project_id or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    safe_filename = Path(file.filename).name if file.filename else "upload"
    unique_name = f"{uuid.uuid4().hex}_{safe_filename}"
    task_dir = _shared.UPLOADS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    dest = task_dir / unique_name
    try:
        dest.write_bytes(contents)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=f"Failed to write file to disk: {exc}",
        )

    attachment = Attachment(
        filename=unique_name,
        content_type=file.content_type,
        size=len(contents),
    )
    task.attachments.append(attachment)
    await task.save_updated()
    await publish_event(project_id, "task.updated", _task_dict(task))
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size": attachment.size,
        "created_at": attachment.created_at.isoformat(),
    }


@router.delete("/{task_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    project_id: str, task_id: str, attachment_id: str, user: User = Depends(get_current_user)
) -> None:
    valid_object_id(task_id)
    project = await check_project_access(project_id, user)
    check_not_locked(project)
    task = await Task.get(task_id)
    if not task or task.project_id != project_id or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    attachment = next((a for a in task.attachments if a.id == attachment_id), None)
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    # Delete file from disk
    file_path = _shared.UPLOADS_DIR / task_id / attachment.filename
    if file_path.exists():
        file_path.unlink()

    task.attachments = [a for a in task.attachments if a.id != attachment_id]
    await task.save_updated()
    await publish_event(project_id, "task.updated", _task_dict(task))
