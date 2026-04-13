"""Bookmark clip queue: concurrent workers + Redis Stream consumer + periodic sweep.

Architecture:
    - Multiple concurrent workers process clips from an asyncio.Queue
    - Redis Stream consumer picks up notifications from API workers
    - Periodic DB sweep catches any missed bookmarks (fallback)
    - Playwright BrowserPool reuses a single browser with multiple pages

Usage:
    from .clip_queue import clip_queue

    await clip_queue.enqueue(bookmark_id)     # Submit a single clip job
    await clip_queue.enqueue_many([id1, id2]) # Submit multiple
    await clip_queue.start()                  # Start workers (called in lifespan)
    await clip_queue.stop()                   # Graceful shutdown
    await clip_queue.recover_pending()        # Re-queue stuck pending/processing
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from ..models.bookmark import Bookmark, ClipStatus

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAYS = [5, 15]  # seconds between retries
_THROTTLE_SECONDS = 0.5
_CONCURRENCY = 3  # concurrent clip workers
_SWEEP_INTERVAL_SECONDS = 60  # DB sweep interval
_SWEEP_BATCH_SIZE = 50  # max items per sweep
_CONSUMER_READ_BLOCK_MS = 1000
_CONSUMER_READ_BATCH = 16


class ClipQueue:
    """Manages concurrent workers for bookmark web clipping."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
        self._sweep_task: asyncio.Task | None = None
        self._consumer_task: asyncio.Task | None = None
        self._stopping = False
        self._processing_ids: set[str] = set()  # dedup guard
        self._pool = None  # BrowserPool, set in start()
        self._consumer_name = f"clipper-{uuid.uuid4().hex[:12]}"
        self._redis: Any = None

    async def start(self) -> None:
        """Start workers, sweep loop, and Redis Stream consumer."""
        if self._worker_tasks:
            return
        self._stopping = False

        # Lazy-import to avoid circular dependency at module load
        from .clip_playwright import BrowserPool

        self._pool = BrowserPool(max_pages=_CONCURRENCY)

        # Start concurrent worker tasks
        for i in range(_CONCURRENCY):
            task = asyncio.create_task(
                self._worker(i), name=f"clip-worker-{i}",
            )
            self._worker_tasks.append(task)

        # Start periodic DB sweep
        self._sweep_task = asyncio.create_task(
            self._sweep_loop(), name="clip-sweep",
        )

        # Start Redis Stream consumer (multi-worker notification)
        try:
            from ..core.redis import get_redis

            self._redis = get_redis()
            await self._ensure_consumer_group()
            self._consumer_task = asyncio.create_task(
                self._consume_stream(), name="clip-consumer",
            )
            logger.info(
                "Clip queue started: %d workers, sweep=%ds, Redis consumer=%s",
                _CONCURRENCY, _SWEEP_INTERVAL_SECONDS, self._consumer_name,
            )
        except Exception:
            logger.warning(
                "Clip queue started WITHOUT Redis consumer (Redis unavailable); "
                "relying on periodic sweep only",
                exc_info=True,
            )
            logger.info(
                "Clip queue started: %d workers, sweep=%ds (no Redis consumer)",
                _CONCURRENCY, _SWEEP_INTERVAL_SECONDS,
            )

    async def stop(self) -> None:
        """Gracefully stop all workers and background tasks."""
        if not self._worker_tasks:
            return
        self._stopping = True

        # Unblock workers waiting on empty queue
        for _ in self._worker_tasks:
            await self._queue.put("")

        # Cancel sweep and consumer
        if self._sweep_task:
            self._sweep_task.cancel()
        if self._consumer_task:
            self._consumer_task.cancel()

        # Wait for all tasks (with timeout)
        all_tasks = self._worker_tasks[:]
        if self._sweep_task:
            all_tasks.append(self._sweep_task)
        if self._consumer_task:
            all_tasks.append(self._consumer_task)

        for t in all_tasks:
            try:
                await asyncio.wait_for(t, timeout=120)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t

        self._worker_tasks.clear()
        self._sweep_task = None
        self._consumer_task = None

        # Shutdown browser pool
        if self._pool:
            await self._pool.shutdown()
            self._pool = None

        logger.info("Clip queue stopped")

    async def enqueue(self, bookmark_id: str) -> None:
        """Add a bookmark ID to the clip queue (dedup-safe).

        On the API worker (ENABLE_CLIP_QUEUE=False) this also publishes
        a Redis Stream notification so the indexer sidecar picks it up.
        On the indexer itself the notification is a no-op.
        """
        # Publish cross-worker notification (no-op on same-process)
        try:
            from .clip_notifications import notify_clip_requested

            await notify_clip_requested(bookmark_id)
        except Exception:
            logger.warning(
                "Failed to publish clip notification for %s", bookmark_id,
                exc_info=True,
            )

        if bookmark_id in self._processing_ids:
            return
        await self._queue.put(bookmark_id)
        logger.debug(
            "Enqueued bookmark %s (queue size: %d)",
            bookmark_id, self._queue.qsize(),
        )

    async def enqueue_many(self, bookmark_ids: list[str]) -> None:
        """Add multiple bookmark IDs to the clip queue."""
        # Publish cross-worker notifications (no-op on same-process)
        try:
            from .clip_notifications import notify_clip_requested

            for bid in bookmark_ids:
                await notify_clip_requested(bid)
        except Exception:
            logger.warning(
                "Failed to publish clip notifications for batch",
                exc_info=True,
            )

        added = 0
        for bid in bookmark_ids:
            if bid not in self._processing_ids:
                await self._queue.put(bid)
                added += 1
        if added:
            logger.info("Enqueued %d bookmarks for clipping", added)

    async def recover_pending(self) -> int:
        """Re-queue bookmarks stuck in pending or processing status.

        Called at startup to recover from crashes/restarts.
        Does NOT publish Redis notifications (this runs on the indexer
        which owns the queue locally).
        Returns the number of re-queued bookmarks.
        """
        stuck = await Bookmark.find(
            {
                "clip_status": {"$in": [ClipStatus.pending, ClipStatus.processing]},
                "is_deleted": False,
            },
        ).sort("+created_at").limit(5000).to_list()

        if not stuck:
            return 0

        # Reset processing → pending before re-queuing
        for bm in stuck:
            if bm.clip_status == ClipStatus.processing:
                bm.clip_status = ClipStatus.pending
                bm.clip_error = ""
                await bm.save_updated()

        ids = [str(bm.id) for bm in stuck]
        # Direct queue insert — skip notifications (we ARE the consumer)
        added = 0
        for bid in ids:
            if bid not in self._processing_ids:
                await self._queue.put(bid)
                added += 1
        logger.info("Recovered %d stuck bookmarks (pending/processing)", added)
        return added

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    # ── Workers ───────────────────────────────────────────────

    async def _worker(self, worker_id: int) -> None:
        """Worker loop: pull from queue and clip."""
        while True:
            try:
                bookmark_id = await self._queue.get()
            except asyncio.CancelledError:
                break

            if self._stopping or not bookmark_id:
                self._queue.task_done()
                break

            try:
                await self._process_one(bookmark_id, worker_id)
            except Exception:
                logger.exception(
                    "Worker %d: unexpected error for bookmark %s",
                    worker_id, bookmark_id,
                )
            finally:
                self._processing_ids.discard(bookmark_id)
                self._queue.task_done()

            await asyncio.sleep(_THROTTLE_SECONDS)

    async def _process_one(self, bookmark_id: str, worker_id: int = 0) -> None:
        """Process a single bookmark with retry."""
        self._processing_ids.add(bookmark_id)

        for attempt in range(_MAX_RETRIES + 1):
            bm = await Bookmark.get(bookmark_id)
            if not bm or bm.is_deleted:
                logger.debug("Skipping clip for %s (deleted or not found)", bookmark_id)
                return

            try:
                from .bookmark_clip import clip_bookmark

                await clip_bookmark(bm, browser_pool=self._pool)

                # Re-fetch to get updated state, then index
                bm = await Bookmark.get(bookmark_id)
                if bm and bm.clip_status == ClipStatus.done:
                    from .bookmark_search import index_bookmark

                    await index_bookmark(bm)

                self._publish_progress(bm)
                return  # Success

            except Exception as e:
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Worker %d: clip attempt %d/%d failed for %s: %s — "
                        "retrying in %ds",
                        worker_id, attempt + 1, _MAX_RETRIES + 1,
                        bookmark_id, e, delay,
                    )
                    try:
                        bm = await Bookmark.get(bookmark_id)
                        if bm:
                            bm.clip_status = ClipStatus.pending
                            bm.clip_error = ""
                            await bm.save_updated()
                    except Exception:
                        logger.warning(
                            "Failed to reset clip_status for retry: %s",
                            bookmark_id, exc_info=True,
                        )
                    await asyncio.sleep(delay)
                else:
                    logger.exception(
                        "Worker %d: clip failed after %d attempts for %s",
                        worker_id, _MAX_RETRIES + 1, bookmark_id,
                    )
                    try:
                        bm = await Bookmark.get(bookmark_id)
                        if bm:
                            bm.clip_status = ClipStatus.failed
                            bm.clip_error = (
                                f"Failed after {_MAX_RETRIES + 1} attempts: "
                                f"{str(e)[:300]}"
                            )
                            await bm.save_updated()
                    except Exception:
                        logger.exception(
                            "Failed to persist clip_status=failed for %s",
                            bookmark_id,
                        )

    # ── Periodic DB sweep ─────────────────────────────────────

    async def _sweep_loop(self) -> None:
        """Periodically find pending bookmarks not in the queue."""
        while not self._stopping:
            try:
                await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
                if self._stopping:
                    break
                await self._sweep_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Clip sweep error; continuing")
                await asyncio.sleep(5)

    async def _sweep_once(self) -> None:
        """Single sweep: find pending bookmarks and enqueue missing ones."""
        pending = await Bookmark.find(
            {"clip_status": ClipStatus.pending, "is_deleted": False},
        ).sort("+created_at").limit(_SWEEP_BATCH_SIZE).to_list()

        if not pending:
            return

        added = 0
        for bm in pending:
            bid = str(bm.id)
            if bid not in self._processing_ids:
                await self._queue.put(bid)
                added += 1

        if added:
            logger.info("Sweep: enqueued %d pending bookmarks", added)

    # ── Redis Stream consumer ─────────────────────────────────

    async def _ensure_consumer_group(self) -> None:
        """Create Redis consumer group for clip:jobs stream."""
        from .clip_notifications import CLIP_CONSUMER_GROUP, CLIP_STREAM_KEY

        try:
            await self._redis.xgroup_create(
                CLIP_STREAM_KEY, CLIP_CONSUMER_GROUP,
                id="$", mkstream=True,
            )
            logger.info(
                "Created consumer group %s on %s",
                CLIP_CONSUMER_GROUP, CLIP_STREAM_KEY,
            )
        except Exception as e:
            if "BUSYGROUP" in str(e):
                return
            raise

    async def _consume_stream(self) -> None:
        """Read clip job notifications from Redis Stream."""
        from .clip_notifications import CLIP_CONSUMER_GROUP, CLIP_STREAM_KEY

        while not self._stopping:
            try:
                resp = await self._redis.xreadgroup(
                    CLIP_CONSUMER_GROUP,
                    self._consumer_name,
                    {CLIP_STREAM_KEY: ">"},
                    count=_CONSUMER_READ_BATCH,
                    block=_CONSUMER_READ_BLOCK_MS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Clip consumer xreadgroup failed; backing off")
                await asyncio.sleep(2.0)
                continue

            if not resp:
                continue

            for _stream_name, entries in resp:
                for entry_id, fields in entries:
                    await self._dispatch_stream_entry(entry_id, fields)

    async def _dispatch_stream_entry(
        self, entry_id: Any, fields: dict[Any, Any],
    ) -> None:
        """Process a single clip:jobs stream entry."""
        from .clip_notifications import CLIP_CONSUMER_GROUP, CLIP_STREAM_KEY

        def _s(v: Any) -> str:
            return v.decode("utf-8") if isinstance(v, bytes) else str(v)

        norm = {_s(k): _s(v) for k, v in fields.items()}
        bookmark_id = norm.get("bookmark_id")

        if not bookmark_id:
            logger.warning(
                "Dropping malformed clip notification %s: %r", entry_id, norm,
            )
            await self._redis.xack(CLIP_STREAM_KEY, CLIP_CONSUMER_GROUP, entry_id)
            return

        # Direct queue insert — skip enqueue() to avoid re-publishing notification
        if bookmark_id not in self._processing_ids:
            await self._queue.put(bookmark_id)
        await self._redis.xack(CLIP_STREAM_KEY, CLIP_CONSUMER_GROUP, entry_id)

    # ── SSE progress ──────────────────────────────────────────

    def _publish_progress(self, bm: Bookmark | None) -> None:
        """Fire-and-forget SSE progress event."""
        if not bm:
            return
        try:
            from .events import publish_event

            asyncio.ensure_future(publish_event(
                bm.project_id,
                "bookmark:clipped",
                {"bookmark_id": str(bm.id), "status": bm.clip_status},
            ))
        except Exception:
            logger.warning(
                "Failed to publish clip progress for %s",
                bm.id, exc_info=True,
            )


# Module-level singleton
clip_queue = ClipQueue()
