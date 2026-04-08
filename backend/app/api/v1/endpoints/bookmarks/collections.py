"""Bookmark collection CRUD endpoints."""
from __future__ import annotations

import asyncio

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from .....core.deps import get_current_user
from .....core.validators import valid_object_id
from .....models import Bookmark, BookmarkCollection, User
from .....services.serializers import bookmark_collection_to_dict as _coll_dict
from ._shared import (
    CreateCollectionRequest,
    ReorderRequest,
    UpdateCollectionRequest,
    check_not_locked,
    check_project_access,
)

coll_router = APIRouter(
    prefix="/projects/{project_id}/bookmark-collections",
    tags=["bookmark-collections"],
)


@coll_router.post("/", status_code=status.HTTP_201_CREATED)
async def create_collection(
    project_id: str,
    body: CreateCollectionRequest,
    user: User = Depends(get_current_user),
):
    project = await check_project_access(project_id, user)
    check_not_locked(project)

    c = BookmarkCollection(
        project_id=project_id,
        name=body.name.strip(),
        description=body.description,
        icon=body.icon,
        color=body.color,
        created_by=str(user.id),
    )
    await c.insert()
    return _coll_dict(c)


@coll_router.get("/")
async def list_collections(
    project_id: str,
    user: User = Depends(get_current_user),
):
    await check_project_access(project_id, user)
    items = (
        await BookmarkCollection.find(
            {"project_id": project_id, "is_deleted": False},
        )
        .sort("+sort_order", "+name")
        .to_list()
    )
    return {"items": [_coll_dict(c) for c in items]}


@coll_router.patch("/{collection_id}")
async def update_collection(
    project_id: str,
    collection_id: str,
    body: UpdateCollectionRequest,
    user: User = Depends(get_current_user),
):
    project = await check_project_access(project_id, user)
    check_not_locked(project)

    valid_object_id(collection_id)
    c = await BookmarkCollection.get(collection_id)
    if not c or c.is_deleted or c.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")

    if body.name is not None:
        c.name = body.name.strip()
    if body.description is not None:
        c.description = body.description
    if body.icon is not None:
        c.icon = body.icon
    if body.color is not None:
        c.color = body.color

    await c.save_updated()
    return _coll_dict(c)


@coll_router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    project_id: str,
    collection_id: str,
    user: User = Depends(get_current_user),
):
    project = await check_project_access(project_id, user)
    check_not_locked(project)

    valid_object_id(collection_id)
    c = await BookmarkCollection.get(collection_id)
    if not c or c.is_deleted or c.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")

    c.is_deleted = True
    await c.save_updated()

    # Unset collection_id on bookmarks in this collection
    await Bookmark.find(
        {"collection_id": collection_id, "is_deleted": False},
    ).update({"$set": {"collection_id": None}})


@coll_router.post("/reorder")
async def reorder_collections(
    project_id: str,
    body: ReorderRequest,
    user: User = Depends(get_current_user),
):
    project = await check_project_access(project_id, user)
    check_not_locked(project)

    try:
        oids = [ObjectId(cid) for cid in body.ids]
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid collection ID")

    items = await BookmarkCollection.find(
        {"_id": {"$in": oids}, "project_id": project_id, "is_deleted": False},
    ).to_list()
    item_map = {str(c.id): c for c in items}

    updates = []
    for i, cid in enumerate(body.ids):
        c = item_map.get(cid)
        if c and c.sort_order != i:
            c.sort_order = i
            updates.append(c.save())
    if updates:
        await asyncio.gather(*updates)

    return {"reordered": len(updates)}
