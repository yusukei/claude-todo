"""In-process Rust-supervisor connection manager.

Mirrors the public surface of ``agent_manager`` (register / unregister
/ send_request / resolve_request / is_connected) so the WS endpoint
and future MCP tools can use the same idioms, but is intentionally
simpler:

- One WebSocket per supervisor (1:1 host binding from spec §2.2).
- No Redis bus / multi-worker fan-out yet — each ``RemoteSupervisor``
  is currently bound to a single host and we only run one backend
  worker against it. If we ever scale out workers, slot a
  ``RedisSupervisorBus`` behind this facade the same way
  ``AgentConnectionManager`` does.
- No in-flight cap or back-pressure: the supervisor RPC surface is
  small (6 RPCs) and only invoked from MCP tools (Day 5), so the
  per-agent concurrency machinery is overkill.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_S = 60.0


class SupervisorOfflineError(Exception):
    """Raised when an RPC targets a supervisor that isn't connected."""


class SupervisorRpcTimeout(Exception):
    """Raised when an RPC response doesn't arrive in time."""


class SupervisorConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # Map request_id -> supervisor_id so disconnect can fail just
        # the affected futures instead of every pending RPC globally.
        self._pending_owner: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ─────────────────────────────────────

    async def register(self, supervisor_id: str, ws: WebSocket) -> None:
        async with self._lock:
            existing = self._connections.get(supervisor_id)
            if existing is not None and existing is not ws:
                # A reconnect raced the old socket. Evict it here so
                # RPCs route to the live one immediately; the stale
                # reader loop will run its own unregister(ws=stale),
                # which is a no-op when ``ws`` doesn't match.
                logger.info(
                    "supervisor_manager: replacing stale ws for supervisor=%s",
                    supervisor_id,
                )
            self._connections[supervisor_id] = ws

    async def unregister(
        self,
        supervisor_id: str,
        ws: WebSocket | None = None,
    ) -> None:
        to_cancel: list[str] = []
        async with self._lock:
            current = self._connections.get(supervisor_id)
            if current is None:
                return
            if ws is not None and current is not ws:
                # Stale handler: a fresher reconnect already claimed
                # the slot; do not evict it.
                return
            self._connections.pop(supervisor_id, None)
            for rid, owner in list(self._pending_owner.items()):
                if owner == supervisor_id:
                    to_cancel.append(rid)
                    self._pending_owner.pop(rid, None)
        # Fail the affected futures *outside* the lock so handlers
        # awaiting on them can re-enter the manager safely.
        for rid in to_cancel:
            fut = self._pending.pop(rid, None)
            if fut and not fut.done():
                fut.set_exception(SupervisorOfflineError(supervisor_id))

    def is_connected(self, supervisor_id: str) -> bool:
        return supervisor_id in self._connections

    def get_connected_supervisor_ids(self) -> list[str]:
        return list(self._connections.keys())

    # ── Messaging ────────────────────────────────────────────────

    async def send_request(
        self,
        supervisor_id: str,
        msg_type: str,
        payload: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Send an RPC envelope and await the supervisor's response.

        Generates a unique ``request_id`` and indexes a Future on it.
        The WS reader loop calls :meth:`resolve_request` on inbound
        frames; matching ``request_id`` resolves the Future.
        """
        ws = self._connections.get(supervisor_id)
        if ws is None:
            raise SupervisorOfflineError(supervisor_id)

        request_id = secrets.token_hex(8)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()

        # Register the Future *before* sending so a fast response
        # can't slip past us into the unknown-request_id branch.
        async with self._lock:
            self._pending[request_id] = fut
            self._pending_owner[request_id] = supervisor_id

        envelope = {
            "type": msg_type,
            "request_id": request_id,
            "payload": payload or {},
        }
        try:
            await ws.send_text(json.dumps(envelope))
        except Exception as e:
            async with self._lock:
                self._pending.pop(request_id, None)
                self._pending_owner.pop(request_id, None)
            raise SupervisorOfflineError(
                f"send to supervisor={supervisor_id} failed: {e}"
            ) from e

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            async with self._lock:
                self._pending.pop(request_id, None)
                self._pending_owner.pop(request_id, None)
            raise SupervisorRpcTimeout(
                f"supervisor={supervisor_id} did not respond to "
                f"{msg_type} within {timeout}s"
            ) from e

    def resolve_request(self, msg: dict[str, Any]) -> bool:
        """Correlate an inbound frame to a pending RPC by ``request_id``.

        Returns True when the frame was consumed (matched a Future).
        Returns False for push frames or unknown request_ids — the
        caller should fall through to type-based dispatch.
        """
        rid = msg.get("request_id")
        if not rid:
            return False
        fut = self._pending.pop(rid, None)
        self._pending_owner.pop(rid, None)
        if fut is None:
            return False
        if not fut.done():
            payload = msg.get("payload") or {}
            # Surface the response type so callers can disambiguate
            # error responses without re-parsing the envelope.
            if isinstance(payload, dict):
                payload["__type__"] = msg.get("type")
            fut.set_result(payload)
        return True


# Module-level singleton. Tests that need isolation can monkeypatch
# ``app.services.supervisor_manager.supervisor_manager`` with a fresh
# instance.
supervisor_manager = SupervisorConnectionManager()
