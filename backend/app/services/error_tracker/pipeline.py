"""Worker event pipeline (T5 handler).

Wires together scrubbing (T6), fingerprinting (T5), Issue
upsert + counter enqueue (T5 + T11), PII-safe event persistence,
and auto-task creation (T14).

The function is registered with the worker via
``set_event_handler`` in :func:`install_real_handler`.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import orjson

from ...models.error_tracker import (
    ErrorIssue,
    ErrorProject,
    IssueLevel,
    IssueStatus,
)
from .auto_task import create_task_for_new_issue
from .counters import record_event_seen
from .events import get_event_collection_for_date
from .fingerprint import compute_fingerprint
from .scrubber import scrub_event

logger = logging.getLogger(__name__)

_LEVEL_VALUES = {x.value for x in IssueLevel}


def _coerce_level(val: Any) -> IssueLevel:
    s = str(val or "").lower()
    if s in _LEVEL_VALUES:
        return IssueLevel(s)
    if s == "critical":  # alias seen in the wild
        return IssueLevel.fatal
    return IssueLevel.error


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _user_key(event: dict[str, Any], fallback_ip: str | None) -> str | None:
    user = event.get("user") or {}
    if isinstance(user, dict):
        uid = user.get("id") or user.get("username") or user.get("email")
        if uid:
            return f"u:{uid}"
    if fallback_ip:
        ua = ((event.get("contexts") or {}).get("browser") or {}).get("name", "")
        return "ip:" + hashlib.sha256(
            f"{fallback_ip}|{ua}".encode("utf-8")
        ).hexdigest()[:16]
    return None


async def handle_event_entry(entry: dict[str, str]) -> None:
    """Worker hook registered via ``set_event_handler``."""
    if entry.get("item_type") != "event":
        return

    project_id = entry.get("project_id", "")
    error_project_id = entry.get("error_project_id", "")
    event_id = entry.get("event_id", "")
    received_at = _parse_iso(entry.get("received_at"))
    client_ip = entry.get("client_ip") or None
    user_agent = entry.get("user_agent") or None

    project = await ErrorProject.get(error_project_id) if error_project_id else None
    if project is None:
        logger.warning(
            "error-tracker pipeline: no ErrorProject for %s — dropping event %s",
            error_project_id,
            event_id,
        )
        return

    try:
        raw = orjson.loads(entry.get("payload", "{}"))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {"raw": entry.get("payload")}

    scrubbed = scrub_event(raw, scrub_ip=project.scrub_ip)

    fingerprint, title, culprit = compute_fingerprint(scrubbed)
    level = _coerce_level(scrubbed.get("level"))
    environment = scrubbed.get("environment") or None
    release = scrubbed.get("release") or None
    platform = scrubbed.get("platform") or "javascript"

    # ── Issue upsert (idempotent by (project_id, fingerprint)) ──
    coll = ErrorIssue.get_motor_collection()
    now = datetime.now(UTC)
    filt = {"project_id": project_id, "fingerprint": fingerprint}
    set_on_insert = {
        "project_id": project_id,
        "error_project_id": error_project_id,
        "fingerprint": fingerprint,
        "title": title,
        "culprit": culprit,
        "level": level.value,
        "platform": platform,
        "status": IssueStatus.unresolved.value,
        "first_seen": received_at,
        "last_seen": received_at,
        "event_count": 0,
        "user_count": 0,
        "release": release,
        "environment": environment,
        "linked_task_ids": [],
        "tags": scrubbed.get("tags") or {},
        "created_at": now,
        "updated_at": now,
    }
    # Use update_one so ``upserted_id`` tells us for certain whether
    # this was the first-ever occurrence of the fingerprint. A later
    # ``find_one`` is required either way (we need the document for
    # the auto-task creation path), but we only consult the boolean
    # from the write result to decide.
    upsert_res = await coll.update_one(
        filt, {"$setOnInsert": set_on_insert}, upsert=True
    )
    is_new_issue = upsert_res.upserted_id is not None
    res = await coll.find_one(filt)
    if res is None:
        logger.error(
            "error-tracker pipeline: upsert didn't return a doc for fp=%s",
            fingerprint,
        )
        return

    issue_id = str(res["_id"])

    # Counter enqueue (T5 / T11).
    user_key = _user_key(scrubbed, client_ip)
    try:
        await record_event_seen(issue_id, user_key, when=received_at)
    except Exception:
        logger.exception(
            "error-tracker pipeline: record_event_seen failed for issue=%s",
            issue_id,
        )

    # Persist event to the daily partition collection (PII-clean).
    day_coll = await get_event_collection_for_date(received_at)
    event_doc = {
        "event_id": event_id,
        "issue_id": issue_id,
        "project_id": project_id,
        "error_project_id": error_project_id,
        "fingerprint": fingerprint,
        "received_at": received_at,
        "timestamp": _parse_iso(str(scrubbed.get("timestamp")) if scrubbed.get("timestamp") else None),
        "platform": platform,
        "level": level.value,
        "message": scrubbed.get("message"),
        "exception": scrubbed.get("exception"),
        "breadcrumbs": scrubbed.get("breadcrumbs"),
        "request": scrubbed.get("request"),
        "user": scrubbed.get("user"),
        "tags": scrubbed.get("tags"),
        "contexts": scrubbed.get("contexts"),
        "release": release,
        "environment": environment,
        "sdk": scrubbed.get("sdk"),
        "user_agent": user_agent,
        "symbolicated": False,
    }
    try:
        await day_coll.insert_one(event_doc)
    except Exception as exc:
        if "E11000" in str(exc) or "duplicate" in str(exc).lower():
            # Idempotent replay (§4.5). Still worth tracking the counter,
            # which we already did above — no further action.
            return
        raise

    # Auto-task (T14) — only on the very first occurrence.
    if is_new_issue and project.auto_create_task_on_new_issue:
        try:
            # Re-fetch as Beanie model so we can mutate linked_task_ids.
            issue_doc = await ErrorIssue.get(issue_id)
            if issue_doc is not None:
                await create_task_for_new_issue(project, issue_doc)
        except Exception:
            logger.exception(
                "error-tracker pipeline: auto-task creation failed for issue=%s",
                issue_id,
            )


def install_real_handler() -> None:
    """Install the production handler on the worker singleton."""
    from .worker import set_event_handler

    set_event_handler(handle_event_entry)


__all__ = ["handle_event_entry", "install_real_handler"]
