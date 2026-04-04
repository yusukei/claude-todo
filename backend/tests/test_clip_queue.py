"""Tests for bookmark clip queue worker."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.bookmark import Bookmark, ClipStatus
from app.services.clip_queue import ClipQueue


@pytest.mark.asyncio
class TestClipQueue:
    """Unit tests for ClipQueue."""

    async def test_enqueue_and_process(self):
        """Worker picks up enqueued item and processes it."""
        q = ClipQueue()

        mock_bm = MagicMock()
        mock_bm.id = "test123"
        mock_bm.is_deleted = False
        mock_bm.clip_status = ClipStatus.done
        mock_bm.project_id = "proj1"

        with (
            patch.object(Bookmark, "get", new_callable=AsyncMock, return_value=mock_bm),
            patch("app.services.clip_queue.ClipQueue._process_one", new_callable=AsyncMock) as mock_process,
        ):
            await q.start()
            await q.enqueue("test123")

            # Give worker time to process
            await asyncio.sleep(0.1)

            mock_process.assert_awaited_once_with("test123")

            await q.stop()

    async def test_enqueue_many(self):
        q = ClipQueue()
        await q.enqueue_many(["a", "b", "c"])
        assert q.qsize == 3

    async def test_stop_graceful(self):
        """Worker stops gracefully."""
        q = ClipQueue()
        await q.start()
        await q.stop()
        assert q._worker_task is None

    async def test_worker_continues_after_error(self):
        """Worker continues processing after an item fails."""
        q = ClipQueue()
        processed = []

        async def mock_process(bookmark_id):
            if bookmark_id == "fail":
                raise RuntimeError("boom")
            processed.append(bookmark_id)

        q._process_one = mock_process  # type: ignore[assignment]

        with patch("app.services.clip_queue._THROTTLE_SECONDS", 0):
            await q.start()
            await q.enqueue("fail")
            await q.enqueue("ok1")
            await q.enqueue("ok2")

            # Give worker time to process all items
            await asyncio.sleep(0.3)
            await q.stop()

        assert "ok1" in processed
        assert "ok2" in processed

    async def test_skips_deleted_bookmark(self):
        """Deleted bookmarks are skipped."""
        q = ClipQueue()

        mock_bm = MagicMock()
        mock_bm.is_deleted = True

        with (
            patch.object(Bookmark, "get", new_callable=AsyncMock, return_value=mock_bm),
            patch("app.services.bookmark_clip.clip_bookmark", new_callable=AsyncMock) as mock_clip,
        ):
            await q._process_one("deleted123")
            mock_clip.assert_not_awaited()

    async def test_skips_not_found_bookmark(self):
        """Non-existent bookmarks are skipped."""
        q = ClipQueue()

        with (
            patch.object(Bookmark, "get", new_callable=AsyncMock, return_value=None),
            patch("app.services.bookmark_clip.clip_bookmark", new_callable=AsyncMock) as mock_clip,
        ):
            await q._process_one("missing123")
            mock_clip.assert_not_awaited()

    async def test_retry_on_failure(self):
        """Failed clips are retried up to _MAX_RETRIES times."""
        q = ClipQueue()

        call_count = 0
        mock_bm = MagicMock()
        mock_bm.id = "retry123"
        mock_bm.is_deleted = False
        mock_bm.clip_status = ClipStatus.pending
        mock_bm.project_id = "proj1"
        mock_bm.save_updated = AsyncMock()

        async def failing_clip(bm):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("clip error")

        with (
            patch.object(Bookmark, "get", new_callable=AsyncMock, return_value=mock_bm),
            patch("app.services.bookmark_clip.clip_bookmark", side_effect=failing_clip),
            patch("app.services.clip_queue._RETRY_DELAYS", [0, 0]),  # No delay in tests
        ):
            await q._process_one("retry123")

        # 1 initial + 2 retries = 3 total
        assert call_count == 3
        # Last status should be failed
        assert mock_bm.clip_status == ClipStatus.failed

    async def test_recover_pending(self):
        """recover_pending re-queues stuck bookmarks."""
        q = ClipQueue()

        bm_pending = MagicMock()
        bm_pending.id = "p1"
        bm_pending.clip_status = ClipStatus.pending
        bm_pending.save_updated = AsyncMock()

        bm_processing = MagicMock()
        bm_processing.id = "p2"
        bm_processing.clip_status = ClipStatus.processing
        bm_processing.save_updated = AsyncMock()

        mock_find = MagicMock()
        mock_sort = MagicMock()
        mock_sort.to_list = AsyncMock(return_value=[bm_pending, bm_processing])
        mock_find.sort = MagicMock(return_value=mock_sort)

        with patch.object(Bookmark, "find", return_value=mock_find):
            count = await q.recover_pending()

        assert count == 2
        assert q.qsize == 2
        # Processing bookmark should be reset to pending
        assert bm_processing.clip_status == ClipStatus.pending
        bm_processing.save_updated.assert_awaited_once()


@pytest.mark.asyncio
class TestClipQueueIntegration:
    """Integration tests for clip queue with REST API."""

    @pytest_asyncio.fixture(autouse=True)
    async def _mock_clip(self, monkeypatch):
        """Mock clip_queue.enqueue to prevent actual clipping."""
        from app.services.clip_queue import clip_queue

        self._enqueued = []
        original_enqueue = clip_queue.enqueue

        async def mock_enqueue(bookmark_id):
            self._enqueued.append(bookmark_id)

        monkeypatch.setattr(clip_queue, "enqueue", mock_enqueue)

    async def test_create_bookmark_enqueues(self, client, admin_headers, test_project):
        resp = await client.post(
            f"/api/v1/projects/{test_project.id}/bookmarks/",
            json={"url": "https://example.com/queue-test"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        bm_id = resp.json()["id"]
        assert bm_id in self._enqueued

    async def test_reclip_enqueues(self, client, admin_headers, test_project):
        create_resp = await client.post(
            f"/api/v1/projects/{test_project.id}/bookmarks/",
            json={"url": "https://example.com/reclip-test"},
            headers=admin_headers,
        )
        bm_id = create_resp.json()["id"]
        self._enqueued.clear()

        resp = await client.post(
            f"/api/v1/projects/{test_project.id}/bookmarks/{bm_id}/clip",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert bm_id in self._enqueued
