"""Redis-backed MCP session registry for cross-worker session tracking.

Tracks which MCP session IDs are currently live (registered by any worker).
This allows workers to distinguish between:
- a session that lives on another worker (cross-worker recovery: create local transport)
- a session that has truly expired/never existed (→ 404)

Key format: ``todo:mcp:registry:{session_id}``
TTL: 1 hour, refreshed on each request handled by the owning worker.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from ..core.config import settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "todo:mcp:registry:"
_SESSION_TTL = 3600  # seconds; refreshed on activity


class RedisSessionRegistry:
    """Cross-worker MCP session registry backed by Redis.

    Each ``ResilientSessionManager`` instance (one per worker process)
    creates a ``RedisSessionRegistry`` pointing at the same Redis DB.
    Because all workers share the same Redis, a session registered by
    worker A is immediately visible to workers B, C, … D.

    Lifecycle
    ---------
    - **register(session_id)** — called when a new transport is created.
      Sets ``todo:mcp:registry:{id}`` with a 1-hour TTL.
    - **touch(session_id)** — refreshes the TTL on each request so
      long-running sessions don't expire mid-flight.
    - **unregister(session_id)** — called when the transport terminates
      (client disconnected, session deleted). Immediately removes the key
      so the next worker that receives a request for this session returns
      404 rather than attempting a pointless recovery.
    - **exists(session_id)** — O(1) check used by the session manager
      when it receives a request for a session not in its local
      ``_server_instances`` map.

    Thread safety
    -------------
    All operations are single Redis commands or pipelined; no additional
    locking is needed beyond what ``ResilientSessionManager`` already
    provides via ``_session_creation_lock``.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        _redis: aioredis.Redis | None = None,
    ) -> None:
        """Initialise the registry.

        Parameters
        ----------
        redis_url:
            Redis connection URL.  Defaults to ``settings.REDIS_MCP_URI``
            (the same DB used by ``RedisEventStore``).
        _redis:
            Inject a pre-existing ``aioredis.Redis`` client.  Used in
            tests to share a ``fakeredis`` instance across registry and
            event-store instances without starting a real Redis server.
            When supplied, ``aclose()`` does *not* close the injected
            client (the caller owns its lifecycle).
        """
        if _redis is not None:
            self._redis: aioredis.Redis = _redis
            self._owns_client = False
        else:
            url = redis_url or settings.REDIS_MCP_URI
            self._redis = aioredis.from_url(url, decode_responses=True)
            self._owns_client = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, session_id: str) -> str:
        return f"{_KEY_PREFIX}{session_id}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register(self, session_id: str) -> None:
        """Mark *session_id* as active in Redis.

        Called by the session manager when a new ``StreamableHTTPServerTransport``
        is created, both for genuinely new sessions and for cross-worker
        recovery sessions.
        """
        await self._redis.setex(self._key(session_id), _SESSION_TTL, "1")
        logger.debug("MCP session registered in registry: %s", session_id)

    async def touch(self, session_id: str) -> None:
        """Refresh the TTL for *session_id*.

        Call once per incoming request on the owning worker to keep the
        registry entry alive for long-running sessions.
        """
        await self._redis.expire(self._key(session_id), _SESSION_TTL)

    async def unregister(self, session_id: str) -> None:
        """Remove *session_id* from the registry.

        Called when the transport terminates cleanly (client disconnect,
        explicit DELETE) so that subsequent requests for this session
        from other workers immediately receive 404 rather than wasting
        a round-trip to create a doomed recovery transport.
        """
        await self._redis.delete(self._key(session_id))
        logger.debug("MCP session unregistered from registry: %s", session_id)

    async def exists(self, session_id: str) -> bool:
        """Return ``True`` if *session_id* is registered by *any* worker."""
        return bool(await self._redis.exists(self._key(session_id)))

    async def aclose(self) -> None:
        """Close the underlying Redis connection if we own it."""
        if self._owns_client:
            await self._redis.aclose()
