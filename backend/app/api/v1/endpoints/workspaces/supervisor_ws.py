"""Rust supervisor WebSocket loop (spec §3.1, §6.1).

Mirrors ``websocket.py`` (the agent loop) but for the ``supervisor_*``
control plane. The two channels are intentionally separate:

- Different auth tokens (``sv_*`` vs ``ta_*``); the supervisor token
  has stronger privileges (restart / upgrade / config_reload).
- Different envelope namespaces (``supervisor_*`` vs ``terminal_*`` /
  ``exec_*``).
- Different connection manager instances. ``supervisor_manager`` is
  the in-process counterpart of ``agent_manager``.

The endpoint owns:
1. Origin allowlist + first-message ``auth`` handshake (10s timeout).
2. ``RemoteSupervisor`` upsert from the inbound ``supervisor_info``
   pushes (hostname, os_type, versions, agent_pid, agent_uptime_s).
3. ``supervisor_event`` logging (agent_started / agent_crashed / …).
4. ``supervisor_log`` push forwarding — currently buffered to the
   server log only; live tail to MCP subscribers lands in Day 5.
5. RPC response correlation via ``supervisor_manager.resolve_request``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .....core.config import settings
from .....core.security import hash_api_key
from .....models.remote import RemoteSupervisor
from .....services.supervisor_manager import supervisor_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# Push frame types (no request_id). Listed explicitly so
# ``resolve_request`` doesn't try to correlate them.
_PUSH_TYPES = frozenset(
    {"supervisor_info", "supervisor_event", "supervisor_log"}
)


async def _safe_close(ws: WebSocket, *, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except (RuntimeError, OSError, WebSocketDisconnect) as e:
        logger.info(
            "supervisor_websocket: ws.close(code=%s) failed: %s",
            code, e, exc_info=e,
        )


def _allowed_origins() -> set[str]:
    return settings.ws_allowed_origins


@router.websocket("/supervisor/ws")
async def supervisor_websocket(ws: WebSocket) -> None:
    """Supervisor WebSocket with first-message authentication.

    Same Origin-allowlist policy as the agent endpoint: browser-
    originated connections must match ``ws_allowed_origins``;
    headless clients (the Rust supervisor) send no Origin header
    and pass through to token auth.
    """
    origin = ws.headers.get("origin")
    if origin is not None and origin not in _allowed_origins():
        logger.warning(
            "supervisor_websocket: rejecting Origin=%r", origin
        )
        await ws.close(code=4403, reason="Origin not allowed")
        return

    await ws.accept()

    # ── Auth via first message ──
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect) as e:
        logger.info(
            "supervisor_websocket: auth handshake failed: %s", e, exc_info=e
        )
        await _safe_close(ws, code=4008, reason="Auth timeout")
        return

    if msg.get("type") != "auth" or not msg.get("token"):
        logger.warning(
            "supervisor_websocket: first message was not an auth frame (type=%r)",
            msg.get("type"),
        )
        await _safe_close(ws, code=4008, reason="Expected auth message")
        return

    key_hash = hash_api_key(msg["token"])
    supervisor = await RemoteSupervisor.find_one({"key_hash": key_hash})
    if not supervisor:
        logger.warning(
            "supervisor_websocket: rejected connection with invalid token"
        )
        try:
            await ws.send_text(
                json.dumps({"type": "auth_error", "message": "Invalid token"})
            )
        except (RuntimeError, OSError, WebSocketDisconnect) as e:
            logger.info(
                "supervisor_websocket: could not deliver auth_error: %s",
                e, exc_info=e,
            )
        await _safe_close(ws, code=4008, reason="Invalid supervisor token")
        return

    supervisor_id = str(supervisor.id)

    # ``host_id`` from the auth frame is the spec §2.2 join key — the
    # supervisor and the agent on the same physical host both report
    # the same value, so the UI can render "supervisor X manages
    # agent Y" without an explicit FK.
    reported_host_id = msg.get("host_id")
    if reported_host_id:
        supervisor.host_id = reported_host_id

    await ws.send_text(
        json.dumps({"type": "auth_ok", "supervisor_id": supervisor_id})
    )

    await supervisor_manager.register(supervisor_id, ws)
    supervisor.last_seen_at = datetime.now(UTC)
    await supervisor.save()
    logger.info(
        "Supervisor connected: %s (%s)", supervisor.name, supervisor_id
    )

    # ── Message loop ──
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(
                    "Supervisor %s: dropped non-JSON frame: %r",
                    supervisor_id, raw[:200],
                )
                continue

            msg_type = msg.get("type")
            request_id = msg.get("request_id")

            # Push frames carry no request_id — skip the correlation
            # check so ``resolve_request`` doesn't waste a lookup.
            if (
                request_id is not None
                and msg_type not in _PUSH_TYPES
                and supervisor_manager.resolve_request(msg)
            ):
                continue

            if msg_type == "supervisor_info":
                payload = msg.get("payload") or {}
                _apply_supervisor_info(supervisor, payload)
                supervisor.last_seen_at = datetime.now(UTC)
                await supervisor.save()

            elif msg_type == "supervisor_event":
                payload = msg.get("payload") or {}
                event = payload.get("event")
                logger.info(
                    "supervisor=%s event=%s payload=%s",
                    supervisor_id, event, payload,
                )
                # Update agent_pid on agent_started / agent_restarted
                # so callers polling the model see fresh state without
                # waiting for the next supervisor_info push.
                if event in {"agent_started", "agent_restarted"}:
                    new_pid = payload.get("agent_pid")
                    if isinstance(new_pid, int):
                        supervisor.agent_pid = new_pid
                        supervisor.last_seen_at = datetime.now(UTC)
                        await supervisor.save()

            elif msg_type == "supervisor_log":
                # Day 4 just logs the count + sample. Day 5 will fan
                # out to MCP subscribers via a dedicated bus.
                payload = msg.get("payload") or {}
                lines = payload.get("lines") or []
                if lines:
                    logger.debug(
                        "supervisor=%s log batch (%d lines, first: %r)",
                        supervisor_id, len(lines), lines[0].get("text", "")[:120],
                    )

            else:
                logger.warning(
                    "Supervisor %s: unknown frame type=%r request_id=%s (dropped)",
                    supervisor_id, msg_type, request_id,
                )

    except WebSocketDisconnect:
        logger.info(
            "Supervisor disconnected: %s (%s)", supervisor.name, supervisor_id
        )
    except Exception:
        logger.exception(
            "Supervisor WebSocket error (%s)", supervisor_id
        )
    finally:
        await supervisor_manager.unregister(supervisor_id, ws)
        supervisor.last_seen_at = datetime.now(UTC)
        try:
            await supervisor.save()
        except Exception:
            logger.exception(
                "Failed to persist supervisor last_seen_at on disconnect (%s)",
                supervisor_id,
            )


def _apply_supervisor_info(
    supervisor: RemoteSupervisor, payload: dict
) -> None:
    """Copy the supervisor_info push payload into the model.

    Only fields that the supervisor explicitly reports are touched —
    None / missing values leave the existing value alone so a partial
    payload doesn't blank out previously-known data.
    """
    if (hostname := payload.get("hostname")):
        supervisor.hostname = hostname
    if (os_type := payload.get("os")):
        supervisor.os_type = os_type
    if (host_id := payload.get("host_id")):
        supervisor.host_id = host_id
    if (sv_version := payload.get("supervisor_version")):
        supervisor.supervisor_version = sv_version
    if (agent_version := payload.get("agent_version")):
        supervisor.agent_version = agent_version
    agent_pid = payload.get("agent_pid")
    if isinstance(agent_pid, int):
        supervisor.agent_pid = agent_pid
    agent_uptime = payload.get("agent_uptime_s")
    if isinstance(agent_uptime, int):
        supervisor.agent_uptime_s = agent_uptime
