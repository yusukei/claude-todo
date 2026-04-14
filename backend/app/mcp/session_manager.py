"""Resilient session manager with cross-worker Redis registry.

Extends FastMCP's ``StreamableHTTPSessionManager`` with two improvements:

1. **Redis session registry** (``RedisSessionRegistry``)
   Every worker registers its sessions in a shared Redis key-space.  When a
   request arrives for a session that is *not* in the local
   ``_server_instances`` map the manager checks Redis before deciding what
   to do:

   - Session found in Redis  → cross-worker recovery: create a local
     ``StreamableHTTPServerTransport`` pre-initialised in stateless mode
     so the client can continue using its existing tool list immediately.
     The ``Last-Event-ID`` / ``RedisEventStore`` path then replays any
     events the client missed during the transfer.

   - Session not in Redis   → truly expired / invalid session.  Return
     a ``404 Session not found`` JSON-RPC error per the MCP spec rather
     than blindly creating a recovery transport.

2. **Container-restart resilience** (original ``ResilientSessionManager``
   behaviour, preserved)
   If the process has restarted and lost its in-memory state, the Redis
   registry still contains the session entry (TTL = 1 hour) so incoming
   requests are recovered transparently instead of returning 404.

Prior behaviour (pre-registry)
-------------------------------
``Unknown session X — re-creating transport (likely container restart)``
was logged for *every* cross-worker round-robin hit because the manager
had no way to tell "valid session on another worker" from "expired
session".  With the registry the distinction is authoritative.

Multi-worker behaviour
----------------------
With Traefik sticky routing (cookie ``_sticky_mcp``) the common case is
that all requests for a session land on the same worker: no registry
lookup needed.  The registry only activates for:

- worker crash (sticky target gone → Traefik re-routes to surviving
  worker)
- rolling restart (new worker starts before old one drains)
- round-robin misconfiguration / missing sticky cookie
- future multi-instance scale-out

SSE event continuity
--------------------
The persistent GET ``/mcp`` SSE stream lives on the worker that opened
it.  When that worker disappears the client reconnects; the new worker
creates a recovery transport and ``RedisEventStore.replay_events_after``
replays buffered events — no tool-list re-initialisation is required
from the client's perspective (``stateless=True`` in ``app.run``).

Cross-worker POST requests
--------------------------
When a POST arrives at Worker B for a session whose SSE stream is on
Worker A, Worker B creates a recovery transport in stateless mode and
sends the response inline in the POST response body.  This is correct
because MCP stateful-HTTP responses are always carried in the POST body;
the GET SSE stream is for server-initiated *notifications*, not for
request–response.

Session TTL
-----------
The registry entry TTL is refreshed on each request handled by the
owning worker (``registry.touch``).  An idle session expires from the
registry after ``_SESSION_TTL`` seconds (default 1 hour), matching the
``RedisEventStore`` event-buffer TTL.
"""

from __future__ import annotations

import logging

import anyio
from anyio.abc import TaskStatus
from fastmcp.server.http import StreamableHTTPSessionManager
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    StreamableHTTPServerTransport,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from .session_registry import RedisSessionRegistry

logger = logging.getLogger(__name__)


class ResilientSessionManager(StreamableHTTPSessionManager):
    """SessionManager with Redis-backed cross-worker session awareness.

    Parameters
    ----------
    session_registry:
        Shared Redis registry.  Pass ``None`` to disable the registry
        (falls back to the original "always recover unknown sessions"
        behaviour — useful for unit tests that do not wire up Redis).
    All other parameters are forwarded verbatim to the upstream
    ``StreamableHTTPSessionManager``.
    """

    def __init__(self, *args, session_registry: RedisSessionRegistry | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._session_registry = session_registry

    # ------------------------------------------------------------------
    # ASGI entry-point override
    # ------------------------------------------------------------------

    async def _handle_stateful_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # ── Fast path: session lives in this worker ───────────────────
        if (
            request_mcp_session_id is not None
            and request_mcp_session_id in self._server_instances
        ):
            transport = self._server_instances[request_mcp_session_id]
            # Refresh the registry TTL on every handled request so the
            # session does not expire for long-running connections.
            if self._session_registry is not None:
                try:
                    await self._session_registry.touch(request_mcp_session_id)
                except Exception:
                    # Registry touch failures are non-fatal; the session
                    # is still alive locally.  Log at debug so operators
                    # notice if Redis is consistently unreachable.
                    logger.debug(
                        "Registry touch failed for session %s (Redis unreachable?)",
                        request_mcp_session_id,
                        exc_info=True,
                    )
            await transport.handle_request(scope, receive, send)
            return

        # ── New session (no session ID in request) ────────────────────
        if request_mcp_session_id is None:
            await self._create_and_handle(
                scope, receive, send, session_id_to_use=None, is_recovery=False
            )
            return

        # ── Unknown session (has session ID, not in local map) ────────
        #
        # Check the Redis registry to decide whether this is a valid
        # session on another worker (→ recover) or a truly expired /
        # invalid session (→ 404).
        is_known_in_registry = await self._check_registry(request_mcp_session_id)

        if not is_known_in_registry:
            # Not in Redis either: truly expired or forged session ID.
            # Return 404 per the MCP spec.
            logger.warning(
                "Unknown MCP session %s — not found in registry, returning 404",
                request_mcp_session_id,
            )
            await self._send_session_not_found(scope, receive, send)
            return

        # Session is valid (registered by another worker or a previous
        # incarnation of this worker).  Create a recovery transport so
        # the client can continue its session without re-initialising.
        logger.info(
            "Cross-worker MCP session recovery: %s",
            request_mcp_session_id,
        )
        await self._create_and_handle(
            scope, receive, send,
            session_id_to_use=request_mcp_session_id,
            is_recovery=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _check_registry(self, session_id: str) -> bool:
        """Return True if *session_id* is registered in Redis.

        If no registry is configured (test/dev mode), always return True
        so that the original "recover every unknown session" behaviour is
        preserved.
        """
        if self._session_registry is None:
            return True
        try:
            return await self._session_registry.exists(session_id)
        except Exception:
            # Redis unavailable: fail open (same as pre-registry behaviour)
            # so that a Redis outage does not hard-break MCP connectivity.
            logger.warning(
                "Session registry unavailable — treating session %s as known "
                "(Redis error); fix the Redis connection to restore 404 "
                "precision for expired sessions.",
                session_id,
                exc_info=True,
            )
            return True

    async def _create_and_handle(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        session_id_to_use: str | None,
        is_recovery: bool,
    ) -> None:
        """Create a new transport (or a recovery transport) and serve the request."""
        async with self._session_creation_lock:
            # Double-check: a concurrent request may have already created it.
            if (
                session_id_to_use is not None
                and session_id_to_use in self._server_instances
            ):
                transport = self._server_instances[session_id_to_use]
                await transport.handle_request(scope, receive, send)
                return

            from uuid import uuid4

            new_session_id = session_id_to_use or uuid4().hex

            http_transport = StreamableHTTPServerTransport(
                mcp_session_id=new_session_id,
                is_json_response_enabled=self.json_response,
                event_store=self.event_store,
                security_settings=self.security_settings,
                retry_interval=self.retry_interval,
            )

            assert http_transport.mcp_session_id is not None
            self._server_instances[http_transport.mcp_session_id] = http_transport
            logger.info(
                "%s MCP transport: session_id=%s",
                "Recovered" if is_recovery else "Created",
                new_session_id,
            )

            # Register in Redis so other workers know this session is live.
            if self._session_registry is not None:
                try:
                    await self._session_registry.register(new_session_id)
                except Exception:
                    logger.warning(
                        "Failed to register session %s in Redis registry — "
                        "cross-worker recovery will not be available for this "
                        "session until Redis is restored.",
                        new_session_id,
                        exc_info=True,
                    )

            async def run_server(
                *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED
            ) -> None:
                async with http_transport.connect() as streams:
                    read_stream, write_stream = streams
                    task_status.started()
                    try:
                        await self.app.run(
                            read_stream,
                            write_stream,
                            self.app.create_initialization_options(),
                            # Recovery sessions start pre-initialised so
                            # clients can call tools without re-initialising.
                            stateless=is_recovery,
                        )
                    except Exception:
                        logger.exception(
                            "MCP session %s crashed",
                            http_transport.mcp_session_id,
                        )
                    finally:
                        sid = http_transport.mcp_session_id
                        if (
                            sid
                            and sid in self._server_instances
                            and not http_transport.is_terminated
                        ):
                            logger.info("Cleaning up crashed MCP session %s", sid)
                            del self._server_instances[sid]
                        # Unregister from Redis so other workers stop
                        # attempting to recover a dead session.
                        if sid and self._session_registry is not None:
                            try:
                                await self._session_registry.unregister(sid)
                            except Exception:
                                logger.debug(
                                    "Failed to unregister session %s from Redis registry",
                                    sid,
                                    exc_info=True,
                                )

            assert self._task_group is not None
            await self._task_group.start(run_server)
            await http_transport.handle_request(scope, receive, send)

    async def _send_session_not_found(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Return a 404 JSON-RPC error for an unknown/expired session."""
        from http import HTTPStatus

        from mcp.types import INVALID_REQUEST, ErrorData, JSONRPCError

        error_response = JSONRPCError(
            jsonrpc="2.0",
            id="server-error",
            error=ErrorData(
                code=INVALID_REQUEST,
                message="Session not found",
            ),
        )
        response = Response(
            content=error_response.model_dump_json(by_alias=True, exclude_none=True),
            status_code=HTTPStatus.NOT_FOUND,
            media_type="application/json",
        )
        await response(scope, receive, send)
