"""Back-compat shim — canonical home moved to ``app.models.remote``.

This module re-exports the renamed model classes so any straggler
``from app.models.terminal import ...`` keeps working until Phase 5
of the terminal → workspaces/remote rename, when the file is removed.
"""
from .remote import (
    AgentRelease,
    RemoteAgent,
    RemoteExecLog,
    RemoteWorkspace,
)

# Historical name kept as an alias for code that has not yet been updated.
TerminalAgent = RemoteAgent

__all__ = [
    "RemoteAgent",
    "RemoteWorkspace",
    "RemoteExecLog",
    "AgentRelease",
    "TerminalAgent",
]
