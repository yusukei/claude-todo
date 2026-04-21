"""File browser REST endpoints — directory listing, file reads, git status/diff."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from .....core.deps import get_current_user_flexible
from .....models import Project, User
from .....services.agent_manager import (
    AgentOfflineError,
    CommandTimeoutError,
    agent_manager,
)

router = APIRouter()


def _validate_path(path: str) -> str:
    if "\x00" in path or "\r" in path or "\n" in path:
        raise HTTPException(status_code=422, detail="Invalid characters in path")
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=422, detail="Path traversal not allowed")
    return path


async def _get_project(project_id: str, user: User) -> Project:
    project = await Project.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    is_member = user.is_admin or any(m.user_id == str(user.id) for m in project.members)
    if not is_member:
        raise HTTPException(status_code=403, detail="Access denied")
    if not project.remote:
        raise HTTPException(status_code=409, detail="No remote agent bound to this project")
    return project


async def _agent_request(agent_id: str, msg_type: str, payload: dict, timeout: float) -> dict:
    try:
        return await agent_manager.send_request(agent_id, msg_type, payload, timeout=timeout)
    except AgentOfflineError:
        raise HTTPException(status_code=503, detail="Agent is offline")
    except CommandTimeoutError:
        raise HTTPException(status_code=504, detail="Agent request timed out")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/projects/{project_id}/files")
async def list_files(
    project_id: str,
    path: str = Query(default="."),
    user: User = Depends(get_current_user_flexible),
) -> dict:
    _validate_path(path)
    project = await _get_project(project_id, user)
    result = await _agent_request(
        project.remote.agent_id,
        "list_dir",
        {"path": path, "cwd": project.remote.remote_path},
        timeout=15,
    )
    return {
        "entries": result.get("entries", []),
        "count": len(result.get("entries", [])),
        "path": result.get("path", path),
    }


@router.get("/projects/{project_id}/file")
async def read_file(
    project_id: str,
    path: str = Query(...),
    user: User = Depends(get_current_user_flexible),
) -> dict:
    _validate_path(path)
    project = await _get_project(project_id, user)
    result = await _agent_request(
        project.remote.agent_id,
        "read_file",
        {"path": path, "cwd": project.remote.remote_path},
        timeout=30,
    )
    return {
        "content": result.get("content", ""),
        "path": result.get("path", path),
        "is_binary": result.get("is_binary", False),
        "total_lines": result.get("total_lines", 0),
        "truncated": result.get("truncated", False),
    }


@router.get("/projects/{project_id}/file-raw")
async def read_file_raw(
    project_id: str,
    path: str = Query(...),
    user: User = Depends(get_current_user_flexible),
) -> Response:
    """Serve a file with its native Content-Type for inline browser display (PDF, images)."""
    _validate_path(path)
    project = await _get_project(project_id, user)
    result = await _agent_request(
        project.remote.agent_id,
        "read_file",
        {"path": path, "cwd": project.remote.remote_path},
        timeout=60,
    )
    content = result.get("content", "")
    is_binary = result.get("is_binary", False)

    data: bytes = base64.b64decode(content) if is_binary else content.encode("utf-8")

    mime_type, _ = mimetypes.guess_type(path)
    media_type = mime_type or "application/octet-stream"

    headers = {"Content-Disposition": "inline"}
    return Response(content=data, media_type=media_type, headers=headers)


@router.get("/projects/{project_id}/git/status")
async def git_status(
    project_id: str,
    user: User = Depends(get_current_user_flexible),
) -> dict:
    project = await _get_project(project_id, user)
    result = await _agent_request(
        project.remote.agent_id,
        "exec",
        {
            "command": "git status --porcelain -uall",
            "cwd": project.remote.remote_path,
            "timeout": 15,
        },
        timeout=20,
    )
    stdout = result.get("stdout", "")
    exit_code = result.get("exit_code", 0)

    files = []
    for line in stdout.splitlines():
        if len(line) >= 3:
            xy = line[:2]
            filepath = line[3:]
            # git status --porcelain uses forward slashes even on Windows
            files.append({"status": xy, "path": filepath})

    return {
        "files": files,
        "exit_code": exit_code,
        "error": result.get("stderr", "") if exit_code != 0 else "",
    }


@router.get("/projects/{project_id}/git/diff")
async def git_diff(
    project_id: str,
    path: str = Query(default=""),
    staged: bool = Query(default=False),
    user: User = Depends(get_current_user_flexible),
) -> dict:
    if path:
        _validate_path(path)
        # Reject embedded double-quotes to prevent shell injection
        if '"' in path:
            raise HTTPException(status_code=422, detail="Invalid characters in path")

    project = await _get_project(project_id, user)

    base = "git diff --cached" if staged else "git diff HEAD"
    cmd = f'{base} -- "{path}"' if path else base

    result = await _agent_request(
        project.remote.agent_id,
        "exec",
        {
            "command": cmd,
            "cwd": project.remote.remote_path,
            "timeout": 15,
        },
        timeout=20,
    )
    exit_code = result.get("exit_code", 0)
    return {
        "diff": result.get("stdout", ""),
        "exit_code": exit_code,
        "error": result.get("stderr", "") if exit_code != 0 else "",
    }
