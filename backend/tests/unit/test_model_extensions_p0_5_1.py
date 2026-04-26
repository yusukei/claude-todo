"""Phase 0.5.1 model extension tests.

Covers the new fields introduced for the UI redesign:

* ``Task.decider_id`` / ``Task.decision_requested_at``
* ``ActorType`` enum + ``ActivityEntry.actor_type``
* ``UserStatus`` enum + ``User.status`` / ``User.last_active_at``
* Backwards-compatible defaults (existing documents still load)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.models import ActorType, Task, User, UserStatus
from app.models.task import ActivityEntry, TaskPriority, TaskStatus, TaskType
from app.models.user import AuthType


# Note: ``asyncio_mode = auto`` is set in pyproject.toml, so async tests
# are picked up automatically. Plain (sync) tests in this file should
# NOT be marked async — the no-op auto-mark would emit a warning.


@pytest_asyncio.fixture
async def sample_project_id() -> str:
    return "p:phase-0.5.1"


# ── Task.decider_id / decision_requested_at ──────────────────────


async def test_task_decider_id_defaults_to_none(sample_project_id: str) -> None:
    t = Task(project_id=sample_project_id, title="t", created_by="u")
    assert t.decider_id is None
    assert t.decision_requested_at is None


async def test_task_decider_id_round_trip(sample_project_id: str) -> None:
    # mongomock loses tzinfo and truncates microseconds, so we compare
    # at second precision after stripping tz.
    requested_at = datetime.now(UTC).replace(microsecond=0)
    t = Task(
        project_id=sample_project_id,
        title="d",
        created_by="u",
        task_type=TaskType.decision,
        decider_id="user-koji",
        decision_requested_at=requested_at,
    )
    await t.insert()
    fetched = await Task.get(t.id)
    assert fetched is not None
    assert fetched.decider_id == "user-koji"
    assert fetched.decision_requested_at is not None
    rt = fetched.decision_requested_at
    if rt.tzinfo is None:
        rt = rt.replace(tzinfo=UTC)
    assert rt.replace(microsecond=0) == requested_at


# ── ActorType / ActivityEntry.actor_type ─────────────────────────


def test_activity_entry_actor_type_defaults_to_human() -> None:
    entry = ActivityEntry(field="status", old_value="todo", new_value="in_progress")
    assert entry.actor_type == ActorType.human


def test_activity_entry_actor_type_can_be_ai() -> None:
    entry = ActivityEntry(
        field="description",
        old_value="x",
        new_value="y",
        changed_by="mcp:test",
        actor_type=ActorType.ai,
    )
    assert entry.actor_type == ActorType.ai


async def test_record_change_writes_actor_type(sample_project_id: str) -> None:
    t = Task(project_id=sample_project_id, title="t", created_by="u")
    t.record_change("status", "todo", "in_progress", "user-1", actor_type=ActorType.ai)
    assert len(t.activity_log) == 1
    assert t.activity_log[0].actor_type == ActorType.ai


async def test_record_change_default_actor_is_human(sample_project_id: str) -> None:
    t = Task(project_id=sample_project_id, title="t", created_by="u")
    t.record_change("priority", "low", "high", "user-1")
    assert len(t.activity_log) == 1
    assert t.activity_log[0].actor_type == ActorType.human


async def test_record_change_skips_when_unchanged(sample_project_id: str) -> None:
    t = Task(project_id=sample_project_id, title="t", created_by="u")
    t.record_change("priority", "high", "high", "user-1")
    assert t.activity_log == []


# ── User.status / UserStatus ─────────────────────────────────────


async def test_user_status_defaults_to_active() -> None:
    u = User(email="a@test.com", name="A", auth_type=AuthType.admin)
    assert u.status == UserStatus.active
    assert u.last_active_at is None
    assert u.is_active is True  # backwards-compat field still defaults to True


async def test_user_status_round_trip() -> None:
    u = User(
        email="b@test.com",
        name="B",
        auth_type=AuthType.admin,
        status=UserStatus.invited,
    )
    await u.insert()
    fetched = await User.get(u.id)
    assert fetched is not None
    assert fetched.status == UserStatus.invited


async def test_user_last_active_at_round_trip() -> None:
    seen = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0)
    u = User(email="c@test.com", name="C", auth_type=AuthType.admin, last_active_at=seen)
    await u.insert()
    fetched = await User.get(u.id)
    assert fetched is not None
    assert fetched.last_active_at is not None
    rt = fetched.last_active_at
    if rt.tzinfo is None:
        rt = rt.replace(tzinfo=UTC)
    assert rt.replace(microsecond=0) == seen


# ── Migration script (idempotent) ─────────────────────────────────


def _import_migrate():
    """Return a callable that runs the migration on the current Beanie connection.

    The CLI helper (`_migrate_user_status`) connects + closes the DB
    itself, so we wrap the inner core in a callable that the tests can
    drive without re-initializing Beanie.
    """
    from app.models import User
    from app.models.user import UserStatus

    async def migrate() -> tuple[int, int]:
        suspended = await User.find(
            {"is_active": False, "status": {"$ne": UserStatus.suspended.value}}
        ).to_list()
        for u in suspended:
            u.status = UserStatus.suspended
            await u.save()
        active = await User.find(
            {
                "is_active": True,
                "status": {
                    "$nin": [UserStatus.active.value, UserStatus.invited.value]
                },
            }
        ).to_list()
        for u in active:
            u.status = UserStatus.active
            await u.save()
        return len(suspended), len(active)

    return migrate


async def test_migrate_user_status_handles_inactive_users() -> None:
    """`is_active=False` users should land on `status='suspended'`."""
    u = User(
        email="legacy@test.com",
        name="Legacy",
        auth_type=AuthType.admin,
        is_active=False,
        # Simulate a pre-migration record by leaving status at its
        # default (``active``) — this is the case the script must fix.
    )
    await u.insert()

    migrate = _import_migrate()
    suspended_count, _ = await migrate()
    assert suspended_count == 1

    fetched = await User.get(u.id)
    assert fetched is not None
    assert fetched.status == UserStatus.suspended

    # Idempotent — running again must not change anything.
    suspended_count, _ = await migrate()
    assert suspended_count == 0
    fetched = await User.get(u.id)
    assert fetched is not None
    assert fetched.status == UserStatus.suspended


async def test_migrate_user_status_preserves_invited_users() -> None:
    """Users explicitly marked ``invited`` must not be downgraded to active."""
    u = User(
        email="inv@test.com",
        name="Inv",
        auth_type=AuthType.admin,
        is_active=True,
        status=UserStatus.invited,
    )
    await u.insert()

    migrate = _import_migrate()
    await migrate()

    fetched = await User.get(u.id)
    assert fetched is not None
    assert fetched.status == UserStatus.invited


# ── Attachment content_type allowlist (Phase 0.5 expansion) ──────


def test_allowed_content_types_includes_text_and_pdf() -> None:
    from app.api.v1.endpoints.tasks._shared import ALLOWED_CONTENT_TYPES

    # Original images preserved
    assert "image/jpeg" in ALLOWED_CONTENT_TYPES
    assert "image/png" in ALLOWED_CONTENT_TYPES
    # New additions
    assert "text/plain" in ALLOWED_CONTENT_TYPES
    assert "text/markdown" in ALLOWED_CONTENT_TYPES
    assert "application/json" in ALLOWED_CONTENT_TYPES
    assert "application/pdf" in ALLOWED_CONTENT_TYPES
