"""Single-message dispatch through the MCP SDK.

Wraps the MCP SDK's ``Server.run(stateless=...)`` primitive so that a
single JSON-RPC message is pumped through a fresh, short-lived
ServerSession and the resulting response + notifications are collected.

- ``stateless=True``  → the ServerSession is pre-initialized. Used for
  tool calls on an already-initialized MCP session (session state
  itself lives in Redis, see :mod:`session_state`).
- ``stateless=False`` → the SDK runs the real initialize handshake.
  Used exactly once per session, in :func:`handle_initialize`.

This replaces FastMCP's ``StreamableHTTPSessionManager`` entirely: no
per-worker session map, no cross-worker recovery, no session-creation
lock. The only state is in Redis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import anyio
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.types import (
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCResponse,
)

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import AccessToken
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# Outbound stream buffer: must be large enough to absorb all messages the
# SDK emits for one request (one response + any notifications) without
# blocking ``_handle_message``. Tool notifications during a single call
# are typically ≤10; 128 gives ample headroom without wasted memory.
_CLIENT_TO_SERVER_BUF = 8
_SERVER_TO_CLIENT_BUF = 128


@dataclass
class DispatchResult:
    response: dict[str, Any] | None
    notifications: list[dict[str, Any]]


async def dispatch(
    body: dict[str, Any],
    *,
    stateless: bool,
    request: "Request",
    access_token: "AccessToken | None",
) -> DispatchResult:
    """Drive the MCP SDK for one JSON-RPC message.

    Sets FastMCP's contextvars for the duration of the dispatch so that
    tools calling ``get_http_request()`` / ``get_access_token()`` see
    the current request. Also sets ``SessionMessage.metadata`` so that
    the SDK populates ``RequestContext.request`` — which is the
    primary source ``get_http_request()`` consults.

    Args:
        body: Parsed JSON-RPC request body.
        stateless: ``True`` for non-initialize dispatch (session already
            initialized); ``False`` for the initialize handshake.
        request: The ASGI ``Request``; threaded into the SDK so tools
            can inspect headers.
        access_token: Validated OAuth token (or ``None`` for API-key
            auth). Exposed to tools via ``get_access_token()``.

    Returns:
        DispatchResult with the single JSON-RPC response and any
        notifications emitted during dispatch.
    """
    # Deferred import: the `_current_http_request` etc. are private
    # contextvars in the FastMCP package. If FastMCP ever renames them
    # the import failure surfaces here immediately (caught by our unit
    # test), rather than silently-broken auth at runtime.
    from fastmcp.server.dependencies import _current_http_request

    # Import the server lazily so tests can construct DispatchResult
    # without pulling in the full FastMCP graph.
    from .server import mcp as _fastmcp
    _mcp_server = _fastmcp._mcp_server  # the mcp.server.lowlevel.Server instance

    client_to_server_tx, client_to_server_rx = anyio.create_memory_object_stream(
        max_buffer_size=_CLIENT_TO_SERVER_BUF,
    )
    server_to_client_tx, server_to_client_rx = anyio.create_memory_object_stream(
        max_buffer_size=_SERVER_TO_CLIENT_BUF,
    )

    request_id = body.get("id")
    notifications: list[dict[str, Any]] = []
    response: dict[str, Any] | None = None

    # Thread the HTTP request into the SDK so `request_ctx.get().request`
    # is populated for tools that call `get_http_request()`. Also seed
    # the FastMCP contextvar as a belt-and-braces fallback (covered by
    # `get_http_request()`'s own fallback chain).
    scope = request.scope
    if access_token is not None:
        # Minimal scope shape expected by `get_access_token()`:
        # `scope["user"]` must be an `AuthenticatedUser` whose
        # `.access_token` is a FastMCP `AccessToken`.
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
        scope["user"] = AuthenticatedUser(access_token)
        scope["auth"] = _AuthCredentials(scopes=list(access_token.scopes or []))

    http_req_token = _current_http_request.set(request)
    try:
        async with anyio.create_task_group() as tg:

            async def _run_server() -> None:
                try:
                    await _mcp_server.run(
                        client_to_server_rx,
                        server_to_client_tx,
                        _mcp_server.create_initialization_options(),
                        stateless=stateless,
                    )
                finally:
                    # Closing the server-side writer unblocks the reader
                    # loop below when the SDK finishes processing.
                    await server_to_client_tx.aclose()

            tg.start_soon(_run_server)

            # Send the one request message with the HTTP request attached
            # as metadata so the SDK can populate RequestContext.request.
            message = JSONRPCMessage.model_validate(body)
            metadata = ServerMessageMetadata(request_context=request)
            await client_to_server_tx.send(
                SessionMessage(message, metadata=metadata),
            )

            # For requests (have id): wait for matching response.
            # For notifications (no id): close the client side immediately
            # so the SDK's receive loop sees EOF and the task group
            # unwinds. JSON-RPC notifications produce no response.
            if request_id is None:
                # Give the SDK one event-loop tick to process the
                # notification, then close to signal EOF.
                await client_to_server_tx.aclose()
                # Drain anything the SDK emits (notifications could in
                # theory be triggered, though `notifications/initialized`
                # produces nothing). Loop ends when server_to_client_tx
                # is closed by `_run_server`'s finally.
                async for outgoing in server_to_client_rx:
                    root = outgoing.message.root
                    if isinstance(root, JSONRPCNotification):
                        notifications.append(root.model_dump(mode="json"))
            else:
                # Drain outbound messages until we see our response.
                async for outgoing in server_to_client_rx:
                    root = outgoing.message.root
                    if isinstance(root, JSONRPCNotification):
                        notifications.append(root.model_dump(mode="json"))
                        continue
                    if isinstance(root, (JSONRPCResponse, JSONRPCError)):
                        if root.id == request_id:
                            response = root.model_dump(mode="json")
                            break
                        logger.warning(
                            "Unexpected response id during dispatch: "
                            "expected=%r got=%r",
                            request_id, root.id,
                        )
                    else:  # pragma: no cover - sampling callback
                        logger.warning(
                            "Server→client request in stateless dispatch "
                            "(sampling?); ignoring: %s", type(root).__name__,
                        )

                # Close the client→server writer to signal EOF.
                await client_to_server_tx.aclose()
    finally:
        _current_http_request.reset(http_req_token)

    return DispatchResult(response=response, notifications=notifications)


# Placeholder until we import the real type — `AuthCredentials` from
# Starlette `authentication` module.
from starlette.authentication import AuthCredentials as _AuthCredentials  # noqa: E402
