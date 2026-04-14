"""Token-bucket rate limiter for the error ingest endpoint (T7 / §9).

One bucket per ``ErrorProject.project_id`` per minute. When the
project opts into ``allowed_origin_wildcard``, the effective
limit is clamped to 300/min per v3 decision #1.

We use the simplest correct shape: a Redis ``INCR`` on a
``ratelimit:error:{project}:{minute}`` key with ``EXPIRE 120``
so the key auto-evicts after the window. ``INCR`` is atomic so
there's no double-count under concurrency.

Redis is fail-closed (§9): if Redis is unreachable we reject
the request with 503. A silent fail-open would hide the outage
and let an abusive client overwhelm the worker stream.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ...core.redis import get_redis
from ...models.error_tracker import ErrorProject

logger = logging.getLogger(__name__)

WILDCARD_CAP = 300  # per-minute cap when wildcard origin is enabled


@dataclass
class RateDecision:
    allowed: bool
    remaining: int
    retry_after_sec: int
    limit: int


def effective_limit(project: ErrorProject) -> int:
    """Compute the per-minute cap for this project."""
    limit = project.rate_limit_per_min
    if project.allowed_origin_wildcard:
        limit = min(limit, WILDCARD_CAP)
    return max(1, limit)


async def check(project: ErrorProject) -> RateDecision:
    """Consume one token from the current minute's bucket."""
    limit = effective_limit(project)
    minute = int(time.time() // 60)
    key = f"ratelimit:error:{project.project_id}:{minute}"
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 120)
        count, _ = await pipe.execute()
    except Exception:
        # Fail-closed so the outage surfaces to the operator.
        logger.exception("rate_limit: redis unavailable — rejecting request")
        return RateDecision(
            allowed=False, remaining=0, retry_after_sec=60, limit=limit,
        )

    count = int(count)
    remaining = max(0, limit - count)
    if count > limit:
        return RateDecision(
            allowed=False,
            remaining=0,
            retry_after_sec=60 - int(time.time()) % 60,
            limit=limit,
        )
    return RateDecision(
        allowed=True, remaining=remaining, retry_after_sec=0, limit=limit,
    )


__all__ = ["check", "effective_limit", "RateDecision", "WILDCARD_CAP"]
