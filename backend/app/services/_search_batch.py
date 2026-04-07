"""Shared batch-commit helper for Tantivy-backed search indexers.

Tantivy's `commit()` is fsync-heavy; calling it on every single upsert
makes write-heavy paths (e.g. bookmark imports, bulk task creation)
extremely slow. This mixin coalesces commits along two axes:

- **Count**: commit after `BATCH_MAX_PENDING` queued writes
- **Time**: commit when more than `BATCH_INTERVAL_S` seconds have passed
  since the last commit

A background `flush_loop()` coroutine ensures the final partial batch
gets committed even when writes go quiet, and `flush()` is called on
shutdown to drain anything still in the buffer.

Hosts must:
1. Set `self._writer` (tantivy IndexWriter) and `self._lock` (threading.Lock)
   before calling `_init_batch_state()`.
2. Replace direct `self._writer.commit()` calls in single-document
   upsert/delete paths with `self._maybe_commit_locked()`.
3. Keep direct `commit()` in bulk-rebuild paths — those already batch
   internally, and forcing them through this debouncer would just add
   overhead.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class BatchCommitMixin:
    BATCH_MAX_PENDING: int = 100
    BATCH_INTERVAL_S: float = 2.0

    # These attrs are set by the subclass before _init_batch_state() runs.
    _writer: object  # tantivy.IndexWriter (kept loose to avoid import cost)
    _lock: object   # threading.Lock

    def _init_batch_state(self) -> None:
        self._pending_writes: int = 0
        self._last_commit_at: float = time.monotonic()

    def _maybe_commit_locked(self, *, force: bool = False) -> None:
        """Commit if the count or time threshold has been reached.

        The caller must already hold ``self._lock`` and have completed any
        ``add_document`` / ``delete_documents`` calls before invoking this.
        """
        self._pending_writes += 1
        now = time.monotonic()
        if (
            force
            or self._pending_writes >= self.BATCH_MAX_PENDING
            or (now - self._last_commit_at) >= self.BATCH_INTERVAL_S
        ):
            self._writer.commit()  # type: ignore[attr-defined]
            self._pending_writes = 0
            self._last_commit_at = now

    def flush(self) -> None:
        """Synchronously commit any pending writes (acquires the lock).

        Safe to call from a worker thread via ``asyncio.to_thread`` or
        directly from synchronous shutdown code.
        """
        with self._lock:  # type: ignore[attr-defined]
            if self._pending_writes:
                try:
                    self._writer.commit()  # type: ignore[attr-defined]
                except Exception as e:
                    logger.warning("flush(): commit failed: %s", e)
                    return
                self._pending_writes = 0
                self._last_commit_at = time.monotonic()

    async def flush_loop(self, interval_s: float | None = None) -> None:
        """Background task that flushes pending writes on a fixed cadence.

        Started by the application lifespan once per indexer. Cancelling
        the task triggers a final flush so the buffer doesn't survive a
        graceful shutdown.
        """
        wait = interval_s if interval_s is not None else self.BATCH_INTERVAL_S
        try:
            while True:
                await asyncio.sleep(wait)
                try:
                    await asyncio.to_thread(self.flush)
                except Exception as e:
                    logger.warning("flush_loop iteration error: %s", e)
        except asyncio.CancelledError:
            try:
                await asyncio.to_thread(self.flush)
            except Exception as e:
                logger.warning("flush_loop final flush error: %s", e)
            raise
