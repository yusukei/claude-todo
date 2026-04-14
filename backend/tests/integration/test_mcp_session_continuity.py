"""Integration tests for MCP cross-worker session continuity.

Verifies that the ``RedisSessionRegistry`` enables workers to share
session awareness via Redis, and that ``ResilientSessionManager``
correctly distinguishes between:
- a valid session registered on another worker  → cross-worker recovery
- a truly expired / unknown session            → 404

Test infrastructure
-------------------
Real Redis via ``testcontainers[redis]`` (same approach as
``test_agent_bus_realredis.py``).  The module is skipped automatically
when Docker is unavailable so CI environments without a Docker daemon
stay green.

Two-worker simulation
---------------------
Within a single process we instantiate two ``RedisSessionRegistry``
objects pointing at the same Redis container.  This correctly models
the multi-worker scenario because each object maintains an independent
connection and has no shared in-memory state.

For the ``ResilientSessionManager`` tests we verify the decision logic
(recovery vs. 404) by inspecting the ASGI response sent for a mocked
request — the full MCP protocol loop is not exercised.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# ── Module-level Docker availability guard ─────────────────────
_skip_reason: str | None = None
try:
    import docker as _docker  # type: ignore[import-not-found]

    _docker.from_env().ping()
except ImportError as _e:
    _skip_reason = f"docker-py not installed: {_e}"
except Exception as _e:  # pragma: no cover
    _skip_reason = f"Docker daemon unreachable: {type(_e).__name__}: {_e}"

if _skip_reason is not None:
    pytest.skip(_skip_reason, allow_module_level=True)

pytest.importorskip(
    "testcontainers.core.container",
    reason="testcontainers not installed",
)

import redis.asyncio as aioredis  # noqa: E402

from app.mcp.session_registry import RedisSessionRegistry  # noqa: E402

# Force per-test event loops (same rationale as test_agent_bus_realredis.py:
# redis-py Lock objects bind to the loop they are first awaited on).
pytestmark = pytest.mark.asyncio(loop_scope="function")


# ── Container fixture ────────────────────────────────────────────


@pytest.fixture(scope="module")
def redis_container_url():
    """Start a real Redis container once per module; yield its URL."""
    import socket
    import time

    from testcontainers.core.container import DockerContainer

    container = DockerContainer("redis:7-alpine").with_exposed_ports(6379)
    container.start()
    try:
        host = container.get_container_host_ip()
        if host == "localhost":
            host = "127.0.0.1"
        port = int(container.get_exposed_port(6379))
        url = f"redis://{host}:{port}/0"

        deadline = time.monotonic() + 30.0
        while True:
            try:
                with socket.create_connection((host, port), timeout=2) as s:
                    s.sendall(b"PING\r\n")
                    reply = s.recv(64)
                    if b"PONG" in reply:
                        break
            except Exception:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Redis container at {url} did not answer PING in 30s"
                )
            time.sleep(0.2)

        yield url
    finally:
        container.stop()


@pytest_asyncio.fixture(loop_scope="function")
async def redis_client(redis_container_url):
    """Yield a flushed aioredis client bound to the current test loop."""
    client = aioredis.from_url(
        redis_container_url,
        decode_responses=True,
        health_check_interval=10,
        socket_keepalive=True,
    )
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()


# ── Helper: build two registries sharing the same Redis ─────────


def make_registry(redis_url: str) -> RedisSessionRegistry:
    """Create a fresh registry connected to the given Redis URL."""
    return RedisSessionRegistry(redis_url=redis_url)


# ══════════════════════════════════════════════════════════════════
# Section 1: RedisSessionRegistry unit-level tests (real Redis)
# ══════════════════════════════════════════════════════════════════


async def test_register_makes_session_visible_to_peer(redis_container_url, redis_client):
    """Session registered by registry-A is immediately visible to registry-B."""
    reg_a = make_registry(redis_container_url)
    reg_b = make_registry(redis_container_url)
    session_id = "cross-worker-test-session"

    try:
        # A registers (simulates worker A creating the session)
        await reg_a.register(session_id)

        # B can see it (simulates worker B receiving a request for that session)
        assert await reg_b.exists(session_id), (
            "registry-B should see the session registered by registry-A"
        )

        # A unregisters (simulates session termination on worker A)
        await reg_a.unregister(session_id)

        # B now sees it's gone
        assert not await reg_b.exists(session_id), (
            "registry-B should see the session removed by registry-A"
        )
    finally:
        await reg_a.aclose()
        await reg_b.aclose()


async def test_nonexistent_session_not_visible(redis_container_url, redis_client):
    """A session ID that was never registered returns False from exists()."""
    reg = make_registry(redis_container_url)
    try:
        assert not await reg.exists("never-registered-session-xyz")
    finally:
        await reg.aclose()


async def test_touch_refreshes_ttl(redis_container_url, redis_client):
    """touch() resets the TTL so the session does not expire mid-flight."""
    reg = make_registry(redis_container_url)
    session_id = "touch-test-session"
    try:
        await reg.register(session_id)
        key = f"todo:mcp:registry:{session_id}"

        # Manually shorten TTL to 2s so we can observe the touch effect
        await redis_client.expire(key, 2)
        ttl_before = await redis_client.ttl(key)
        assert ttl_before <= 2

        await reg.touch(session_id)
        ttl_after = await redis_client.ttl(key)
        # After touch, TTL should be back near _SESSION_TTL (3600s)
        assert ttl_after > 10, f"Expected TTL > 10 after touch, got {ttl_after}"
    finally:
        await reg.aclose()


async def test_two_workers_independent_registration(redis_container_url, redis_client):
    """Each worker independently registers its own sessions; all visible to peers."""
    reg_a = make_registry(redis_container_url)
    reg_b = make_registry(redis_container_url)

    try:
        # Both workers register different sessions simultaneously
        await asyncio.gather(
            reg_a.register("session-from-worker-a"),
            reg_b.register("session-from-worker-b"),
        )

        # Each registry can see the other's session
        assert await reg_a.exists("session-from-worker-b")
        assert await reg_b.exists("session-from-worker-a")

        # Worker A's own session also visible to itself
        assert await reg_a.exists("session-from-worker-a")
    finally:
        await reg_a.aclose()
        await reg_b.aclose()


# ══════════════════════════════════════════════════════════════════
# Section 2: ResilientSessionManager decision-making (real Redis)
# ══════════════════════════════════════════════════════════════════


def _make_asgi_request(session_id: str | None) -> tuple[dict, Any, Any, list]:
    """Build a minimal ASGI (scope, receive, send) triple for testing.

    Returns the scope dict and async callables for receive/send.
    ``send`` captures all sent chunks into ``sent_chunks``.
    """
    headers: list[tuple[bytes, bytes]] = []
    if session_id is not None:
        headers.append((b"mcp-session-id", session_id.encode()))

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp/",
        "headers": headers,
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent_chunks: list[dict] = []

    async def send(message):
        sent_chunks.append(message)

    return scope, receive, send, sent_chunks


async def test_manager_recovers_known_cross_worker_session(redis_container_url, redis_client):
    """Manager creates a recovery transport for a session registered in Redis.

    Scenario: session was created on worker A (registered in Redis).
    A request arrives at worker B (manager has empty _server_instances).
    Expected: recovery transport is created (NOT a 404).

    Verification strategy: ``_server_instances`` is cleared when the task
    group exits, so we check it *inside* ``manager.run()`` while the fake
    protocol loop is still blocking on ``run_gate``.
    """
    from app.mcp.session_manager import ResilientSessionManager

    reg = make_registry(redis_container_url)
    session_id = "cross-worker-session-abc"

    try:
        # Worker A registers the session
        await reg.register(session_id)

        # run_gate blocks the fake protocol loop so _server_instances is
        # still populated when we check it.
        run_gate = asyncio.Event()
        run_started = asyncio.Event()

        mock_mcp_server = MagicMock()
        mock_mcp_server.create_initialization_options.return_value = {}

        async def _fake_run(read_stream, write_stream, init_opts, *, stateless=False):
            run_started.set()
            await run_gate.wait()

        mock_mcp_server.run = _fake_run

        manager = ResilientSessionManager(
            app=mock_mcp_server,
            event_store=None,
            session_registry=reg,
        )

        scope, receive, send_fn, sent_chunks = _make_asgi_request(session_id)

        import anyio as _anyio

        async with manager.run():
            async with _anyio.create_task_group() as tg:
                # Kick off the request handler in the background so we can
                # check state while the fake protocol loop is blocked.
                tg.start_soon(manager._handle_stateful_request, scope, receive, send_fn)

                # Wait until the fake protocol loop is actually running.
                await run_started.wait()

                # At this point the transport IS in _server_instances.
                assert session_id in manager._server_instances, (
                    "Recovery transport should be present while the protocol "
                    "loop is still running (known session from Redis)"
                )

                # Verify the registry was NOT by-passed: the session existed in
                # Redis before this request arrived.
                assert await reg.exists(session_id), (
                    "Session should still be registered while the transport is live"
                )

                run_gate.set()  # let the fake loop finish

        # Must NOT have sent a 404 response.
        status_codes = [
            chunk.get("status")
            for chunk in sent_chunks
            if chunk.get("type") == "http.response.start"
        ]
        assert 404 not in status_codes, (
            f"Should not return 404 for a cross-worker session; "
            f"got status codes: {status_codes}"
        )
    finally:
        await reg.aclose()


async def test_manager_returns_404_for_truly_unknown_session(redis_container_url, redis_client):
    """Manager returns 404 for a session that is not in the Redis registry.

    Scenario: client sends a session ID that was never registered (expired
    or forged).  Expected: 404 JSON-RPC error, no recovery transport.
    """
    from app.mcp.session_manager import ResilientSessionManager

    reg = make_registry(redis_container_url)
    expired_session_id = "expired-or-forged-session-xyz"

    try:
        # No registration: this session never existed in Redis.

        mock_mcp_server = MagicMock()
        mock_mcp_server.create_initialization_options.return_value = {}

        manager = ResilientSessionManager(
            app=mock_mcp_server,
            event_store=None,
            session_registry=reg,
        )

        scope, receive, send_fn, sent_chunks = _make_asgi_request(expired_session_id)

        async with manager.run():
            await manager._handle_stateful_request(scope, receive, send_fn)

        # Must have sent a 404 response
        status_codes = [
            chunk.get("status")
            for chunk in sent_chunks
            if chunk.get("type") == "http.response.start"
        ]
        assert 404 in status_codes, (
            f"Should return 404 for an expired/unknown session; "
            f"got status codes: {status_codes}"
        )

        # Must NOT have created a transport for the unknown session
        assert expired_session_id not in manager._server_instances, (
            "No transport should be created for a truly unknown session"
        )
    finally:
        await reg.aclose()


async def test_manager_with_no_registry_recovers_all_unknown_sessions(redis_container_url, redis_client):
    """Without a registry, unknown sessions are always recovered (legacy behaviour).

    This confirms backward-compatibility: passing ``session_registry=None``
    restores the original ``ResilientSessionManager`` behaviour where every
    unknown session ID is treated as a cross-worker recovery target.
    """
    from app.mcp.session_manager import ResilientSessionManager

    import anyio as _anyio

    session_id = "no-registry-test-session"

    run_gate = asyncio.Event()
    run_started = asyncio.Event()

    mock_mcp_server = MagicMock()
    mock_mcp_server.create_initialization_options.return_value = {}

    async def _fake_run(read_stream, write_stream, init_opts, *, stateless=False):
        run_started.set()
        await run_gate.wait()

    mock_mcp_server.run = _fake_run

    # No registry — legacy mode
    manager = ResilientSessionManager(
        app=mock_mcp_server,
        event_store=None,
        session_registry=None,  # disabled
    )

    scope, receive, send_fn, sent_chunks = _make_asgi_request(session_id)

    async with manager.run():
        async with _anyio.create_task_group() as tg:
            tg.start_soon(manager._handle_stateful_request, scope, receive, send_fn)

            await run_started.wait()

            # Transport is in _server_instances while the protocol loop is running.
            assert session_id in manager._server_instances, (
                "Without a registry, unknown sessions should always be recovered"
            )

            run_gate.set()

    status_codes = [
        chunk.get("status")
        for chunk in sent_chunks
        if chunk.get("type") == "http.response.start"
    ]
    assert 404 not in status_codes


async def test_session_unregistered_after_termination(redis_container_url, redis_client):
    """Session is removed from Redis when the transport terminates.

    After the MCP protocol loop exits (simulated by the fake run() above),
    the manager's cleanup code should unregister the session from Redis so
    that subsequent cross-worker requests for the same ID return 404 rather
    than attempting futile recovery.
    """
    from app.mcp.session_manager import ResilientSessionManager

    reg_owner = make_registry(redis_container_url)
    reg_peer = make_registry(redis_container_url)
    session_id = "cleanup-test-session"

    try:
        mock_mcp_server = MagicMock()
        mock_mcp_server.create_initialization_options.return_value = {}

        # Fake run that exits immediately — simulates session completion.
        async def _fake_run(read_stream, write_stream, init_opts, *, stateless=False):
            return

        mock_mcp_server.run = _fake_run

        manager = ResilientSessionManager(
            app=mock_mcp_server,
            event_store=None,
            session_registry=reg_owner,
        )

        # Create session (request with no session ID → new session)
        scope, receive, send_fn, _ = _make_asgi_request(None)

        async with manager.run():
            await manager._handle_stateful_request(scope, receive, send_fn)
            # At this point the session should be registered in Redis.
            # Grab the actual session ID from the manager's instance map.
            created_ids = list(manager._server_instances.keys())

        # After manager.run() exits, the task group is cancelled and all
        # transports are terminated → cleanup should have unregistered them.
        if created_ids:
            created_session_id = created_ids[0]
            # Give cleanup coroutines a moment to run.
            await asyncio.sleep(0.1)
            still_exists = await reg_peer.exists(created_session_id)
            assert not still_exists, (
                f"Session {created_session_id} should be unregistered after "
                "the transport terminates, but it's still in Redis"
            )
    finally:
        await reg_owner.aclose()
        await reg_peer.aclose()
