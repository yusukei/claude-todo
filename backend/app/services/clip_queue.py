"""Bookmark clip queue: asyncio.Queue-based worker with retry and recovery.

Usage:
    from .clip_queue import clip_queue

    await clip_queue.enqueue(bookmark_id)     # Submit a single clip job
    await clip_queue.enqueue_many([id1, id2]) # Submit multiple
    await clip_queue.start()                  # Start worker (called in lifespan)
    await clip_queue.stop()                   # Graceful shutdown
    await clip_queue.recover_pending()        # Re-queue stuck pending/processing
"""

from __future__ import annotations

import asyncio
import logging

from ..models.bookmark import Bookmark, ClipStatus

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_DELAYS = [5, 15]  # seconds between retries
_THROTTLE_SECONDS = 1


class ClipQueue:
    """Manages a single-worker queue for bookmark web clipping."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        """Start the background worker."""
        if self._worker_task is not None:
            return
        self._stopping = False
        self._worker_task = asyncio.create_task(self._worker(), name="clip-queue-worker")
        logger.info("Clip queue worker started")

    async def stop(self) -> None:
        """Gracefully stop the worker after current item completes."""
        if self._worker_task is None:
            return
        self._stopping = True
        # Put sentinel to unblock the queue.get()
        await self._queue.put("")
        try:
            await asyncio.wait_for(self._worker_task, timeout=120)
        except asyncio.TimeoutError:
            self._worker_task.cancel()
            logger.warning("Clip queue worker timed out during shutdown, cancelled")
        self._worker_task = None
        logger.info("Clip queue worker stopped")

    async def enqueue(self, bookmark_id: str) -> None:
        """Add a bookmark ID to the clip queue."""
        await self._queue.put(bookmark_id)
        logger.debug("Enqueued bookmark %s for clipping (queue size: %d)", bookmark_id, self._queue.qsize())

    async def enqueue_many(self, bookmark_ids: list[str]) -> None:
        """Add multiple bookmark IDs to the clip queue."""
        for bid in bookmark_ids:
            await self._queue.put(bid)
        if bookmark_ids:
            logger.info("Enqueued %d bookmarks for clipping", len(bookmark_ids))

    async def recover_pending(self) -> int:
        """Re-queue bookmarks stuck in pending or processing status.

        Called at startup to recover from crashes/restarts.
        Returns the number of re-queued bookmarks.
        """
        stuck = await Bookmark.find(
            {"clip_status": {"$in": [ClipStatus.pending, ClipStatus.processing]}, "is_deleted": False},
        ).sort("+created_at").to_list()

        if not stuck:
            return 0

        # Reset processing → pending before re-queuing
        for bm in stuck:
            if bm.clip_status == ClipStatus.processing:
                bm.clip_status = ClipStatus.pending
                bm.clip_error = ""
                await bm.save_updated()

        ids = [str(bm.id) for bm in stuck]
        await self.enqueue_many(ids)
        logger.info("Recovered %d stuck bookmarks (pending/processing)", len(ids))
        return len(ids)

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    async def _worker(self) -> None:
        """Main worker loop: pull from queue and clip one at a time."""
        while True:
            try:
                bookmark_id = await self._queue.get()
            except asyncio.CancelledError:
                break

            if self._stopping:
                self._queue.task_done()
                break

            try:
                await self._process_one(bookmark_id)
            except Exception:
                logger.exception("Unexpected error in clip worker for bookmark %s", bookmark_id)
            finally:
                self._queue.task_done()

            # Throttle between clips to avoid resource pressure
            await asyncio.sleep(_THROTTLE_SECONDS)

    async def _process_one(self, bookmark_id: str) -> None:
        """Process a single bookmark with retry."""
        for attempt in range(_MAX_RETRIES + 1):
            bm = await Bookmark.get(bookmark_id)
            if not bm or bm.is_deleted:
                logger.debug("Skipping clip for %s (deleted or not found)", bookmark_id)
                return

            try:
                from .bookmark_clip import clip_bookmark
                await clip_bookmark(bm)

                # Re-fetch after clip to get updated state, then index
                bm = await Bookmark.get(bookmark_id)
                if bm and bm.clip_status == ClipStatus.done:
                    from .bookmark_search import index_bookmark
                    await index_bookmark(bm)

                # Publish progress event
                self._publish_progress(bm)
                return  # Success, no retry needed

            except Exception as e:
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Clip attempt %d/%d failed for bookmark %s: %s — retrying in %ds",
                        attempt + 1, _MAX_RETRIES + 1, bookmark_id, e, delay,
                    )
                    # Reset status for retry
                    try:
                        bm = await Bookmark.get(bookmark_id)
                        if bm:
                            bm.clip_status = ClipStatus.pending
                            bm.clip_error = ""
                            await bm.save_updated()
                    except Exception:
                        pass
                    await asyncio.sleep(delay)
                else:
                    logger.exception(
                        "Clip failed after %d attempts for bookmark %s",
                        _MAX_RETRIES + 1, bookmark_id,
                    )
                    try:
                        bm = await Bookmark.get(bookmark_id)
                        if bm:
                            bm.clip_status = ClipStatus.failed
                            bm.clip_error = f"Failed after {_MAX_RETRIES + 1} attempts: {str(e)[:300]}"
                            await bm.save_updated()
                    except Exception:
                        pass

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
            pass


# Module-level singleton
clip_queue = ClipQueue()
