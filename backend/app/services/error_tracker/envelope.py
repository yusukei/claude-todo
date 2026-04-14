"""Sentry-compatible envelope parser.

Implements the subset of the Sentry Developer Envelope spec required
by `@sentry/browser` / `@sentry/react` v7–v8 (§3.2–3.3 of the spec).

Envelope wire format::

    <envelope_header_json>\\n
    <item_header_json>\\n
    <item_payload>\\n
    <item_header_json>\\n
    <item_payload>\\n
    ...

- The first line is the envelope header (event_id, sent_at, sdk, ...).
- Each subsequent pair is one item: a JSON header + raw payload.
- ``length`` in the item header is the byte length of the payload;
  when absent, the payload extends to the next newline.

We implement a length-honouring parser because Sentry SDKs sometimes
embed payloads that themselves contain raw newlines (rare in
browsers, common in native SDKs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import orjson


class EnvelopeParseError(ValueError):
    """Raised when the envelope wire format is invalid."""


@dataclass(frozen=True)
class EnvelopeItem:
    type: str
    payload: bytes  # raw (may be JSON or another format)
    header: dict[str, Any]

    def json(self) -> Any:
        """Return the payload parsed as JSON, raising on failure."""
        try:
            return orjson.loads(self.payload)
        except Exception as exc:  # pragma: no cover — surfaced at call site
            raise EnvelopeParseError(
                f"item type={self.type} is not valid JSON: {exc}"
            ) from exc


@dataclass(frozen=True)
class Envelope:
    header: dict[str, Any]
    items: list[EnvelopeItem]

    @property
    def event_id(self) -> str | None:
        eid = self.header.get("event_id")
        return str(eid) if eid else None


def _decode_json_line(line: bytes) -> dict[str, Any]:
    try:
        obj = orjson.loads(line)
    except Exception as exc:
        raise EnvelopeParseError(f"invalid JSON in envelope: {exc}") from exc
    if not isinstance(obj, dict):
        raise EnvelopeParseError("envelope header or item header must be a JSON object")
    return obj


def parse_envelope(body: bytes) -> Envelope:
    """Parse a Sentry envelope.

    The parser is strict about structure (unterminated items raise)
    but tolerant about optional fields: an envelope without
    ``event_id`` is allowed (client reports, sessions), as is an
    item header without ``type`` (we preserve it as ``type=""``).

    We walk the body byte-by-byte rather than splitting on ``\\n``
    because item payloads can contain raw newlines when
    ``length`` is set.
    """

    if not body:
        raise EnvelopeParseError("empty envelope body")

    # 1) envelope header — everything up to first \n.
    nl = body.find(b"\n")
    if nl < 0:
        # Single-line body can still be a valid header-only envelope
        # (no items), e.g. a ping from the SDK. Accept it.
        header = _decode_json_line(body)
        return Envelope(header=header, items=[])

    header = _decode_json_line(body[:nl])
    pos = nl + 1
    items: list[EnvelopeItem] = []
    n = len(body)

    while pos < n:
        # Skip extra blank lines between items. Sentry spec treats
        # them as noise; the official Relay ignores them too.
        while pos < n and body[pos : pos + 1] == b"\n":
            pos += 1
        if pos >= n:
            break

        # 2) item header — up to next \n.
        nl = body.find(b"\n", pos)
        if nl < 0:
            raise EnvelopeParseError("envelope truncated in item header")
        item_hdr = _decode_json_line(body[pos:nl])
        pos = nl + 1
        item_type = str(item_hdr.get("type") or "")
        length_raw = item_hdr.get("length")

        # 3) item payload — either ``length`` bytes, or up to the
        # next newline, or EOF.
        if isinstance(length_raw, int) and length_raw >= 0:
            end = pos + length_raw
            if end > n:
                raise EnvelopeParseError(
                    f"item type={item_type!r} length={length_raw} exceeds "
                    f"envelope body ({n - pos} bytes available)"
                )
            payload = body[pos:end]
            pos = end
            # Consume the optional trailing \n that Sentry SDKs
            # emit after a length-prefixed payload.
            if pos < n and body[pos : pos + 1] == b"\n":
                pos += 1
        else:
            # Fallback: length omitted → payload runs to next \n.
            end = body.find(b"\n", pos)
            if end < 0:
                payload = body[pos:]
                pos = n
            else:
                payload = body[pos:end]
                pos = end + 1

        items.append(EnvelopeItem(type=item_type, payload=payload, header=item_hdr))

    return Envelope(header=header, items=items)


__all__ = ["Envelope", "EnvelopeItem", "EnvelopeParseError", "parse_envelope"]
