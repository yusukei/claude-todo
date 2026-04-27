"""Unit tests for the ``supervisor_request_agent_token`` WS RPC handler.

Tests the standalone helper :func:`_handle_request_agent_token` directly
(no WebSocket scaffolding) since the handler is a pure async function
that takes a supervisor record and returns a JSON response dict.
"""
from __future__ import annotations

import pytest

from app.api.v1.endpoints.workspaces.supervisor_ws import (
    _handle_request_agent_token,
)
from app.core.security import hash_api_key
from app.models import RemoteAgent, RemoteSupervisor


@pytest.mark.asyncio
async def test_returns_no_paired_agent_error_when_unpaired(admin_user):
    sv = RemoteSupervisor(
        name="legacy-sv",
        key_hash=hash_api_key("sv_" + "x" * 32),
        owner_id=str(admin_user.id),
        # paired_agent_id intentionally unset (legacy supervisor).
    )
    await sv.insert()

    resp = await _handle_request_agent_token(
        supervisor=sv, rotate=False, request_id="req-1",
    )
    assert resp["type"] == "supervisor_request_agent_token_result"
    assert resp["request_id"] == "req-1"
    assert resp["error"]["code"] == "no_paired_agent"


@pytest.mark.asyncio
async def test_returns_paired_agent_missing_when_record_deleted(admin_user):
    sv = RemoteSupervisor(
        name="sv",
        key_hash=hash_api_key("sv_" + "y" * 32),
        owner_id=str(admin_user.id),
        paired_agent_id="0" * 24,  # well-formed but does not exist
    )
    await sv.insert()

    resp = await _handle_request_agent_token(
        supervisor=sv, rotate=False, request_id="req-2",
    )
    assert resp["error"]["code"] == "paired_agent_missing"


@pytest.mark.asyncio
async def test_issues_fresh_token_and_updates_both_records(admin_user):
    agent = RemoteAgent(
        name="paired",
        key_hash=hash_api_key("ta_" + "old" * 11),  # 33 chars OK as input
        owner_id=str(admin_user.id),
    )
    await agent.insert()
    sv = RemoteSupervisor(
        name="sv",
        key_hash=hash_api_key("sv_" + "z" * 32),
        owner_id=str(admin_user.id),
        paired_agent_id=str(agent.id),
        agent_token_hash=agent.key_hash,
    )
    await sv.insert()
    old_agent_hash = agent.key_hash

    resp = await _handle_request_agent_token(
        supervisor=sv, rotate=True, request_id="req-3",
    )
    assert resp["type"] == "supervisor_request_agent_token_result"
    assert resp["request_id"] == "req-3"
    assert resp["payload"]["agent_id"] == str(agent.id)
    new_token = resp["payload"]["agent_token"]
    assert new_token.startswith("ta_")

    refreshed_agent = await RemoteAgent.get(agent.id)
    refreshed_sv = await RemoteSupervisor.get(sv.id)
    assert refreshed_agent.key_hash != old_agent_hash
    assert refreshed_agent.key_hash == hash_api_key(new_token)
    assert refreshed_sv.agent_token_hash == refreshed_agent.key_hash


@pytest.mark.asyncio
async def test_rotate_false_still_issues_fresh_token(admin_user):
    """Backend never has the raw token, so rotate=false still rotates.

    This documents the intentional behavior — clients should not rely on
    rotate=false meaning "give me the existing token".
    """
    agent = RemoteAgent(
        name="paired2",
        key_hash=hash_api_key("ta_" + "p" * 32),
        owner_id=str(admin_user.id),
    )
    await agent.insert()
    sv = RemoteSupervisor(
        name="sv2",
        key_hash=hash_api_key("sv_" + "q" * 32),
        owner_id=str(admin_user.id),
        paired_agent_id=str(agent.id),
        agent_token_hash=agent.key_hash,
    )
    await sv.insert()
    old_hash = agent.key_hash

    resp = await _handle_request_agent_token(
        supervisor=sv, rotate=False, request_id="req-4",
    )
    new_token = resp["payload"]["agent_token"]
    refreshed = await RemoteAgent.get(agent.id)
    assert refreshed.key_hash == hash_api_key(new_token)
    assert refreshed.key_hash != old_hash
