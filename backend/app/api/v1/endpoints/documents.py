from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ....core.deps import get_current_user
from ....models import Project, User
from ....models.document import DocumentCategory, DocumentVersion, ProjectDocument
from ....services.document_search import index_document, deindex_document
from ....services.serializers import (
    document_to_dict as _document_dict,
    document_version_summary as _version_summary,
    document_version_to_dict as _version_dict,
)

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

_VALID_CATEGORIES = {e.value for e in DocumentCategory}


class CreateDocumentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field("", max_length=100000)
    tags: list[str] = Field(default_factory=list)
    category: str = "spec"


class UpdateDocumentRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, max_length=100000)
    tags: list[str] | None = None
    category: str | None = None
    task_id: str | None = None
    change_summary: str | None = None


@router.get("/")
async def list_documents(
    project_id: str,
    category: str | None = Query(None),
    tag: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    filters: dict = {"project_id": project_id, "is_deleted": False}
    if category:
        if category not in _VALID_CATEGORIES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid category: {category}")
        filters["category"] = category
    if tag:
        filters["tags"] = tag.lower()
    if search:
        import re
        pattern = re.escape(search.strip())
        filters["$or"] = [
            {"title": {"$regex": pattern, "$options": "i"}},
            {"content": {"$regex": pattern, "$options": "i"}},
            {"tags": {"$regex": pattern, "$options": "i"}},
        ]

    total = await ProjectDocument.find(filters).count()
    docs = await ProjectDocument.find(filters).skip(skip).limit(limit).sort("-updated_at").to_list()
    return {"items": [_document_dict(d) for d in docs], "total": total, "limit": limit, "skip": skip}


async def _check_not_locked(project_id: str) -> None:
    project = await Project.get(project_id)
    if project and project.is_locked:
        raise HTTPException(status.HTTP_423_LOCKED, "Project is locked")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_document(
    project_id: str,
    body: CreateDocumentRequest,
    user: User = Depends(get_current_user),
):
    await _check_not_locked(project_id)
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid category: {body.category}")

    normalized_tags = [t.strip().lower() for t in body.tags if t.strip()]

    d = ProjectDocument(
        project_id=project_id,
        title=body.title.strip(),
        content=body.content,
        tags=normalized_tags,
        category=DocumentCategory(body.category),
        created_by=str(user.id),
    )
    await d.insert()
    await index_document(d)
    return _document_dict(d)


@router.get("/{document_id}")
async def get_document(
    project_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
):
    d = await ProjectDocument.get(document_id)
    if not d or d.is_deleted or d.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return _document_dict(d)


@router.patch("/{document_id}")
async def update_document(
    project_id: str,
    document_id: str,
    body: UpdateDocumentRequest,
    user: User = Depends(get_current_user),
):
    await _check_not_locked(project_id)
    d = await ProjectDocument.get(document_id)
    if not d or d.is_deleted or d.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    if body.category is not None and body.category not in _VALID_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid category: {body.category}")

    # Snapshot current state as a version
    version = DocumentVersion(
        document_id=str(d.id),
        version=d.version,
        title=d.title,
        content=d.content,
        tags=list(d.tags),
        category=d.category,
        changed_by=str(user.id),
        task_id=body.task_id,
        change_summary=body.change_summary,
    )
    await version.insert()

    # Apply updates
    if body.title is not None:
        d.title = body.title.strip()
    if body.content is not None:
        d.content = body.content
    if body.tags is not None:
        d.tags = [t.strip().lower() for t in body.tags if t.strip()]
    if body.category is not None:
        d.category = DocumentCategory(body.category)
    d.version += 1

    await d.save_updated()
    await index_document(d)
    return _document_dict(d)


@router.get("/{document_id}/versions")
async def list_document_versions(
    project_id: str,
    document_id: str,
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    d = await ProjectDocument.get(document_id)
    if not d or d.is_deleted or d.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    total = await DocumentVersion.find(
        DocumentVersion.document_id == str(d.id),
    ).count()
    versions = await DocumentVersion.find(
        DocumentVersion.document_id == str(d.id),
    ).sort("-version").skip(skip).limit(limit).to_list()

    return {
        "document_id": str(d.id),
        "current_version": d.version,
        "items": [_version_summary(v) for v in versions],
        "total": total,
    }


@router.get("/{document_id}/versions/{version_num}")
async def get_document_version(
    project_id: str,
    document_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
):
    d = await ProjectDocument.get(document_id)
    if not d or d.is_deleted or d.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    v = await DocumentVersion.find_one(
        DocumentVersion.document_id == str(d.id),
        DocumentVersion.version == version_num,
    )
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Version {version_num} not found")

    return _version_dict(v)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    project_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
):
    await _check_not_locked(project_id)
    d = await ProjectDocument.get(document_id)
    if not d or d.is_deleted or d.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    d.is_deleted = True
    await d.save_updated()
    await deindex_document(document_id)
