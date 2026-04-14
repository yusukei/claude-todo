"""Redis Stream producer for the error tracker ingest path.

The Ingest API writes raw event payloads onto this stream and
returns ``200 OK`` immediately (spec §2). The worker in
:mod:`services.error_tracker.worker` consumes the stream,
parses the payload, scrubs PII, computes the fingerprint and
persists to Mongo.

We keep the producer dead simple and synchronous: if ``XADD``
fails we raise, and the HTTP handler turns that into a 503. Per
CLAUDE.md "no silent fallbacks" — masking a Redis outage with a
200 OK would drop events on the floor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import orjson

from ...core.config import settings
from ...core.redis import get_redis

logger = logging.getLogger(__name__)


# Stream and consumer group names. Kept module-level so the worker
# imports the same constants.
STREAM_KEY = "errors:ingest"
CONSUMER_GROUP = "error-tracker"


@dataclass
class EnqueuedEvent:
    """Minimal metadata returned to the HTTP handler.

    ``stream_id`` is the Redis Stream id (``<ms>-<seq>``). We log
    it along with the public-facing ``event_id`` so operators can
    correlate SDK reports with stream entries.
    """

    event_id: str
    stream_id: str


async def enqueue_event(
    *,
    project_id: str,
    error_project_id: str,
    event_id: str,
    payload: bytes,
    received_at_iso: str,
    item_type: str = "event",
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> EnqueuedEvent:
    """Enqueue a single event payload.

    ``payload`` is the raw JSON bytes from the envelope — we push
    it through unmodified so the worker sees exactly what the SDK
    sent (important for fingerprint reproducibility in tests).

    ``client_ip`` and ``user_agent`` are captured **here** rather
    than the worker because they originate from the HTTP request
    and are gone by the time the worker picks the entry up.
    """
    redis = get_redis()
    fields: dict[str, str] = {
        "project_id": project_id,
        "error_project_id": error_project_id,
        "event_id": event_id,
        "item_type": item_type,
        "received_at": received_at_iso,
        # Payload stays bytes but redis-py happily accepts them as
        # a field value; it round-trips through the wire unchanged.
        # We store as base64-ish string? No — redis-py handles bytes
        # when decode_responses=False. With decode_responses=True
        # (our default) we must decode. Payload is JSON, so utf-8
        # is safe.
        "payload": payload.decode("utf-8", errors="replace"),
    }
    if client_ip:
        fields["client_ip"] = client_ip
    if user_agent:
        fields["user_agent"] = user_agent

    stream_id = await redis.xadd(
        STREAM_KEY,
        fields,
        maxlen=settings.ERROR_TRACKER_STREAM_MAXLEN,
        approximate=True,
    )
    sid = stream_id.decode("utf-8") if isinstance(stream_id, bytes) else str(stream_id)
    logger.debug(
        "error-tracker: enqueued event project=%s event_id=%s stream=%s",
        project_id,
        event_id,
        sid,
    )
    return EnqueuedEvent(event_id=event_id, stream_id=sid)


def json_dumps(obj: Any) -> bytes:
    """Canonical JSON encoder for things we push to the stream."""
    return orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_NAIVE_UTC)


__all__ = [
    "STREAM_KEY",
    "CONSUMER_GROUP",
    "EnqueuedEvent",
    "enqueue_event",
    "json_dumps",
]
