from datetime import UTC, datetime
from enum import StrEnum as str_enum

from beanie import Document, Indexed
from pydantic import Field


class DocumentCategory(str_enum):
    spec = "spec"
    design = "design"
    api = "api"
    guide = "guide"
    notes = "notes"


class ProjectDocument(Document):
    project_id: Indexed(str)  # type: ignore[valid-type]
    title: Indexed(str)  # type: ignore[valid-type]
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    category: DocumentCategory = DocumentCategory.spec
    version: int = 1
    created_by: str = ""
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    async def save_updated(self, **kwargs):
        self.updated_at = datetime.now(UTC)
        await self.save(**kwargs)

    class Settings:
        name = "project_documents"
        indexes = [
            [("project_id", 1), ("is_deleted", 1)],
            [("project_id", 1), ("category", 1), ("is_deleted", 1)],
            [("is_deleted", 1), ("tags", 1)],
        ]


class DocumentVersion(Document):
    document_id: Indexed(str)  # type: ignore[valid-type]
    version: int
    title: str
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    category: DocumentCategory = DocumentCategory.spec
    changed_by: str = ""
    task_id: str | None = None
    change_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "document_versions"
        indexes = [
            [("document_id", 1), ("version", -1)],
            [("task_id", 1)],
        ]
