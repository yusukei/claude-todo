from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from ....core.deps import get_current_user
from ....core.validators import valid_object_id
from ....models import Task, User

router = APIRouter(prefix="/attachments", tags=["attachments"])

UPLOADS_DIR = Path(__file__).resolve().parents[4] / "uploads"


@router.get("/{task_id}/{filename}")
async def serve_attachment(
    task_id: str, filename: str, user: User = Depends(get_current_user)
) -> FileResponse:
    valid_object_id(task_id)

    # Verify the filename exists in the task's attachments list
    task = await Task.get(task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if not any(a.filename == filename for a in task.attachments):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    file_path = UPLOADS_DIR / task_id / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    # Prevent path traversal
    try:
        file_path.resolve().relative_to(UPLOADS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

    return FileResponse(file_path)
