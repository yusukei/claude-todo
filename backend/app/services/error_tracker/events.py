"""Daily-partition event storage for the error tracker.

Event documents are stored in collections named
``error_events_YYYYMMDD`` (UTC date of ``received_at``). Per-project
``retention_days`` cannot be expressed with a single Mongo TTL index
— a shared TTL would force every project to the same cutoff — so the
rotation job drops whole collections after the *longest* retention
window still needs them. Each event carries ``project_id`` so the
drop is safe: a project with a shorter retention simply has its rows
filtered out of query results well before the physical drop.

For ingest we use raw Motor collections rather than Beanie Documents
so that we can mint a new collection name without re-running
``init_beanie``. The Beanie models in ``models.error_tracker`` still
own the aggregate tables (``error_issues`` etc.).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from ...core.database import get_mongo_client
from ...core.config import settings

logger = logging.getLogger(__name__)

_COLL_PREFIX = "error_events_"
# Matches ``error_events_YYYYMMDD`` (no extra suffixes) so we never
# confuse user-created collections with rotation targets.
_COLL_RE = re.compile(rf"^{_COLL_PREFIX}(\d{{8}})$")

# Per-event indexes. Kept minimal: ingest writes happen on the hot
# path so extra indexes trade throughput for nothing — read queries
# almost always filter by ``project_id`` + time or by ``issue_id``.
_EVENT_INDEXES: list[IndexModel] = [
    IndexModel(
        [("project_id", ASCENDING), ("received_at", DESCENDING)],
        name="by_project_recent",
    ),
    IndexModel(
        [("issue_id", ASCENDING), ("received_at", DESCENDING)],
        name="by_issue_recent",
    ),
    IndexModel(
        [("project_id", ASCENDING), ("event_id", ASCENDING)],
        unique=True,
        name="uniq_project_event",
    ),
]


def _get_db() -> AsyncIOMotorDatabase:
    client = get_mongo_client()
    if client is None:  # pragma: no cover — only on misconfigured boot
        raise RuntimeError(
            "MongoDB client not initialised. Call app.core.database.connect()"
        )
    return client[settings.MONGO_DBNAME]


def collection_name_for(when: datetime | date) -> str:
    """Return the partition collection name for the UTC date of ``when``.

    Accepts a ``datetime`` (converted to its UTC date) or a ``date``.
    """
    if isinstance(when, datetime):
        when = when.astimezone(UTC).date() if when.tzinfo else when.date()
    return f"{_COLL_PREFIX}{when:%Y%m%d}"


async def ensure_event_collection(when: datetime | date) -> AsyncIOMotorCollection:
    """Create the daily collection (with indexes) if it doesn't exist.

    ``create_collection`` is idempotent in our usage: we swallow
    ``CollectionInvalid`` from a concurrent creator, then apply the
    index set via ``create_indexes`` (which is itself idempotent).
    """
    from pymongo.errors import CollectionInvalid

    db = _get_db()
    name = collection_name_for(when)
    try:
        await db.create_collection(name)
        logger.info("error-tracker: created partition collection %s", name)
    except CollectionInvalid:
        pass  # already exists — common case after the first write of the day
    coll = db[name]
    await coll.create_indexes(_EVENT_INDEXES)
    return coll


async def get_event_collection_for_date(
    when: datetime | date,
) -> AsyncIOMotorCollection:
    """Return the partition collection, ensuring it is prepared."""
    return await ensure_event_collection(when)


async def list_event_collections() -> list[str]:
    """Return every ``error_events_YYYYMMDD`` collection, ascending by date."""
    db = _get_db()
    names = await db.list_collection_names(filter={"name": {"$regex": _COLL_RE.pattern}})
    # ``list_collection_names`` filter is loose in tests (regex support
    # varies); re-filter client-side to be safe.
    return sorted(n for n in names if _COLL_RE.match(n))


def _coll_date(name: str) -> date | None:
    m = _COLL_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


async def drop_expired_event_collections(
    *,
    now: datetime | None = None,
    max_retention_days: int | None = None,
) -> list[str]:
    """Drop daily collections older than the configured retention window.

    We keep collections covering the **longest** currently-configured
    ``retention_days`` (up to ``max_retention_days``, default 90 to
    match the spec-enforced upper bound). The caller — typically a
    nightly scheduler — is expected to pass ``now`` only in tests
    (via freezegun).

    Returns the list of dropped collection names.
    """
    from ...models.error_tracker import ErrorTrackingConfig

    now = now or datetime.now(UTC)
    if max_retention_days is None:
        max_retention_days = 90  # hard cap from spec §4.1

    # Longest retention currently in use across projects. Projects
    # with shorter retention are filtered at query time; physical
    # delete is driven by the max so no project loses data early.
    longest = 0
    async for p in ErrorTrackingConfig.find_all():
        longest = max(longest, min(p.retention_days, max_retention_days))
    if longest == 0:
        longest = 30  # sensible default when there are no projects yet

    cutoff = (now - timedelta(days=longest)).date()
    dropped: list[str] = []
    db = _get_db()
    for name in await list_event_collections():
        d = _coll_date(name)
        if d is None:
            continue
        if d < cutoff:
            await db.drop_collection(name)
            dropped.append(name)
            logger.info(
                "error-tracker: dropped expired partition %s (cutoff=%s)",
                name,
                cutoff,
            )
    return dropped


__all__ = [
    "collection_name_for",
    "ensure_event_collection",
    "get_event_collection_for_date",
    "list_event_collections",
    "drop_expired_event_collections",
]
