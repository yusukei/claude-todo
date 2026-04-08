"""Bulk task operations: reorder, export, batch update."""
from __future__ import annotations

import asyncio

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from .....core.deps import get_current_user
from .....core.validators import valid_object_id
from .....models import Task, User
from .....services.events import publish_event
from .....services.search import index_task as _index_task
from .....services.serializers import task_to_dict as _task_dict
from .....services.task_approval import cascade_approve_subtasks
from .....services.task_export import export_tasks_markdown, export_tasks_pdf
from ._shared import (
    BatchUpdateRequest,
    ExportTasksRequest,
    ReorderTasksRequest,
    check_not_locked,
    check_project_access,
)

router = APIRouter()


@router.post("/reorder")
async def reorder_tasks(
    project_id: str,
    body: ReorderTasksRequest,
    user: User = Depends(get_current_user),
):
    """Reorder tasks by assigning sequential sort_order values."""
    await check_project_access(project_id, user)

    try:
        oids = [ObjectId(tid) for tid in body.task_ids]
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid task ID")

    tasks = await Task.find(
        {"_id": {"$in": oids}, "project_id": project_id, "is_deleted": False},
    ).to_list()

    task_map = {str(t.id): t for t in tasks}
    updates = []
    for i, tid in enumerate(body.task_ids):
        task = task_map.get(tid)
        if task and task.sort_order != i:
            task.sort_order = i
            updates.append(task.save())
    if updates:
        await asyncio.gather(*updates)

    return {"reordered": len(updates)}


@router.post("/export")
async def export_tasks(
    project_id: str,
    body: ExportTasksRequest,
    user: User = Depends(get_current_user),
):
    """Export selected tasks as Markdown or PDF."""
    await check_project_access(project_id, user)

    try:
        oids = [ObjectId(tid) for tid in body.task_ids]
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid task ID")

    fetched = await Task.find(
        {"_id": {"$in": oids}, "project_id": project_id, "is_deleted": False},
    ).to_list()

    # Preserve the order from the request (reflects UI sort_order)
    task_map = {str(t.id): t for t in fetched}
    tasks = [task_map[tid] for tid in body.task_ids if tid in task_map]

    if not tasks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No tasks found")

    # Fetch subtasks for each task
    parent_ids = [str(t.id) for t in tasks]
    subtasks = await Task.find(
        {"project_id": project_id, "parent_task_id": {"$in": parent_ids}, "is_deleted": False},
    ).sort("+sort_order", "+created_at").to_list()
    subtasks_by_parent: dict[str, list[Task]] = {}
    for st in subtasks:
        subtasks_by_parent.setdefault(st.parent_task_id, []).append(st)

    if body.format == "markdown":
        md_text = export_tasks_markdown(tasks, subtasks_by_parent)
        filename = f"tasks_{project_id[:8]}.md"
        return Response(
            content=md_text.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    pdf_bytes = await export_tasks_pdf(tasks, subtasks_by_parent)
    filename = f"tasks_{project_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/batch")
async def batch_update_tasks(
    project_id: str, body: BatchUpdateRequest, user: User = Depends(get_current_user)
) -> dict:
    """Update flags (needs_detail, approved, archived) for multiple tasks in one request."""
    project = await check_project_access(project_id, user)
    check_not_locked(project)
    actor = str(user.id)

    task_ids = [u.task_id for u in body.updates]
    for tid in task_ids:
        valid_object_id(tid)

    tasks = await Task.find(
        {"_id": {"$in": [ObjectId(tid) for tid in task_ids]}},
        Task.project_id == project_id,
        Task.is_deleted == False,
    ).to_list()
    task_map = {str(t.id): t for t in tasks}

    updated = []
    failed = []
    cascade_ids: list[str] = []

    for item in body.updates:
        task = task_map.get(item.task_id)
        if not task:
            failed.append({"task_id": item.task_id, "error": "Task not found"})
            continue

        changes = item.model_dump(exclude_unset=True, exclude={"task_id"})
        if "needs_detail" in changes:
            task.record_change("needs_detail", str(task.needs_detail), str(changes["needs_detail"]), actor)
            task.needs_detail = changes["needs_detail"]
            if changes["needs_detail"]:
                task.approved = False
        if "approved" in changes:
            task.record_change("approved", str(task.approved), str(changes["approved"]), actor)
            task.approved = changes["approved"]
            if changes["approved"]:
                task.needs_detail = False
                cascade_ids.append(str(task.id))
        if "archived" in changes:
            task.archived = changes["archived"]

        updated.append(task)

    results = await asyncio.gather(
        *[t.save_updated() for t in updated], return_exceptions=True
    )

    saved = []
    for task, result in zip(updated, results):
        if isinstance(result, Exception):
            failed.append({"task_id": str(task.id), "error": str(result)})
        else:
            saved.append(_task_dict(task))
            await _index_task(task)

    if saved:
        await publish_event(project_id, "tasks.batch_updated", {
            "count": len(saved), "task_ids": [t["id"] for t in saved]
        })

    saved_ids = {t["id"] for t in saved}
    for cid in cascade_ids:
        if cid in saved_ids:
            await cascade_approve_subtasks(cid, actor)

    return {"updated": saved, "failed": failed}
