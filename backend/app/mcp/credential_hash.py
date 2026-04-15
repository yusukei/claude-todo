"""Credential binding hash for MCP sessions.

Each MCP session stores ``auth_key_hash = HMAC(derived_key, domain || credential)``
in its Redis Hash and compares with ``hmac.compare_digest`` on every request.

The HMAC key is derived from ``SECRET_KEY`` via HKDF-SHA256 with a domain
label, so:

- rotating ``SECRET_KEY`` also invalidates MCP sessions (desirable — same
  cost as invalidating JWTs);
- a Redis dump alone cannot be used to offline-match candidate credentials
  without ``SECRET_KEY``;
- no new env var is required (satisfies CLAUDE.md's env-var discipline).

Domain separation (``apikey\\x00`` vs ``oauth\\x00``) prevents an API key
string from ever producing the same hash as an OAuth bearer token, even
if the raw bytes coincide.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
from typing import Literal

from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..core.config import settings


@functools.cache
def _mcp_hmac_key() -> bytes:
    """Derive the MCP-session HMAC key from ``SECRET_KEY`` via HKDF-SHA256."""
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=b"mcp-session-hmac-v1",
    ).derive(settings.SECRET_KEY.encode("utf-8"))


AuthKind = Literal["api_key", "oauth"]


def hash_credential(credential: str, kind: AuthKind) -> str:
    """Return a domain-separated HMAC of the credential.

    - ``kind="api_key"``: input is the raw API key string (e.g. ``mtodo_...``).
    - ``kind="oauth"``: input is the raw bearer token string. Binding to the
      token, not the subject claim, means a second valid token for the same
      user is a distinct credential and cannot hijack an existing session.
    """
    if kind == "api_key":
        material = b"mcp-apikey\x00" + credential.encode("utf-8")
    elif kind == "oauth":
        material = b"mcp-oauth\x00" + credential.encode("utf-8")
    else:  # pragma: no cover - Literal narrows this away at type-check time
        raise ValueError(f"unknown auth kind: {kind!r}")
    return hmac.new(_mcp_hmac_key(), material, hashlib.sha256).hexdigest()


def verify_credential_hash(stored_hash: str, credential: str, kind: AuthKind) -> bool:
    """Timing-safe comparison of ``stored_hash`` against the hash of ``credential``."""
    return hmac.compare_digest(stored_hash, hash_credential(credential, kind))
