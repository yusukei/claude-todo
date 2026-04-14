"""Background worker that consumes the error ingest stream.

Mirrors the shape of ``indexer_consumer.py``: a single consumer
group with one consumer per process, ``XAUTOCLAIM`` on startup to
pick up whatever a crashed predecessor left behind, and
``XREADGROUP`` for new entries.

This module only owns the **transport** in T4: parse the stream
entry, dispatch to a handler, ACK on success. The actual
fingerprint + Issue upsert + PII scrubbing lives in T5/T6 and
plugs into ``_dispatch`` via a module-level callable.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any, Awaitable, Callable

from ...core.config import settings
from .stream import CONSUMER_GROUP, STREAM_KEY

logger = logging.getLogger(__name__)


# ── Dispatch hook ─────────────────────────────────────────────
#
# T5 will register the real handler here. Until then the worker
# runs the placeholder which persists a minimal raw event to the
# daily partition collection so end-to-end ingest tests can
# verify the round-trip without waiting for T5.

EventHandler = Callable[[dict[str, str]], Awaitable[None]]

_handler: EventHandler | None = None


def set_event_handler(handler: EventHandler) -> None:
    """Register the T5 handler. Last registration wins."""
    global _handler
    _handler = handler


# ── Startup-time reclaim tuning ───────────────────────────────

CLAIM_MIN_IDLE_MS = 5 * 60 * 1000  # 5 minutes — same as indexer consumer


class ErrorTrackerWorker:
    """Single-process consumer of ``errors:ingest``."""

    def __init__(self) -> None:
        self._consumer_name = f"error-worker-{uuid.uuid4().hex[:12]}"
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._redis: Any = None

    async def start(self) -> None:
        if self._task is not None:
            return
        from ...core.redis import get_redis

        self._redis = get_redis()
        await self._ensure_group()
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="error-tracker-worker")
        logger.info(
            "ErrorTrackerWorker started (consumer=%s, stream=%s, group=%s)",
            self._consumer_name,
            STREAM_KEY,
            CONSUMER_GROUP,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping = True
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("ErrorTrackerWorker stopped")

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                STREAM_KEY, CONSUMER_GROUP, id="$", mkstream=True,
            )
            logger.info(
                "Created consumer group %s on %s", CONSUMER_GROUP, STREAM_KEY,
            )
        except Exception as e:
            if "BUSYGROUP" in str(e):
                return
            raise

    async def _run(self) -> None:
        await self._reclaim_stale()
        batch = settings.ERROR_TRACKER_WORKER_BATCH
        block = settings.ERROR_TRACKER_WORKER_BLOCK_MS
        while not self._stopping:
            try:
                resp = await self._redis.xreadgroup(
                    CONSUMER_GROUP,
                    self._consumer_name,
                    {STREAM_KEY: ">"},
                    count=batch,
                    block=block,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "ErrorTrackerWorker xreadgroup failed; backing off",
                )
                await asyncio.sleep(1.0)
                continue
            if not resp:
                continue
            for _stream_name, entries in resp:
                for entry_id, fields in entries:
                    await self._dispatch(entry_id, fields)

    async def _reclaim_stale(self) -> None:
        try:
            start_id = "0-0"
            while True:
                result = await self._redis.xautoclaim(
                    STREAM_KEY,
                    CONSUMER_GROUP,
                    self._consumer_name,
                    min_idle_time=CLAIM_MIN_IDLE_MS,
                    start_id=start_id,
                    count=settings.ERROR_TRACKER_WORKER_BATCH,
                )
                if not isinstance(result, (tuple, list)) or len(result) < 2:
                    return
                next_start, reclaimed = result[0], result[1]
                if not reclaimed:
                    return
                for entry_id, fields in reclaimed:
                    logger.info(
                        "ErrorTrackerWorker reclaimed stale %s from previous consumer",
                        entry_id,
                    )
                    await self._dispatch(entry_id, fields)
                if next_start in (b"0-0", "0-0", 0):
                    return
                start_id = (
                    next_start.decode("utf-8")
                    if isinstance(next_start, bytes)
                    else next_start
                )
        except Exception:
            logger.exception(
                "ErrorTrackerWorker xautoclaim failed; continuing with new entries",
            )

    async def _dispatch(self, entry_id: Any, fields: dict[Any, Any]) -> None:
        def _s(v: Any) -> str:
            return v.decode("utf-8") if isinstance(v, bytes) else str(v)

        norm: dict[str, str] = {_s(k): _s(v) for k, v in fields.items()}
        handler = _handler or _default_handler

        try:
            await handler(norm)
        except Exception:
            # Do NOT ACK — next XAUTOCLAIM cycle reclaims it.
            logger.exception(
                "error-tracker: handler failed for entry %s (project=%s event=%s); "
                "leaving pending for retry",
                entry_id,
                norm.get("project_id", "?"),
                norm.get("event_id", "?"),
            )
            return

        try:
            await self._redis.xack(STREAM_KEY, CONSUMER_GROUP, entry_id)
        except Exception:
            logger.exception(
                "error-tracker: XACK failed for %s; entry will be retried",
                entry_id,
            )


# ── Default placeholder handler (T4 only) ─────────────────────
#
# Stores the raw event into the day's partition without any
# fingerprinting / aggregation. This lets the ingest path run
# end-to-end immediately; T5 replaces it via ``set_event_handler``.


async def _default_handler(entry: dict[str, str]) -> None:
    from datetime import UTC, datetime

    import orjson

    from .events import get_event_collection_for_date

    if entry.get("item_type") != "event":
        # Sessions / client_reports are handled upstream. If one
        # leaked into the stream (future bug) we silently skip it.
        return

    received_raw = entry.get("received_at") or datetime.now(UTC).isoformat()
    try:
        received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
    except ValueError:
        received_at = datetime.now(UTC)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)

    try:
        payload = orjson.loads(entry.get("payload", "{}"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"raw": entry.get("payload")}

    coll = await get_event_collection_for_date(received_at)
    doc = {
        "event_id": entry.get("event_id", ""),
        "project_id": entry.get("project_id", ""),
        "error_project_id": entry.get("error_project_id", ""),
        "received_at": received_at,
        "platform": payload.get("platform", "javascript"),
        "level": payload.get("level", "error"),
        "message": payload.get("message"),
        "exception": payload.get("exception"),
        "breadcrumbs": payload.get("breadcrumbs"),
        "request": payload.get("request"),
        "user": payload.get("user"),
        "tags": payload.get("tags"),
        "contexts": payload.get("contexts"),
        "release": payload.get("release"),
        "environment": payload.get("environment"),
        "sdk": payload.get("sdk"),
        "client_ip": entry.get("client_ip"),
        "user_agent": entry.get("user_agent"),
        "symbolicated": False,
        "fingerprint": None,  # filled in T5
        "issue_id": None,  # filled in T5
    }
    try:
        await coll.insert_one(doc)
    except Exception as exc:
        # Duplicate event_id on ``(project_id, event_id)`` unique
        # index is expected (client retries). Swallow — spec §4.5.
        if "E11000" in str(exc) or "duplicate" in str(exc).lower():
            logger.debug(
                "error-tracker: duplicate event %s for project=%s — idempotent skip",
                doc["event_id"],
                doc["project_id"],
            )
            return
        raise


# Module-level singleton (pattern matches indexer_consumer).
error_tracker_worker = ErrorTrackerWorker()


__all__ = [
    "ErrorTrackerWorker",
    "error_tracker_worker",
    "set_event_handler",
    "EventHandler",
]
