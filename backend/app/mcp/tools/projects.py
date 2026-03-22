import logging

from ...models import Project, Task
from ...models.project import ProjectStatus
from ...models.task import TaskStatus
from ..auth import authenticate, check_project_access
from ..server import mcp

logger = logging.getLogger(__name__)


def _project_dict(p: Project) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "color": p.color,
        "status": p.status,
        "members": [{"user_id": m.user_id, "joined_at": m.joined_at.isoformat()} for m in p.members],
        "created_by": str(p.created_by.ref.id) if hasattr(p.created_by, "ref") else str(p.created_by),
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@mcp.tool()
async def list_projects() -> list[dict]:
    """List all accessible projects."""
    key_info = await authenticate()
    scopes = key_info["project_scopes"]

    query = Project.find(Project.status == ProjectStatus.active)
    if scopes:
        query = query.find({"_id": {"$in": scopes}})
    projects = await query.to_list()
    return [_project_dict(p) for p in projects]


@mcp.tool()
async def get_project(project_id: str) -> dict:
    """Get detailed information about a project.

    Args:
        project_id: Project ID or project name
    """
    key_info = await authenticate()
    project_id = await _resolve_project_id(project_id)
    check_project_access(project_id, key_info["project_scopes"])

    project = await Project.get(project_id)
    if not project:
        from fastmcp.exceptions import ToolError
        raise ToolError("Project not found")
    return _project_dict(project)


@mcp.tool()
async def get_project_summary(project_id: str) -> dict:
    """Get project progress summary (task counts by status, completion rate).

    Args:
        project_id: Project ID or project name
    """
    key_info = await authenticate()
    project_id = await _resolve_project_id(project_id)
    check_project_access(project_id, key_info["project_scopes"])

    project = await Project.get(project_id)
    if not project:
        from fastmcp.exceptions import ToolError
        raise ToolError("Project not found")

    tasks = await Task.find(
        Task.project_id == project_id, Task.is_deleted == False  # noqa: E712
    ).to_list()
    counts = {s: 0 for s in TaskStatus}
    for t in tasks:
        counts[t.status] += 1

    return {
        "project_id": project_id,
        "total": len(tasks),
        "by_status": {k: v for k, v in counts.items()},
        "completion_rate": round(counts[TaskStatus.done] / len(tasks) * 100, 1) if tasks else 0,
    }


# ---------------------------------------------------------------------------
# Project name → ID resolver
# ---------------------------------------------------------------------------

import time as _time  # noqa: E402

_project_cache: dict[str, tuple[str, float]] = {}  # name -> (id, expiry)
_PROJECT_CACHE_TTL = 300  # 5 minutes


async def _resolve_project_id(project_id: str) -> str:
    """Resolve a project name to its ObjectId. Pass-through if already an ObjectId."""
    if len(project_id) == 24:
        try:
            int(project_id, 16)
            return project_id
        except ValueError:
            pass

    now = _time.monotonic()
    cached = _project_cache.get(project_id)
    if cached and cached[1] > now:
        return cached[0]

    projects = await Project.find(
        Project.status == ProjectStatus.active
    ).to_list()
    for p in projects:
        pid = str(p.id)
        _project_cache[p.name] = (pid, now + _PROJECT_CACHE_TTL)
        if p.name == project_id:
            return pid

    from fastmcp.exceptions import ToolError
    raise ToolError(f"Project not found: {project_id}")
