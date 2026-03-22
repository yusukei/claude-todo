import os
import subprocess
import tempfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from ....core.config import settings
from ....core.deps import get_admin_user
from ....models import User

router = APIRouter(prefix="/backup", tags=["backup"])

BACKUP_DIR = "/tmp/backups"


def _build_mongodump_args() -> list[str]:
    """Build mongodump command arguments from config."""
    return [
        "mongodump",
        f"--uri={settings.MONGO_URI}",
        f"--db={settings.MONGO_DBNAME}",
        "--gzip",
        "--archive",  # value will be appended by caller
    ]


def _build_mongorestore_args() -> list[str]:
    """Build mongorestore command arguments from config."""
    return [
        "mongorestore",
        f"--uri={settings.MONGO_URI}",
        f"--db={settings.MONGO_DBNAME}",
        "--gzip",
        "--archive",  # value will be appended by caller
        "--drop",
        "--nsFrom=*",
        f"--nsTo={settings.MONGO_DBNAME}.*",
    ]


@router.post("/export")
async def export_backup(_: User = Depends(get_admin_user)):
    """Create a backup using mongodump and return the .agz file."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.agz"
    filepath = os.path.join(BACKUP_DIR, filename)

    args = _build_mongodump_args()
    # Set archive output path
    args[-1] = f"--archive={filepath}"

    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"mongodump failed: {result.stderr}",
        )

    return FileResponse(
        filepath,
        media_type="application/gzip",
        filename=filename,
    )


@router.post("/import")
async def import_backup(
    file: UploadFile,
    _: User = Depends(get_admin_user),
):
    """Restore a backup using mongorestore from an uploaded .agz file."""
    if not file.filename or not file.filename.endswith(".agz"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be .agz format",
        )

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".agz") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        args = _build_mongorestore_args()
        # Set archive input path
        args = [a for a in args if not a.startswith("--archive")]
        args.append(f"--archive={tmp_path}")

        result = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"mongorestore failed: {result.stderr}",
            )

        return {"status": "ok", "message": "Restore completed successfully"}
    finally:
        os.unlink(tmp_path)
