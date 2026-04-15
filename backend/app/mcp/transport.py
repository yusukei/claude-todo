"""MCP stateless HTTP transport.

Replaces FastMCP's ``StreamableHTTPSessionManager`` with per-request
dispatch where session state lives exclusively in Redis. See
``docs/architecture/mcp-stateless-transport.md`` for the full design.

Routes:
    POST   /mcp   — JSON-RPC requests (initialize + tool calls)
    GET    /mcp   — SSE subscriber for server-originated notifications
    DELETE /mcp   — explicit session teardown

Every handler is stateless w.r.t. the worker process. All session
state lives under Redis keys ``mcp:v1:session:*``, ``mcp:v1:events:*``,
``mcp:v1:sse_holder:*``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import orjson
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .credential_hash import AuthKind, hash_credential, verify_credential_hash
from .dispatch import dispatch
from .session_state import (
    SSE_HOLDER_TTL,
    acquire_sse_holder,
    append_event,
    create_session,
    delete_session,
    load_session,
    release_sse_holder_if_owner,
    run_holder_refresh_loop,
    run_ttl_refresh_loop,
    touch_session,
)

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import AccessToken

logger = logging.getLogger(__name__)

# ── JSON-RPC error codes (server-defined range -32000..-32099) ──
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_SESSION_EXPIRED = -32001
ERR_CREDENTIAL_MISMATCH = -32003

# ── Keepalive cadence for SSE comments ──
_SSE_KEEPALIVE_INTERVAL_S = 10.0
_XREAD_BLOCK_MS = 10_000


# ──────────────────────────────────────────────────────────────
# Credential extraction + validation
# ──────────────────────────────────────────────────────────────


@dataclass
class Credentials:
    kind: AuthKind
    raw: str  # api_key string or bearer token string


class AuthError(Exception):
    """Raised when credential extraction/validation fails."""

    def __init__(self, message: str, *, www_authenticate: str | None = None) -> None:
        super().__init__(message)
        self.www_authenticate = www_authenticate


async def extract_and_validate_credentials(
    request: Request,
) -> tuple[Credentials, "AccessToken | None"]:
    """Validate a credential at the handler boundary.

    ⚠ Both X-API-Key AND OAuth Bearer flows are MANDATORY. Removing or
    breaking either branch takes down a class of clients:

    - Claude Code (``.mcp.json`` `headers.X-API-Key`) → X-API-Key path
    - Claude Desktop / OAuth-capable clients → Bearer path

    See ``backend/app/mcp/auth.py`` module docstring and
    ``docs/architecture/mcp-stateless-transport.md`` §"Authentication".

    - X-API-Key: shape check only; full DB lookup happens later in the
      initialize flow via ``authenticate()`` in ``auth.py``.
    - Bearer token: deep validation here (signature/expiry via the
      OAuth provider's ``load_access_token``). Returns the
      ``AccessToken`` so dispatch can seed ``scope["user"]`` for tools.
    """
    api_key = request.headers.get("x-api-key")
    if api_key is not None:
        stripped = api_key.strip()
        if not stripped:
            raise AuthError(
                "empty X-API-Key",
                www_authenticate='Bearer error="invalid_token"',
            )
        return Credentials(kind="api_key", raw=stripped), None

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:].strip()
        if not raw_token:
            raise AuthError("empty bearer token", www_authenticate='Bearer error="invalid_token"')
        # Deferred import so tests can mock the provider without
        # importing the whole MCP graph.
        from .server import _oauth_provider
        token = await _oauth_provider.load_access_token(raw_token)
        if token is None:
            raise AuthError(
                "invalid or expired bearer token",
                www_authenticate='Bearer error="invalid_token"',
            )
        return Credentials(kind="oauth", raw=raw_token), token

    # No credentials at all. We MUST NOT advertise Bearer auth via
    # WWW-Authenticate here, because Claude Code (and other clients
    # that prefer X-API-Key) interprets that header as "the server
    # demands OAuth" and switches into a browser-based OAuth flow,
    # ignoring the X-API-Key in `.mcp.json`. The browser flow then
    # hangs and the client reports "connection timed out after 30000ms".
    #
    # WWW-Authenticate: Bearer is only meaningful when the client has
    # actually presented (an invalid) Bearer token — see the branch
    # above. For "no credentials at all" we return a plain 401.
    raise AuthError("missing credentials")


# ──────────────────────────────────────────────────────────────
# Response helpers
# ──────────────────────────────────────────────────────────────


def _jsonrpc_error_response(
    http_status: int,
    code: int,
    message: str,
    *,
    jsonrpc_id: Any = None,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    body = {
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "error": {"code": code, "message": message},
    }
    headers = {"content-type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        orjson.dumps(body),
        status_code=http_status,
        headers=headers,
    )


async def _dispatch_notification_safe(
    body: dict[str, Any],
    request: Request,
    access_token: "AccessToken | None",
) -> None:
    """Fire-and-forget dispatch for JSON-RPC notifications.

    Notifications produce no JSON-RPC response (no `id`), so we don't
    block the HTTP response on them. We still drive the SDK so any
    state effects (e.g., `notifications/initialized`, `notifications/
    cancelled`) are applied. Errors are logged loudly; nothing is
    swallowed silently.
    """
    try:
        await dispatch(
            body, stateless=True, request=request, access_token=access_token,
        )
    except Exception:
        logger.exception(
            "notification dispatch failed for method=%r", body.get("method"),
        )


def _auth_error_response(err: AuthError) -> Response:
    headers = {}
    if err.www_authenticate:
        headers["www-authenticate"] = err.www_authenticate
    return _jsonrpc_error_response(
        401, ERR_INVALID_REQUEST, str(err), extra_headers=headers,
    )


# ──────────────────────────────────────────────────────────────
# POST /mcp
# ──────────────────────────────────────────────────────────────


async def handle_post(request: Request) -> Response:
    # 1. Parse body.
    try:
        raw = await request.body()
        body = orjson.loads(raw) if raw else {}
    except (orjson.JSONDecodeError, ValueError) as exc:
        return _jsonrpc_error_response(400, ERR_PARSE, f"parse error: {exc}")

    if not isinstance(body, dict):
        return _jsonrpc_error_response(400, ERR_INVALID_REQUEST, "request must be a JSON object")

    method = body.get("method")
    jsonrpc_id = body.get("id")

    # 2. Extract + validate credentials.
    try:
        creds, access_token = await extract_and_validate_credentials(request)
    except AuthError as exc:
        return _auth_error_response(exc)

    # 3. initialize path — stateful single-shot.
    if method == "initialize":
        return await _handle_initialize(request, body, creds, access_token)

    # 4. Non-initialize: require a session matching the credential.
    sid = request.headers.get("mcp-session-id")
    if not sid:
        return _jsonrpc_error_response(
            400, ERR_INVALID_REQUEST, "missing mcp-session-id",
            jsonrpc_id=jsonrpc_id,
        )

    session = await load_session(sid)
    if session is None:
        return _jsonrpc_error_response(
            404, ERR_SESSION_EXPIRED, "session expired; re-initialize",
            jsonrpc_id=jsonrpc_id,
        )

    stored_hash = session.get("auth_key_hash", "")
    stored_kind = session.get("auth_kind", "")
    if stored_kind not in ("api_key", "oauth"):
        logger.error("Session %s has invalid auth_kind=%r", sid[:8], stored_kind)
        return _jsonrpc_error_response(
            500, ERR_INVALID_REQUEST, "internal session state invalid",
            jsonrpc_id=jsonrpc_id,
        )
    if creds.kind != stored_kind or not verify_credential_hash(
        stored_hash, creds.raw, creds.kind,
    ):
        return _jsonrpc_error_response(
            403, ERR_CREDENTIAL_MISMATCH, "credential mismatch",
            jsonrpc_id=jsonrpc_id,
        )

    # 5. Paired TTL refresh (invariant 3).
    await touch_session(sid)

    # 6a. JSON-RPC notifications / responses (no "id" field) are
    #     fire-and-forget — the server MUST NOT reply with a response,
    #     per JSON-RPC 2.0 and MCP. Accept the message and dispatch
    #     in the background; return 202 immediately so the client's
    #     next request doesn't block on a response that will never come.
    if jsonrpc_id is None:
        # The SDK expects notifications to flow into the session too
        # (e.g. `notifications/initialized`, `notifications/cancelled`).
        # We dispatch without waiting for a response — stateless mode
        # will process and emit nothing back for a notification.
        asyncio.create_task(
            _dispatch_notification_safe(body, request, access_token),
        )
        return Response(status_code=202)

    # 6b. Request (has "id"): dispatch and wait for the response.
    result = await dispatch(
        body, stateless=True, request=request, access_token=access_token,
    )

    # 7. Enqueue notifications to the events Stream.
    for notification in result.notifications:
        try:
            await append_event(sid, orjson.dumps(notification))
        except Exception:
            logger.exception(
                "XADD failed for sid=%s; notification lost", sid[:8],
            )

    if result.response is None:
        # Shouldn't happen — the SDK always returns a response for a
        # valid JSONRPCRequest. Log loudly and return a tool-level
        # error body so the client sees something actionable.
        logger.error(
            "Dispatch returned no response for method=%r id=%r sid=%s",
            method, jsonrpc_id, sid[:8],
        )
        return _jsonrpc_error_response(
            500, ERR_INVALID_REQUEST,
            "dispatch completed without a response",
            jsonrpc_id=jsonrpc_id,
        )

    return Response(
        orjson.dumps(result.response),
        status_code=200,
        headers={"content-type": "application/json"},
    )


async def _handle_initialize(
    request: Request,
    body: dict[str, Any],
    creds: Credentials,
    access_token: "AccessToken | None",
) -> Response:
    """Initialize is the one stateful call: run the SDK handshake,
    capture ``InitializeRequestParams``, persist to Redis, return the
    response with a fresh ``mcp-session-id`` header.
    """
    # Drive the SDK with stateless=False so it performs the real
    # handshake (NotInitialized → Initializing → Initialized).
    result = await dispatch(
        body, stateless=False, request=request, access_token=access_token,
    )
    if result.response is None or "result" not in result.response:
        logger.error("initialize dispatch returned no result: %r", result.response)
        return _jsonrpc_error_response(
            500, ERR_INVALID_REQUEST, "initialize failed",
            jsonrpc_id=body.get("id"),
        )

    capabilities = result.response["result"].get("capabilities", {})
    init_params = body.get("params") or {}

    # Mint a fresh session id (§11.2 session-fixation defense:
    # inbound mcp-session-id is ignored).
    sid = await create_session(
        auth_kind=creds.kind,
        auth_key_hash=hash_credential(creds.raw, creds.kind),
        protocol_init_params_json=json.dumps(init_params, separators=(",", ":")),
        capabilities_json=json.dumps(capabilities, separators=(",", ":")),
    )

    return Response(
        orjson.dumps(result.response),
        status_code=200,
        headers={
            "content-type": "application/json",
            "mcp-session-id": sid,
        },
    )


# ──────────────────────────────────────────────────────────────
# GET /mcp (SSE subscriber)
# ──────────────────────────────────────────────────────────────


def _sse_format(entry_id: str, data_bytes: bytes) -> bytes:
    """Format one Redis stream entry as an SSE `data:` block."""
    # Each entry_id becomes the MCP `Last-Event-ID`.
    return (
        f"id: {entry_id}\n".encode()
        + b"data: " + data_bytes + b"\n\n"
    )


async def handle_get(request: Request) -> Response:
    sid = request.headers.get("mcp-session-id")
    if not sid:
        return Response(status_code=400)

    session = await load_session(sid)
    if session is None:
        return Response(status_code=404)

    try:
        creds, _access_token = await extract_and_validate_credentials(request)
    except AuthError as exc:
        return _auth_error_response(exc)

    stored_hash = session.get("auth_key_hash", "")
    stored_kind = session.get("auth_kind", "")
    if creds.kind != stored_kind or not verify_credential_hash(
        stored_hash, creds.raw, creds.kind,
    ):
        return Response(status_code=403)

    holder_id = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
    acquired = await acquire_sse_holder(sid, holder_id)
    if not acquired:
        return Response(status_code=409, headers={"retry-after": "5"})

    last_event_id = request.headers.get("last-event-id", "0-0")

    async def stream():
        from .session_state import events_key
        from .oauth._redis import get_mcp_redis
        redis = get_mcp_redis()
        cursor = last_event_id

        refresh_task = asyncio.create_task(run_holder_refresh_loop(sid, holder_id))
        ttl_task = asyncio.create_task(run_ttl_refresh_loop(sid))

        # Send a keepalive immediately so clients know the SSE handshake
        # succeeded without waiting up to XREAD BLOCK (10 s) for the
        # first event. Some clients (Claude Code in particular) treat
        # silence past their per-request timeout as a connection failure.
        yield b": connected\n\n"

        try:
            while True:
                # Disconnect detection: Starlette's Request exposes a
                # receive() that yields 'http.disconnect' when the
                # client closes. Use request.is_disconnected() at the
                # top of each loop iteration.
                if await request.is_disconnected():
                    return

                try:
                    entries = await redis.xread(
                        {events_key(sid): cursor},
                        block=_XREAD_BLOCK_MS,
                        count=100,
                    )
                except Exception:
                    logger.exception("XREAD failed for sid=%s", sid[:8])
                    return

                if not entries:
                    # Nothing in the stream — send a keepalive comment.
                    yield b": keepalive\n\n"
                    continue

                for _stream, items in entries:
                    for entry_id, fields in items:
                        try:
                            data = fields.get("data") or fields.get(b"data")
                            if data is None:
                                logger.warning(
                                    "Malformed event sid=%s id=%s (no data field)",
                                    sid[:8], entry_id,
                                )
                                cursor = entry_id
                                continue
                            if isinstance(data, str):
                                data = data.encode("utf-8")
                            yield _sse_format(entry_id, data)
                        except (UnicodeDecodeError, KeyError) as exc:
                            logger.exception(
                                "Malformed event sid=%s id=%s: %s",
                                sid[:8], entry_id, exc,
                            )
                        cursor = entry_id
        finally:
            refresh_task.cancel()
            ttl_task.cancel()
            for t in (refresh_task, ttl_task):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            await release_sse_holder_if_owner(sid, holder_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache, no-transform",
            "mcp-session-id": sid,
        },
    )


# ──────────────────────────────────────────────────────────────
# DELETE /mcp
# ──────────────────────────────────────────────────────────────


async def handle_delete(request: Request) -> Response:
    sid = request.headers.get("mcp-session-id")
    if not sid:
        return Response(status_code=400)

    session = await load_session(sid)
    if session is None:
        return Response(status_code=204)  # idempotent

    try:
        creds, _ = await extract_and_validate_credentials(request)
    except AuthError as exc:
        return _auth_error_response(exc)

    stored_hash = session.get("auth_key_hash", "")
    stored_kind = session.get("auth_kind", "")
    if creds.kind != stored_kind or not verify_credential_hash(
        stored_hash, creds.raw, creds.kind,
    ):
        return Response(status_code=403)

    await delete_session(sid)
    return Response(status_code=204)


# ──────────────────────────────────────────────────────────────
# Route registration
# ──────────────────────────────────────────────────────────────


def get_mcp_routes(prefix: str = "/mcp") -> list[Route]:
    """Return Starlette routes for the MCP transport.

    Mounted directly on the FastAPI app. Routes handle both
    ``{prefix}`` and ``{prefix}/`` to avoid a 307 redirect (which
    strips auth headers on some clients).
    """
    paths = [prefix, prefix + "/"]
    routes: list[Route] = []
    for p in paths:
        routes.append(Route(p, handle_post, methods=["POST"]))
        routes.append(Route(p, handle_get, methods=["GET"]))
        routes.append(Route(p, handle_delete, methods=["DELETE"]))
    return routes
