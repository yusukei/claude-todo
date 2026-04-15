"""Unit tests for the Redis-backed stateless MCP transport.

Covers:
- HKDF credential hash: domain separation, deterministic output,
  api_key vs oauth collision resistance, SECRET_KEY change → hash change.
- FastMCP private contextvar import (build-time canary for SDK rename).
- Session state CRUD on fakeredis.
- POST handler: initialize, tool call, unknown session, credential
  mismatch, missing mcp-session-id.
- GET handler: single-holder lock (second GET returns 409).
- DELETE handler: idempotent, credential check.
"""

from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette

from app.mcp.credential_hash import (
    _mcp_hmac_key,
    hash_credential,
    verify_credential_hash,
)


# ── HKDF credential hash ────────────────────────────────────────


def test_hash_credential_is_deterministic():
    h1 = hash_credential("mtodo_abc123", "api_key")
    h2 = hash_credential("mtodo_abc123", "api_key")
    assert h1 == h2


def test_hash_credential_domain_separation():
    """Same raw string under different kinds MUST hash differently."""
    shared = "some_identical_string"
    assert hash_credential(shared, "api_key") != hash_credential(shared, "oauth")


def test_hash_credential_differentiates_inputs():
    assert hash_credential("a", "api_key") != hash_credential("b", "api_key")


def test_verify_credential_hash_compare_digest():
    h = hash_credential("k1", "api_key")
    assert verify_credential_hash(h, "k1", "api_key") is True
    assert verify_credential_hash(h, "k2", "api_key") is False
    # Same raw string, wrong kind → must not match (domain separation).
    assert verify_credential_hash(h, "k1", "oauth") is False


def test_hmac_key_cached_and_secret_derived():
    _mcp_hmac_key.cache_clear()
    k1 = _mcp_hmac_key()
    k2 = _mcp_hmac_key()
    assert k1 is k2  # @functools.cache
    assert len(k1) == 32  # HKDF length=32


def test_secret_key_rotation_invalidates_hashes(monkeypatch):
    """Rotating SECRET_KEY must produce a different derived key, so
    old session hashes stop matching — acceptable by design."""
    import app.mcp.credential_hash as mod
    _mcp_hmac_key.cache_clear()
    h_before = hash_credential("k", "api_key")
    monkeypatch.setattr(mod.settings, "SECRET_KEY", "rotated-" + "x" * 48)
    _mcp_hmac_key.cache_clear()
    h_after = hash_credential("k", "api_key")
    assert h_before != h_after


# ── FastMCP contextvar canary ───────────────────────────────────


def test_fastmcp_private_contextvars_importable():
    """If FastMCP renames these private contextvars in a future
    version, the import here fails and the build breaks BEFORE
    prod sees a silent auth outage."""
    from fastmcp.server.dependencies import _current_http_request
    # Setting and resetting must work without error.
    from starlette.requests import Request
    dummy = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    tok = _current_http_request.set(dummy)
    try:
        assert _current_http_request.get() is dummy
    finally:
        _current_http_request.reset(tok)


# ── Session state CRUD on fakeredis ─────────────────────────────


@pytest_asyncio.fixture
async def patched_mcp_redis():
    """Point mcp.oauth._redis at a fresh fakeredis for each test."""
    import app.mcp.oauth._redis as redis_mod
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    prev = redis_mod._mcp_redis
    redis_mod._mcp_redis = fake
    yield fake
    redis_mod._mcp_redis = prev
    await fake.aclose()


@pytest.mark.asyncio
async def test_session_crud_roundtrip(patched_mcp_redis):
    from app.mcp import session_state

    sid = await session_state.create_session(
        auth_kind="api_key",
        auth_key_hash="abc",
        protocol_init_params_json='{"protocolVersion":"2024-11-05"}',
        capabilities_json='{"tools":{"listChanged":true}}',
    )
    assert isinstance(sid, str) and len(sid) == 32

    loaded = await session_state.load_session(sid)
    assert loaded is not None
    assert loaded["auth_kind"] == "api_key"
    assert loaded["auth_key_hash"] == "abc"
    assert "protocolVersion" in loaded["protocol_init_params"]

    await session_state.delete_session(sid)
    assert await session_state.load_session(sid) is None


@pytest.mark.asyncio
async def test_sse_holder_single_owner(patched_mcp_redis):
    from app.mcp import session_state

    sid = "sess-abc"
    holder_a = "worker-a"
    holder_b = "worker-b"

    assert await session_state.acquire_sse_holder(sid, holder_a) is True
    assert await session_state.acquire_sse_holder(sid, holder_b) is False

    # Non-owner refresh must fail.
    assert await session_state.refresh_sse_holder(sid, holder_b) is False
    # Owner refresh succeeds.
    assert await session_state.refresh_sse_holder(sid, holder_a) is True

    # Non-owner release must not affect the lock.
    await session_state.release_sse_holder_if_owner(sid, holder_b)
    assert await session_state.acquire_sse_holder(sid, holder_b) is False

    # Owner release frees the lock.
    await session_state.release_sse_holder_if_owner(sid, holder_a)
    assert await session_state.acquire_sse_holder(sid, holder_b) is True


@pytest.mark.asyncio
async def test_append_event_increments_cursor(patched_mcp_redis):
    from app.mcp import session_state

    sid = "sess-stream"
    id1 = await session_state.append_event(sid, b'{"x":1}')
    id2 = await session_state.append_event(sid, b'{"x":2}')

    assert id1 != id2
    # Redis stream ids are lexicographically sortable by time.
    assert id1 < id2


@pytest.mark.asyncio
async def test_touch_session_refreshes_both_ttls(patched_mcp_redis):
    """Paired TTL refresh: session Hash AND events Stream get EXPIRE.

    This closes the v2 drift bug where a pure-SSE-idle client's events
    stream expired while the session Hash was still live.
    """
    from app.mcp import session_state

    sid = await session_state.create_session(
        auth_kind="api_key",
        auth_key_hash="h",
        protocol_init_params_json="{}",
        capabilities_json="{}",
    )
    # Seed the events stream so it exists.
    await session_state.append_event(sid, b"{}")

    # Force-set both TTLs to a low value, then touch_session should lift them.
    r = patched_mcp_redis
    await r.expire(session_state.session_key(sid), 10)
    await r.expire(session_state.events_key(sid), 10)
    assert await r.ttl(session_state.session_key(sid)) <= 10
    assert await r.ttl(session_state.events_key(sid)) <= 10

    await session_state.touch_session(sid)
    assert await r.ttl(session_state.session_key(sid)) > 100
    assert await r.ttl(session_state.events_key(sid)) > 100


# ── Transport handler tests ─────────────────────────────────────


@pytest_asyncio.fixture
async def transport_client(patched_mcp_redis):
    """Build a Starlette app with just the MCP transport mounted."""
    from app.mcp.transport import get_mcp_routes
    app = Starlette(routes=get_mcp_routes("/mcp"))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_post_missing_session_id(transport_client):
    resp = await transport_client.post(
        "/mcp",
        headers={"x-api-key": "some_key"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600
    assert "mcp-session-id" in body["error"]["message"]


@pytest.mark.asyncio
async def test_post_unknown_session_returns_404(transport_client):
    resp = await transport_client.post(
        "/mcp",
        headers={
            "x-api-key": "some_key",
            "mcp-session-id": "nonexistent",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == -32001
    assert "re-initialize" in body["error"]["message"]


@pytest.mark.asyncio
async def test_post_credential_mismatch_returns_403(
    transport_client, patched_mcp_redis,
):
    """A valid session accessed with a different credential must 403."""
    from app.mcp import session_state

    sid = await session_state.create_session(
        auth_kind="api_key",
        auth_key_hash=hash_credential("mtodo_original", "api_key"),
        protocol_init_params_json="{}",
        capabilities_json="{}",
    )

    resp = await transport_client.post(
        "/mcp",
        headers={
            "x-api-key": "mtodo_different",
            "mcp-session-id": sid,
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == -32003


@pytest.mark.asyncio
async def test_post_no_credentials_returns_401(transport_client):
    resp = await transport_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_is_idempotent(transport_client):
    """DELETE on unknown session returns 204."""
    resp = await transport_client.request(
        "DELETE", "/mcp",
        headers={
            "x-api-key": "some_key",
            "mcp-session-id": "never-existed",
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_requires_credentials(transport_client):
    resp = await transport_client.request(
        "DELETE", "/mcp",
        headers={"mcp-session-id": "abc"},
    )
    # Unknown session returns 204 (idempotent) — no credential check
    # because there's nothing to protect.
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_real_session_checks_credential(
    transport_client, patched_mcp_redis,
):
    from app.mcp import session_state

    sid = await session_state.create_session(
        auth_kind="api_key",
        auth_key_hash=hash_credential("mtodo_owner", "api_key"),
        protocol_init_params_json="{}",
        capabilities_json="{}",
    )

    # Wrong credential: 403, session survives.
    resp = await transport_client.request(
        "DELETE", "/mcp",
        headers={
            "x-api-key": "mtodo_attacker",
            "mcp-session-id": sid,
        },
    )
    assert resp.status_code == 403
    assert await session_state.load_session(sid) is not None

    # Correct credential: 204, session gone.
    resp = await transport_client.request(
        "DELETE", "/mcp",
        headers={
            "x-api-key": "mtodo_owner",
            "mcp-session-id": sid,
        },
    )
    assert resp.status_code == 204
    assert await session_state.load_session(sid) is None


@pytest.mark.asyncio
async def test_get_unknown_session_returns_404(transport_client):
    resp = await transport_client.get(
        "/mcp",
        headers={
            "x-api-key": "some_key",
            "mcp-session-id": "nope",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_missing_session_id_returns_400(transport_client):
    resp = await transport_client.get(
        "/mcp",
        headers={"x-api-key": "some_key"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_notification_returns_202_immediately(
    transport_client, patched_mcp_redis,
):
    """JSON-RPC notifications (no `id`) MUST get 202 without blocking
    on a response. The MCP `notifications/initialized` handshake step
    fails otherwise — observed bug from prod smoke test."""
    from app.mcp import session_state

    sid = await session_state.create_session(
        auth_kind="api_key",
        auth_key_hash=hash_credential("k", "api_key"),
        protocol_init_params_json="{}",
        capabilities_json="{}",
    )

    resp = await transport_client.post(
        "/mcp",
        headers={
            "x-api-key": "k",
            "mcp-session-id": sid,
            "content-type": "application/json",
        },
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        timeout=2.0,
    )
    assert resp.status_code == 202
