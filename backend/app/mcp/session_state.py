"""Redis-backed MCP session state.

Keys (all in DB ``REDIS_MCP_URI``):

- ``mcp:v1:session:{sid}`` (Hash) — session metadata
- ``mcp:v1:events:{sid}`` (Stream) — server → client notifications
- ``mcp:v1:sse_holder:{sid}`` (String) — single-SSE lock

Invariant: every POST and every SSE keepalive cycle pipelines ``EXPIRE``
on BOTH the session Hash AND the events Stream. Without this, a
long-idle SSE client whose session isn't touched by POSTs loses its
replay buffer (or the whole session) mid-connection.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Literal

from .oauth._redis import get_mcp_redis

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# ── Redis key prefixes ──────────────────────────────────────────

_KEY_SESSION = "mcp:v1:session:"
_KEY_EVENTS = "mcp:v1:events:"
_KEY_SSE_HOLDER = "mcp:v1:sse_holder:"

# ── TTLs (seconds) — see docs/architecture/mcp-stateless-transport.md §3 ──

SESSION_TTL = 3600
SSE_HOLDER_TTL = 60
SSE_HOLDER_REFRESH_INTERVAL = 20  # Redlock 3× margin over 60 s TTL
SSE_TTL_REFRESH_INTERVAL = 30     # keeps session+events alive during long SSE idle
EVENT_STREAM_MAXLEN = 5000


def session_key(sid: str) -> str:
    return f"{_KEY_SESSION}{sid}"


def events_key(sid: str) -> str:
    return f"{_KEY_EVENTS}{sid}"


def sse_holder_key(sid: str) -> str:
    return f"{_KEY_SSE_HOLDER}{sid}"


# ── Session CRUD ────────────────────────────────────────────────


async def create_session(
    *,
    auth_kind: Literal["api_key", "oauth"],
    auth_key_hash: str,
    protocol_init_params_json: str,
    capabilities_json: str,
) -> str:
    """Create a new session Hash, return the session id.

    The session id is a fresh 122-bit UUID4 hex; inbound session id
    headers on initialize are ignored by the caller (session-fixation
    defense).
    """
    sid = uuid.uuid4().hex
    redis: Redis = get_mcp_redis()
    now_ms = int(time.time() * 1000)

    pipe = redis.pipeline(transaction=False)
    pipe.hset(
        session_key(sid),
        mapping={
            "initialized_at_ms": str(now_ms),
            "protocol_init_params": protocol_init_params_json,
            "auth_kind": auth_kind,
            "auth_key_hash": auth_key_hash,
            "capabilities_json": capabilities_json,
        },
    )
    pipe.expire(session_key(sid), SESSION_TTL)
    await pipe.execute()
    return sid


async def load_session(sid: str) -> dict[str, str] | None:
    """Return the session Hash as a dict, or ``None`` if not found."""
    redis: Redis = get_mcp_redis()
    data = await redis.hgetall(session_key(sid))
    return data or None


async def touch_session(sid: str) -> None:
    """Paired TTL refresh: session Hash AND events Stream.

    Called on every POST and every SSE TTL-refresh tick. Both keys
    must be refreshed together so a session with only SSE traffic
    (no POSTs) doesn't lose its events Stream before its session
    Hash, and vice versa.
    """
    redis: Redis = get_mcp_redis()
    pipe = redis.pipeline(transaction=False)
    pipe.expire(session_key(sid), SESSION_TTL)
    pipe.expire(events_key(sid), SESSION_TTL)
    await pipe.execute()


async def delete_session(sid: str) -> None:
    """Delete all keys for a session (idempotent)."""
    redis: Redis = get_mcp_redis()
    pipe = redis.pipeline(transaction=False)
    pipe.delete(session_key(sid))
    pipe.delete(events_key(sid))
    pipe.delete(sse_holder_key(sid))
    await pipe.execute()


# ── Event stream (server → client notifications) ────────────────


async def append_event(sid: str, data_bytes: bytes) -> str:
    """XADD one notification to the per-session Stream.

    Returns the stream entry id, which becomes the client's
    ``Last-Event-ID`` for this event.
    """
    redis: Redis = get_mcp_redis()
    entry_id: str = await redis.xadd(
        events_key(sid),
        {"data": data_bytes},
        maxlen=EVENT_STREAM_MAXLEN,
        approximate=True,
    )
    # Refresh the stream's TTL so it doesn't expire while the session
    # Hash is still being touched.
    await redis.expire(events_key(sid), SESSION_TTL)
    return entry_id


# ── SSE single-holder lock ──────────────────────────────────────
#
# Refresh and release use a read-compare-modify pattern rather than a
# Lua script. The race window (between GET and EXPIRE/DEL) is microseconds
# and our workers are cooperating processes, not adversarial: the worst
# case of a lost race is one extra lock cycle. Avoiding Lua keeps the
# fakeredis-based unit tests simple (no `lupa` dependency).


async def acquire_sse_holder(sid: str, holder_id: str) -> bool:
    """Try to acquire the single-SSE lock for ``sid``.

    Returns True on success, False if another worker already holds it.
    """
    redis: Redis = get_mcp_redis()
    acquired = await redis.set(
        sse_holder_key(sid),
        holder_id,
        nx=True,
        ex=SSE_HOLDER_TTL,
    )
    return bool(acquired)


async def refresh_sse_holder(sid: str, holder_id: str) -> bool:
    """Value-compare EXPIRE refresh; returns True if we still own the lock.

    Note: not strictly atomic (GET then EXPIRE). A micro-window exists
    where another worker could acquire between our GET and EXPIRE —
    they'd still see an immediate expiry-refresh back to 60s. Harmless:
    the lock is ultimately held by whichever worker refreshed last,
    which is what we want.
    """
    redis: Redis = get_mcp_redis()
    current = await redis.get(sse_holder_key(sid))
    if current != holder_id:
        return False
    await redis.expire(sse_holder_key(sid), SSE_HOLDER_TTL)
    return True


async def release_sse_holder_if_owner(sid: str, holder_id: str) -> None:
    """Release the lock only if we still own it."""
    redis: Redis = get_mcp_redis()
    current = await redis.get(sse_holder_key(sid))
    if current == holder_id:
        await redis.delete(sse_holder_key(sid))


# ── Refresh loops used by the SSE handler ───────────────────────


async def run_holder_refresh_loop(sid: str, holder_id: str) -> None:
    """Refresh the SSE holder lock until cancelled.

    Designed to be launched via ``asyncio.create_task`` at the top of
    the SSE handler and cancelled in the handler's ``finally`` block.
    """
    try:
        while True:
            await asyncio.sleep(SSE_HOLDER_REFRESH_INTERVAL)
            still_owner = await refresh_sse_holder(sid, holder_id)
            if not still_owner:
                logger.info(
                    "SSE holder lock for sid=%s lost (taken over); "
                    "refresh loop exiting.",
                    sid[:8],
                )
                return
    except asyncio.CancelledError:
        raise


async def run_ttl_refresh_loop(sid: str) -> None:
    """Keep session Hash + events Stream alive during long SSE idle."""
    try:
        while True:
            await asyncio.sleep(SSE_TTL_REFRESH_INTERVAL)
            await touch_session(sid)
    except asyncio.CancelledError:
        raise
