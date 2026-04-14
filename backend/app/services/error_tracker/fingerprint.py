"""Fingerprint computation (spec §5).

Clusters events into ``ErrorIssue`` rows. The algorithm is
designed to stay stable across minified deployments: we pick the
top 3 in-app frames (resolved > raw) and combine them with the
exception type. Anonymous / eval frames fall back to
``filename:lineno``.
"""

from __future__ import annotations

import hashlib
from typing import Any

FP_LEN = 32  # hex chars — sha256 prefix


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:FP_LEN]


def _frame_key(frame: dict[str, Any]) -> str:
    fn = (frame.get("function") or "").strip()
    module = frame.get("module") or ""
    filename = frame.get("filename") or "?"
    lineno = frame.get("lineno") or "?"
    if not fn or fn in ("<anonymous>", "eval"):
        return f"@{filename}:{lineno}"
    return f"{module}.{fn}"


def compute_fingerprint(event: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(fingerprint, title, culprit)``.

    ``title`` / ``culprit`` are populated alongside so callers
    don't re-derive them from the raw event.
    """
    # User-supplied fingerprint wins outright (Sentry convention).
    if isinstance(event.get("fingerprint"), list) and event["fingerprint"]:
        key = "|".join(str(p) for p in event["fingerprint"])
        title = str(event.get("message") or event["fingerprint"][0])[:255]
        return _hash(key), title, ""

    exc_values = (event.get("exception") or {}).get("values") or []
    exc = exc_values[0] if exc_values else {}
    exc_type = str(exc.get("type") or "Error")
    exc_value = str(exc.get("value") or "")[:255]
    title = f"{exc_type}: {exc_value}" if exc_value else exc_type

    frames = ((exc.get("stacktrace") or {}).get("frames")) or []
    resolved = [f for f in frames if isinstance(f, dict) and f.get("resolved")]
    chosen = resolved or [f for f in frames if isinstance(f, dict)]
    in_app = [f for f in reversed(chosen) if f.get("in_app")]
    pick = (in_app or list(reversed(chosen)))[:3]

    if pick:
        key_str = f"{exc_type}|" + "|".join(_frame_key(f) for f in pick)
        culprit = _frame_key(pick[0])
    else:
        msg = (event.get("message") or exc_value or "")[:80]
        key_str = f"{exc_type}|msg:{msg}"
        culprit = ""

    return _hash(key_str), title[:255], culprit[:255]


__all__ = ["compute_fingerprint", "FP_LEN"]
