"""MCP tools for the Rust supervisor control plane (spec §3.2).

Five tools wrap ``supervisor_manager.send_request`` so an operator can
manage the agent process without SSH:

- ``supervisor_status``        — agent state, pid, uptime, recent stderr
- ``supervisor_restart``       — kill-then-spawn with new pid in response
- ``supervisor_logs``          — one-shot tail (live subscribe is WS-only)
- ``supervisor_upgrade``       — sha256-verified atomic binary swap
- ``supervisor_config_reload`` — re-read config from disk on the host

Authorisation: each tool resolves ``supervisor_id`` to a
``RemoteSupervisor`` document and checks ``owner_id == user_id`` so a
user can only manage supervisors they registered. Admin override is
not currently supported (mirrors the agent surface — admins must take
ownership explicitly).
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp.exceptions import ToolError

from ...models.remote import RemoteSupervisor
from ...services.supervisor_manager import (
    SupervisorOfflineError,
    SupervisorRpcTimeout,
    supervisor_manager,
)
from ..auth import authenticate
from ..server import mcp

logger = logging.getLogger(__name__)


DEFAULT_RPC_TIMEOUT_S = 30.0
# supervisor_upgrade has its own deadline that mirrors the supervisor-
# side observation window (30s) plus headroom for download + swap.
UPGRADE_RPC_TIMEOUT_S = 180.0


async def _resolve_supervisor(supervisor_id: str, key_info: dict) -> RemoteSupervisor:
    """Look up ``supervisor_id`` and check the calling user owns it.

    Raises ToolError on miss / ownership mismatch — same shape as the
    agent tools so callers see consistent error envelopes.
    """
    s = await RemoteSupervisor.get(supervisor_id)
    if s is None or s.owner_id != key_info["user_id"]:
        raise ToolError(f"Supervisor not found: {supervisor_id}")
    return s


async def _send_rpc(
    supervisor_id: str,
    msg_type: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    """Forward an envelope to the supervisor and translate transport
    errors into ToolError so the MCP client sees a clean message
    instead of an opaque server stack."""
    try:
        return await supervisor_manager.send_request(
            supervisor_id, msg_type, payload, timeout=timeout
        )
    except SupervisorOfflineError as e:
        raise ToolError(f"Supervisor is offline: {e}") from e
    except SupervisorRpcTimeout as e:
        raise ToolError(str(e)) from e


@mcp.tool()
async def supervisor_status(supervisor_id: str) -> dict:
    """Report the agent process state managed by a supervisor.

    Args:
        supervisor_id: Registered supervisor ID (from list / create).

    Returns:
        ``{agent_state, agent_pid, agent_started_at, agent_uptime_s,
        agent_version, last_crash_at, last_crash_exit_code,
        consecutive_crashes, recent_stderr}``.

        ``agent_state`` is one of ``stopped``, ``starting``, ``running``,
        ``stopping``, ``crashed``. ``recent_stderr`` is up to 20 lines
        of the agent's recent stderr buffer.
    """
    key_info = await authenticate()
    await _resolve_supervisor(supervisor_id, key_info)
    payload = await _send_rpc(
        supervisor_id, "supervisor_status", {}, DEFAULT_RPC_TIMEOUT_S
    )
    payload.pop("__type__", None)
    return payload


@mcp.tool()
async def supervisor_restart(
    supervisor_id: str,
    graceful_timeout_ms: int | None = None,
) -> dict:
    """Restart the agent process managed by a supervisor.

    The supervisor performs a 4-stage graceful kill (WS shutdown RPC ->
    timeout wait -> CTRL_BREAK_EVENT on Windows -> TerminateJobObject)
    and then respawns the agent. The response is returned only after
    the new PID is observed (or a timeout elapses), so the MCP caller
    can immediately know whether the restart succeeded.

    Args:
        supervisor_id: Registered supervisor ID.
        graceful_timeout_ms: Optional override for the graceful-kill
            stage 2 wait (default: supervisor's configured value, ~5s).

    Returns:
        ``{restarted: bool, new_pid: int | None, error: str | None}``.
    """
    key_info = await authenticate()
    await _resolve_supervisor(supervisor_id, key_info)
    payload: dict[str, Any] = {}
    if graceful_timeout_ms is not None:
        payload["graceful_timeout_ms"] = int(graceful_timeout_ms)
    result = await _send_rpc(
        supervisor_id, "supervisor_restart", payload, DEFAULT_RPC_TIMEOUT_S
    )
    result.pop("__type__", None)
    return result


@mcp.tool()
async def supervisor_logs(
    supervisor_id: str,
    lines: int | None = None,
    since_ts: str | None = None,
    stream: str | None = None,
) -> dict:
    """Fetch a one-shot snapshot of the agent's captured stdout/stderr.

    For live tail, use the ``supervisor_logs_subscribe`` WebSocket RPC
    directly — MCP tools are request/response only and don't support
    server-push.

    Args:
        supervisor_id: Registered supervisor ID.
        lines: Maximum lines to return (default: full buffer, capped at
            the supervisor's ring capacity ~10000).
        since_ts: ISO 8601 UTC timestamp; only lines newer than this
            are returned.
        stream: Filter by stream — ``"stdout"``, ``"stderr"``, or
            ``"both"`` (default).

    Returns:
        ``{lines: [{ts, stream, text, truncated}, ...]}`` oldest-first.
    """
    key_info = await authenticate()
    await _resolve_supervisor(supervisor_id, key_info)
    if stream is not None and stream not in ("stdout", "stderr", "both"):
        raise ToolError(
            f"stream must be 'stdout', 'stderr', or 'both' (got {stream!r})"
        )
    payload: dict[str, Any] = {}
    if lines is not None:
        if lines <= 0:
            raise ToolError("lines must be > 0")
        payload["lines"] = int(lines)
    if since_ts is not None:
        payload["since_ts"] = since_ts
    if stream is not None:
        payload["stream"] = stream
    result = await _send_rpc(
        supervisor_id, "supervisor_logs", payload, DEFAULT_RPC_TIMEOUT_S
    )
    result.pop("__type__", None)
    return result


@mcp.tool()
async def supervisor_upgrade(
    supervisor_id: str,
    download_url: str,
    sha256: str,
) -> dict:
    """Trigger an atomic upgrade of the agent binary on the host.

    The supervisor performs spec §6.4: download to ``<exe>.new``,
    verify sha256 (download), fsync, pause the supervised loop,
    swap (``<exe>`` -> ``<exe>.old``, ``<exe>.new`` -> ``<exe>``),
    re-verify sha256 (post-write), resume, observe for 30s, and
    rollback if the new binary crashes more than once during the
    observation window. A ``.lock`` file is written across the
    swap so an interrupted upgrade is recoverable on the next
    supervisor restart.

    Returns immediately on download / verify failure. On success
    the response arrives only after the 30s observation window
    completes — set the MCP client timeout accordingly (this tool
    waits up to 180s).

    For uv-run mode (no single agent binary), the supervisor
    returns ``success: false`` with an explanatory error.

    Args:
        supervisor_id: Registered supervisor ID.
        download_url: HTTPS URL to fetch the new binary from.
        sha256: Expected lowercase-hex sha256 of the binary
            (must match both the streamed download and the
            post-write file).

    Returns:
        ``{success: bool, new_version: str | None, error: str | None}``.
    """
    key_info = await authenticate()
    await _resolve_supervisor(supervisor_id, key_info)
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256.lower()):
        raise ToolError(
            "sha256 must be 64 lowercase-hex characters"
        )
    payload = {"download_url": download_url, "sha256": sha256.lower()}
    result = await _send_rpc(
        supervisor_id, "supervisor_upgrade", payload, UPGRADE_RPC_TIMEOUT_S
    )
    result.pop("__type__", None)
    return result


@mcp.tool()
async def supervisor_config_reload(supervisor_id: str) -> dict:
    """Re-read the supervisor's TOML config from disk and apply
    hot-reloadable fields (``log.*``, ``restart.*``, ``supervisor_log.*``,
    ``backend.heartbeat_interval_s``).

    Restart-required fields (``backend.url``, ``backend.token``,
    ``agent.*``) are not hot-applied — the response includes them in
    ``requires_restart`` so the operator knows to drive
    ``supervisor_restart`` (or for backend.token, the future
    ``supervisor_reconnect_backend`` RPC).

    Args:
        supervisor_id: Registered supervisor ID.

    Returns:
        ``{success: bool, errors: [str], requires_restart: [str]}``.
    """
    key_info = await authenticate()
    await _resolve_supervisor(supervisor_id, key_info)
    result = await _send_rpc(
        supervisor_id, "supervisor_config_reload", {}, DEFAULT_RPC_TIMEOUT_S
    )
    result.pop("__type__", None)
    return result
