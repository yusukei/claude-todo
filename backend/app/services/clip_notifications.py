"""Redis Stream publisher for bookmark clip job notifications.

When the API worker creates a bookmark, it publishes a clip request
to the ``clip:jobs`` Redis Stream.  The indexer sidecar (which owns
the clip queue worker) consumes these notifications and enqueues the
bookmark for web clipping.

Mirrors the pattern in :mod:`services.index_notifications`.
"""

from __future__ import annotations

import logging

from ..core.config import settings
from ..core.redis import get_redis

logger = logging.getLogger(__name__)

CLIP_STREAM_KEY = "clip:jobs"
CLIP_CONSUMER_GROUP = "clipper"
CLIP_STREAM_MAX_LEN = 50_000


async def notify_clip_requested(bookmark_id: str) -> None:
    """Publish a clip-requested notification for a bookmark.

    Skipped when ``ENABLE_CLIP_QUEUE`` is True (same-process
    deployment — the clip queue is local, so the API code already
    called ``clip_queue.enqueue()`` directly).
    """
    if settings.ENABLE_CLIP_QUEUE:
        return
    if not bookmark_id:
        raise ValueError("notify_clip_requested: empty bookmark_id")
    redis = get_redis()
    await redis.xadd(
        CLIP_STREAM_KEY,
        {"bookmark_id": bookmark_id},
        maxlen=CLIP_STREAM_MAX_LEN,
        approximate=True,
    )
    logger.debug("clip notification published: bookmark_id=%s", bookmark_id)
