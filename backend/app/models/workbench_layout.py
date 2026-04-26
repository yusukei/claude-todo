from datetime import UTC, datetime

import pymongo
from beanie import Document, Indexed
from pydantic import Field


class WorkbenchLayout(Document):
    """Per-user, per-project Workbench layout (pane tree + paneConfig).

    Stored server-side so the layout — including TerminalPane sessionIds —
    follows the user across devices and browser reloads. The `tree` field
    is opaque JSON owned by the frontend (`PersistedLayout` shape); the
    backend never inspects it beyond storing/returning the blob.

    Last-write-wins by `updated_at`; `client_id` carries the writing tab's
    identifier so that tab can ignore its own SSE echo.
    """

    user_id: Indexed(str)
    project_id: Indexed(str)
    tree: dict
    schema_version: int
    client_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "workbench_layouts"
        indexes = [
            pymongo.IndexModel(
                [("user_id", pymongo.ASCENDING), ("project_id", pymongo.ASCENDING)],
                unique=True,
                name="uniq_user_project",
            ),
        ]
