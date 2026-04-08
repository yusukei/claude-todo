"""ChatConnectionManager — multi-worker safe per-session WebSocket fan-out.

Each worker still tracks its own ``session_id → set[WebSocket]``
mapping (a WebSocket only lives in the process that accepted it),
but the **fan-out itself** goes through Redis pub/sub so a message
published by worker A reaches every browser regardless of which
worker holds the chat WebSocket.

## Architecture

- Channel: ``chat:session:{session_id}`` (one per session)
- Each worker runs a single background **pattern subscriber** on
  ``chat:session:*``. On each incoming message it parses the
  channel name to recover ``session_id``, then dispatches the
  payload to the local WebSocket set for that session. This
  eliminates the per-session subscribe / unsubscribe dance.
- ``broadcast(session_id, message)`` becomes a single
  ``await redis.publish(channel, json)`` — the worker that
  published is itself subscribed (loopback), so it also fans
  the message out to its locally-attached browsers without any
  in-process special case.
- ``connect`` / ``disconnect`` remain process-local: a WebSocket
  is owned by exactly one worker, no shared state required.

## Why pattern subscribe and not per-session

The previous design (in-process ``dict[session_id, set[WebSocket]]``
with no Redis) failed because worker A's broadcast never reached
worker B's WebSockets. A naive fix would be ``redis.publish`` plus
per-session subscribe / unsubscribe in ``connect`` / ``disconnect``,
but that means every browser join/leave round-trips to Redis with
a state-changing command. Pattern subscribe (``PSUBSCRIBE``) lets
us do **one** subscribe per worker for the entire chat surface and
filter in memory — fewer round-trips, simpler lifecycle, identical
fan-out semantics.

## Lifecycle

``start()`` is called from the FastAPI lifespan after
``init_redis()``. It launches the subscriber task and is
idempotent. ``stop()`` cancels the task and unsubscribes the
pattern. Tests do not need to call ``start()`` if they only
exercise the local connect / disconnect bookkeeping.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# Channel layout — keep prefixes as module constants so any future
# ops tooling reads from a single source of truth.
CHANNEL_PREFIX = "chat:session:"
CHANNEL_PATTERN = f"{CHANNEL_PREFIX}*"


def _channel_for(session_id: str) -> str:
    return f"{CHANNEL_PREFIX}{session_id}"


def _session_id_from_channel(channel: str) -> str | None:
    if not channel.startswith(CHANNEL_PREFIX):
        return None
    return channel[len(CHANNEL_PREFIX):]


class ChatConnectionManager:
    """Manages WebSocket connections per chat session for multi-browser fan-out.

    The local connection map is process-local (a WebSocket is
    bound to one worker). The cross-worker fan-out runs through
    Redis pub/sub via the background subscriber task started by
    :meth:`start`.
    """

    def __init__(self) -> None:
        # session_id → set of WebSocket connections (process-local)
        self._connections: dict[str, set[WebSocket]] = {}
        self._subscriber_task: asyncio.Task | None = None
        self._stopping = False
        # Resolved lazily by start() so tests that don't need
        # cross-worker fan-out can construct the manager without
        # any Redis client.
        self._redis: aioredis.Redis | None = None

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self, *, redis_client: aioredis.Redis | None = None) -> None:
        """Launch the cross-worker subscriber task. Idempotent."""
        if self._subscriber_task is not None:
            return
        if redis_client is not None:
            self._redis = redis_client
        if self._redis is None:
            from ..core.redis import get_redis
            self._redis = get_redis()
        self._stopping = False
        self._subscriber_task = asyncio.create_task(
            self._subscriber_loop(),
            name="chat-manager-subscriber",
        )
        logger.info("ChatConnectionManager subscriber started")

    async def stop(self) -> None:
        """Cancel the subscriber task and unsubscribe the pattern."""
        if self._subscriber_task is None:
            return
        self._stopping = True
        self._subscriber_task.cancel()
        try:
            await self._subscriber_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "ChatConnectionManager subscriber raised during stop",
            )
        self._subscriber_task = None
        logger.info("ChatConnectionManager subscriber stopped")

    # ── Local connection bookkeeping ────────────────────────────

    def connect(self, session_id: str, ws: WebSocket) -> None:
        if session_id not in self._connections:
            self._connections[session_id] = set()
        self._connections[session_id].add(ws)

    def disconnect(self, session_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(session_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._connections[session_id]

    def get_session_ids(self) -> list[str]:
        return list(self._connections.keys())

    def connection_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, set()))

    # ── Cross-worker fan-out ────────────────────────────────────

    async def broadcast(self, session_id: str, message: dict) -> None:
        """Send ``message`` to every browser attached to ``session_id``.

        The publish is best-effort: if Redis is unavailable we fall
        back to local-only fan-out so a single Redis hiccup does not
        completely break the chat for browsers attached to **this**
        worker. The fallback is loud (``logger.exception``) so the
        operator sees the degradation.

        With Redis up, the loopback delivers the message back to
        this worker via the subscriber, which then runs the local
        fan-out. The publisher does NOT also fan out locally —
        otherwise every message would be delivered twice to
        same-worker browsers.
        """
        payload = json.dumps(message, default=str)
        channel = _channel_for(session_id)
        if self._redis is None:
            # ``start()`` was not called yet (or test mode without
            # the lifespan). Fall back to local fan-out so the test
            # still observes its own broadcasts.
            await self._fanout_local(session_id, payload)
            return
        try:
            await self._redis.publish(channel, payload)
        except Exception:
            logger.exception(
                "Redis publish failed for chat session %s; "
                "falling back to local-only fan-out",
                session_id,
            )
            await self._fanout_local(session_id, payload)

    async def _fanout_local(self, session_id: str, payload: str) -> None:
        """Send ``payload`` to every locally-connected browser for the session.

        Failed sends remove the WebSocket from the local set so a
        stuck browser does not block the rest of the fan-out.
        """
        conns = self._connections.get(session_id, set())
        disconnected: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                logger.exception(
                    "Failed to fan out chat message to a browser; "
                    "removing dead WebSocket from session %s",
                    session_id,
                )
                disconnected.append(ws)
        for ws in disconnected:
            conns.discard(ws)

    # ── Background subscriber ───────────────────────────────────

    async def _subscriber_loop(self) -> None:
        """Forward Redis pub/sub messages into the local WebSocket sets.

        Uses ``PSUBSCRIBE chat:session:*`` so a single connection
        covers every chat session this worker may ever care about.
        Reconnects on transient Redis errors with a short backoff
        — losing the subscriber would silently break chat for the
        whole worker.
        """
        assert self._redis is not None
        backoff_seconds = 0.5
        while not self._stopping:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.psubscribe(CHANNEL_PATTERN)
                # Reset backoff on successful subscribe.
                backoff_seconds = 0.5
                while not self._stopping:
                    try:
                        msg = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=1.0,
                        )
                    except asyncio.TimeoutError:
                        msg = None
                    if msg is None:
                        continue
                    if msg.get("type") not in ("pmessage", "message"):
                        continue
                    channel = msg.get("channel")
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8")
                    session_id = _session_id_from_channel(channel or "")
                    if not session_id:
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    if not isinstance(data, str):
                        continue
                    await self._fanout_local(session_id, data)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "ChatConnectionManager subscriber crashed; "
                    "reconnecting in %.1fs",
                    backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)
                # Exponential backoff capped at 5s.
                backoff_seconds = min(backoff_seconds * 2, 5.0)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.punsubscribe(CHANNEL_PATTERN)
                with contextlib.suppress(Exception):
                    await pubsub.aclose()


# Module-level singleton — import from anywhere instead of constructing
# new instances. Tests can swap it out via monkeypatch on this module.
chat_manager = ChatConnectionManager()
