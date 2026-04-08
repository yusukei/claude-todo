"""Workspaces endpoints package — Agent WebSocket + Workspace REST API.

Renamed from ``endpoints/terminal/`` (Phase 1+2 of the terminal → workspaces
rename, 2026-04-08). The package layout matches the previous terminal/
package, only the parent router prefix changed from ``/terminal`` to
``/workspaces``. A back-compat ``legacy_terminal_router`` exposing the
old prefix is also exported until the running Agent has been updated to
the new URL via self-update (removed in Phase 5).
"""
from __future__ import annotations

from fastapi import APIRouter

from .....core.config import settings  # re-exported for tests
from . import _releases_util, _shared
from ._releases_util import (
    find_latest_release as _find_latest_release,
    is_newer as _is_newer,
    parse_version_tuple as _parse_version_tuple,
)
from ._shared import reset_all_agents_online
from .agents import router as _agents_router
from .releases import router as _releases_router
from .websocket import _RESPONSE_TYPES, router as _websocket_router
from .workspaces import router as _workspaces_router


def _build_router(prefix: str, tag: str) -> APIRouter:
    r = APIRouter(prefix=prefix, tags=[tag])
    r.include_router(_agents_router)
    r.include_router(_workspaces_router)
    r.include_router(_releases_router)
    r.include_router(_websocket_router)
    return r


router = _build_router("/workspaces", "workspaces")

# Back-compat alias router for the pre-rename /api/v1/terminal/* prefix.
# The currently running Agent (built before the rename) still connects
# to /api/v1/terminal/agent/ws and uses /terminal/releases/* for self-
# update. This alias keeps it functional until a new binary has rolled
# out via self-update. To be removed in Phase 5 of the rename.
legacy_terminal_router = _build_router("/terminal", "terminal-legacy")

__all__ = [
    "router",
    "legacy_terminal_router",
    "reset_all_agents_online",
    "settings",
    "_RESPONSE_TYPES",
    "_find_latest_release",
    "_is_newer",
    "_parse_version_tuple",
]
