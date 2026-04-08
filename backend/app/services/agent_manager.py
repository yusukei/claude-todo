"""Agent connection manager facade.

The actual in-process state machine lives in
:mod:`agent_local_transport`. This module keeps backwards-compatible
exports — exception classes, back-pressure constants, the
``AgentConnectionManager`` symbol, and the ``agent_manager``
singleton — so existing callers and tests do not have to change.

The split exists to make room for the Redis multi-worker bus
(P1, PR 2) where ``AgentConnectionManager`` will become a true facade
that composes a :class:`LocalAgentTransport` with a remote routing
layer. The current PR (P1, PR 1) is a pure refactor with no
behavioural changes — see [task:69d67511f4b6de00d3fd1359].

## Why the constants live here and not in agent_local_transport

``LocalAgentTransport`` reads ``MAX_PENDING_PER_AGENT`` /
``MAX_PENDING_GLOBAL`` / ``MAX_INFLIGHT_PER_AGENT`` via late binding
through this module (``from . import agent_manager as _am``). Tests
monkeypatch these names on this module, and the late lookup means
the override takes effect on the very next call without anyone
having to re-import or rebuild semaphores. Moving the constants
into ``agent_local_transport`` would silently break those tests
because ``monkeypatch.setattr`` only rebinds the name in the module
it is given.
"""

from __future__ import annotations

from .agent_local_transport import (
    AgentBusyError,
    AgentOfflineError,
    CommandTimeoutError,
    LocalAgentTransport,
)

__all__ = [
    "AgentBusyError",
    "AgentOfflineError",
    "CommandTimeoutError",
    "AgentConnectionManager",
    "agent_manager",
    "MAX_INFLIGHT_PER_AGENT",
    "MAX_PENDING_PER_AGENT",
    "MAX_PENDING_GLOBAL",
]


# Per-agent concurrency caps. These are intentionally module-level
# constants rather than Settings so tests can patch them without
# pytest-env gymnastics. The defaults are sized for a single-process
# deployment talking to a handful of agents: each agent can run 8
# concurrent operations, with up to 64 requests queued on top of
# that. Global ceiling caps the worst case across all agents.
MAX_INFLIGHT_PER_AGENT = 8
MAX_PENDING_PER_AGENT = 64
MAX_PENDING_GLOBAL = 512


class AgentConnectionManager(LocalAgentTransport):
    """Public facade for the agent connection layer.

    Currently a thin subclass of :class:`LocalAgentTransport` with no
    overrides. PR 2 will replace this inheritance with composition +
    a Redis routing layer; the public method signatures will stay the
    same so callers do not have to change.
    """


# Module-level singleton — import this from anywhere instead of
# constructing new instances. Tests can swap it out via monkeypatch
# on this module.
agent_manager = AgentConnectionManager()
