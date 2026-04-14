"""Hot-path counters for Issue event_count / user_count (HLL).

Two problems are solved here together because they share a
``flush`` codepath:

1. **event_count** — incrementing the Mongo document on every
   event causes WriteConflict when the same Issue is noisy. We
   increment a Redis counter instead and flush to Mongo every
   ``FLUSH_INTERVAL_SEC``.

2. **user_count** — distinct user cardinality per Issue. We use
   Redis HyperLogLog (``PFADD``) on the hot path and snapshot
   ``PFCOUNT`` into the Issue doc during flush (§18).

The flush task runs on whatever process owns the worker, not
the API — it's bursty IO that doesn't want to compete with
user-visible requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from ...core.redis import get_redis

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SEC = 30.0

# Redis key templates.
_INC_KEY = "errtrk:issue:{iid}:evt"
_HLL_KEY = "errtrk:issue:{iid}:hll"
_LAST_SEEN_KEY = "errtrk:issue:{iid}:last"
_DIRTY_SET = "errtrk:dirty-issues"  # set of issue_ids needing flush


async def record_event_seen(
    issue_id: str, user_key: str | None, *, when: datetime | None = None
) -> None:
    """Called by the worker for every accepted event.

    Cheap: two or three small Redis ops. The flush loop later
    folds these into a single Mongo update per Issue.
    """
    redis = get_redis()
    when = when or datetime.now(UTC)
    inc_key = _INC_KEY.format(iid=issue_id)
    last_key = _LAST_SEEN_KEY.format(iid=issue_id)
    hll_key = _HLL_KEY.format(iid=issue_id)
    iso = when.isoformat()
    pipe = redis.pipeline()
    pipe.incr(inc_key)
    pipe.set(last_key, iso)
    if user_key:
        pipe.pfadd(hll_key, user_key)
    pipe.sadd(_DIRTY_SET, issue_id)
    await pipe.execute()


async def flush_once() -> int:
    """Drain the dirty set and persist counter deltas to Mongo.

    Returns the number of Issues touched.
    """
    from ...models.error_tracker import ErrorIssue

    redis = get_redis()
    ids = await redis.smembers(_DIRTY_SET)
    if not ids:
        return 0

    touched = 0
    for raw in ids:
        iid = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        inc_key = _INC_KEY.format(iid=iid)
        last_key = _LAST_SEEN_KEY.format(iid=iid)
        hll_key = _HLL_KEY.format(iid=iid)

        # Atomically read + clear the increment counter so we
        # never double-apply a delta across flush windows.
        pipe = redis.pipeline()
        pipe.get(inc_key)
        pipe.delete(inc_key)
        pipe.get(last_key)
        pipe.pfcount(hll_key)
        pipe.srem(_DIRTY_SET, iid)
        delta_raw, _, last_raw, hll_count, _ = await pipe.execute()

        delta = int(delta_raw or 0)
        if delta <= 0 and not last_raw:
            continue

        try:
            from bson import ObjectId
            oid = ObjectId(iid)
        except Exception:
            logger.warning("error-tracker flush: bad issue_id %s", iid)
            continue

        last_seen: datetime | None = None
        if last_raw:
            try:
                s = (
                    last_raw.decode("utf-8")
                    if isinstance(last_raw, bytes)
                    else str(last_raw)
                )
                last_seen = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                last_seen = datetime.now(UTC)

        update: dict[str, Any] = {"$inc": {"event_count": delta}}
        set_: dict[str, Any] = {"user_count": int(hll_count or 0)}
        if last_seen is not None:
            # Use $max so an out-of-order flush doesn't move the
            # timestamp backwards.
            update["$max"] = {"last_seen": last_seen}
        update["$set"] = set_

        try:
            res = await ErrorIssue.get_motor_collection().update_one(
                {"_id": oid}, update
            )
            if res.modified_count:
                touched += 1
        except Exception:
            logger.exception("error-tracker flush failed for issue %s", iid)

    return touched


class CounterFlusher:
    """Background task that periodically calls :func:`flush_once`."""

    def __init__(self, interval: float = FLUSH_INTERVAL_SEC) -> None:
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="error-tracker-counter-flush")
        logger.info("CounterFlusher started (interval=%.1fs)", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping = True
        # Final flush so we don't lose the last window's deltas.
        with contextlib.suppress(Exception):
            await flush_once()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("CounterFlusher stopped")

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise
            if self._stopping:
                break
            try:
                await flush_once()
            except Exception:
                logger.exception("CounterFlusher loop failed; continuing")


counter_flusher = CounterFlusher()

__all__ = ["record_event_seen", "flush_once", "CounterFlusher", "counter_flusher"]
