"""PII scrubbing for Sentry-compatible events (T6 / spec §8.3).

Scrubbing runs inside the worker, *after* ingest ACKed the HTTP
request, *before* the event is persisted or its fingerprint is
computed. We deliberately apply it to a deep copy so the caller
can still see the original for debugging when needed.

The rules are kept in data (dict / list of regex) so operators
can tune them without touching this code.
"""

from __future__ import annotations

import copy
import re
from typing import Any

FILTERED = "[filtered]"

# Case-insensitive key-name matches. When a dict key matches we
# replace its value with ``[filtered]`` entirely — we do not peek
# at the value at all.
_SENSITIVE_KEY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^authorization$",
        r"^cookie$",
        r"^set-cookie$",
        r"^x-api-key$",
        r"^x-auth-token$",
        r"^x-csrf-token$",
        r".*password.*",
        r".*secret.*",
        r".*token.*",
        r".*api[_-]?key.*",
        r".*credential.*",
        r".*session[_-]?id.*",
    )
]

# Sub-key matches used inside a containers' string value — applied
# after the dict walk so string values with inline secrets are
# still filtered even when the container's key is innocuous.
_VALUE_SUBSTITUTIONS = [
    (
        re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
        "Bearer [filtered]",
    ),
    # JWT-ish triple-base64 tokens.
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
        "[filtered-jwt]",
    ),
    # Stripe-style live keys / AWS access keys.
    (re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"), "[filtered-stripe]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[filtered-aws]"),
    # Email addresses inside arbitrary strings → mask local part.
    (
        re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"),
        r"\1***@\2",
    ),
]

# Query-string parameter names whose values get replaced wholesale.
_QS_SENSITIVE_PARAMS = {
    "token",
    "access_token",
    "id_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "jwt",
    "auth",
    "authorization",
}


def _scrub_str(s: str) -> str:
    for pattern, repl in _VALUE_SUBSTITUTIONS:
        s = pattern.sub(repl, s)
    return s


def _scrub_qs(qs: str) -> str:
    """Rewrite ``a=1&token=xxx`` preserving order, filtering values."""
    if "=" not in qs and "&" not in qs:
        return qs
    parts: list[str] = []
    for pair in qs.split("&"):
        if "=" in pair:
            k, _, v = pair.partition("=")
            if k.lower() in _QS_SENSITIVE_PARAMS:
                parts.append(f"{k}={FILTERED}")
                continue
            parts.append(f"{k}={_scrub_str(v)}")
        else:
            parts.append(pair)
    return "&".join(parts)


def _is_sensitive_key(key: str) -> bool:
    return any(p.match(key) for p in _SENSITIVE_KEY_PATTERNS)


def _scrub_obj(obj: Any, *, in_vars: bool = False) -> Any:
    # Frame-local ``vars`` block is always dropped wholesale per
    # spec §8.3 — the hit-rate of secrets is too high.
    if in_vars:
        return None
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            k_str = str(k)
            lower = k_str.lower()
            if _is_sensitive_key(k_str):
                out[k_str] = FILTERED
            elif lower == "vars":
                out[k_str] = None  # spec §8.3: drop local variables
            elif lower == "query_string" and isinstance(v, str):
                out[k_str] = _scrub_qs(v)
            elif lower == "url" and isinstance(v, str):
                out[k_str] = _scrub_url(v)
            else:
                out[k_str] = _scrub_obj(v)
        return out
    if isinstance(obj, list):
        return [_scrub_obj(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub_obj(item) for item in obj)
    if isinstance(obj, str):
        return _scrub_str(obj)
    return obj


def _scrub_url(u: str) -> str:
    """Strip query-string secrets from a URL string."""
    if "?" not in u:
        return _scrub_str(u)
    base, _, qs = u.partition("?")
    fragment = ""
    if "#" in qs:
        qs, _, fragment = qs.partition("#")
    cleaned = _scrub_qs(qs)
    out = f"{base}?{cleaned}"
    if fragment:
        out = f"{out}#{fragment}"
    return out


def scrub_event(event: dict[str, Any], *, scrub_ip: bool = True) -> dict[str, Any]:
    """Return a scrubbed deep-copy of an event payload."""
    scrubbed = _scrub_obj(copy.deepcopy(event))
    # User block: explicit IP handling (§8.3 / §19.2).
    user = scrubbed.get("user") if isinstance(scrubbed, dict) else None
    if isinstance(user, dict):
        if scrub_ip:
            user.pop("ip", None)
            user.pop("ip_address", None)
        email = user.get("email")
        if isinstance(email, str) and "@" in email:
            user["email"] = _scrub_str(email)
    return scrubbed  # type: ignore[return-value]


__all__ = ["scrub_event"]
