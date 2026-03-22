"""Resilient session manager.

Subclasses FastMCP's StreamableHTTPSessionManager to recover from
container restarts. When a client sends an unknown session ID (e.g.
after a restart), instead of returning 404 "Session not found", we
create a new transport paired with that session ID so the client
can re-initialize transparently.
"""

import logging

import anyio
from anyio.abc import TaskStatus
from fastmcp.server.http import StreamableHTTPSessionManager
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    StreamableHTTPServerTransport,
)
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)


class ResilientSessionManager(StreamableHTTPSessionManager):
    """SessionManager that re-creates transports for unknown session IDs.

    After a container restart the in-memory ``_server_instances`` dict is
    empty, so every session ID from a still-connected client becomes
    "unknown".  Instead of returning a 404 error, this subclass creates a
    fresh transport bound to the *same* session ID, allowing the client to
    re-initialize on the existing session without manual reconnection.
    """

    async def _handle_stateful_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # ① Existing session — delegate directly
        if (
            request_mcp_session_id is not None
            and request_mcp_session_id in self._server_instances
        ):
            transport = self._server_instances[request_mcp_session_id]
            await transport.handle_request(scope, receive, send)
            return

        # ② New session (no ID) — use a fresh UUID, require initialization
        # ③ Unknown session (e.g. after restart) — re-create with SAME ID,
        #    start pre-initialized so client can call tools immediately
        is_recovery = request_mcp_session_id is not None
        if not is_recovery:
            session_id_to_use = None
        else:
            session_id_to_use = request_mcp_session_id
            logger.info(
                "Unknown session %s — re-creating transport (likely container restart)",
                request_mcp_session_id,
            )

        async with self._session_creation_lock:
            # Double-check: another concurrent request may have created it
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
            logger.info("Created transport with session ID: %s", new_session_id)

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
                            # Recovery sessions start pre-initialized so
                            # clients can call tools without re-initializing
                            stateless=is_recovery,
                        )
                    except Exception as e:
                        logger.error(
                            "Session %s crashed: %s",
                            http_transport.mcp_session_id,
                            e,
                            exc_info=True,
                        )
                    finally:
                        sid = http_transport.mcp_session_id
                        if (
                            sid
                            and sid in self._server_instances
                            and not http_transport.is_terminated
                        ):
                            logger.info(
                                "Cleaning up crashed session %s", sid
                            )
                            del self._server_instances[sid]

            assert self._task_group is not None
            await self._task_group.start(run_server)
            await http_transport.handle_request(scope, receive, send)
