"""Task comment add/delete endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .....core.deps import get_current_user
from .....core.validators import valid_object_id
from .....models import Task, User
from .....models.task import Comment
from .....services.events import publish_event
from .....services.search import index_task as _index_task
from .....services.serializers import task_to_dict as _task_dict
from ._shared import AddCommentRequest, check_not_locked, check_project_access

router = APIRouter()


@router.post("/{task_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    project_id: str, task_id: str, body: AddCommentRequest, user: User = Depends(get_current_user)
) -> dict:
    valid_object_id(task_id)
    project = await check_project_access(project_id, user)
    check_not_locked(project)
    task = await Task.get(task_id)
    if not task or task.project_id != project_id or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    comment = Comment(content=body.content, author_id=str(user.id), author_name=user.name)
    task.comments.append(comment)
    await task.save_updated()
    await publish_event(project_id, "comment.added", {"task_id": task_id, "comment": {
        "id": comment.id, "content": comment.content,
        "author_id": comment.author_id, "author_name": comment.author_name,
        "created_at": comment.created_at.isoformat(),
    }})
    await _index_task(task)
    return _task_dict(task)


@router.delete("/{task_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    project_id: str, task_id: str, comment_id: str, user: User = Depends(get_current_user)
) -> None:
    valid_object_id(task_id)
    project = await check_project_access(project_id, user)
    check_not_locked(project)
    task = await Task.get(task_id)
    if not task or task.project_id != project_id or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    comment = next((c for c in task.comments if c.id == comment_id), None)
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.author_id != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not comment author")

    task.comments = [c for c in task.comments if c.id != comment_id]
    task.record_change("comment", comment.content, None, str(user.id))
    await task.save_updated()
    await publish_event(project_id, "comment.deleted", {"task_id": task_id, "comment_id": comment_id})
