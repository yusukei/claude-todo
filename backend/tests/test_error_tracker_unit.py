"""Unit tests for the error tracker pure modules (no DB / Redis)."""

from __future__ import annotations

import orjson
import pytest

from app.services.error_tracker.envelope import (
    EnvelopeParseError,
    parse_envelope,
)
from app.services.error_tracker.auth import (
    cors_headers_for,
    extract_public_key,
    normalize_origin,
    origin_allowed,
    parse_sentry_auth_header,
)
from app.services.error_tracker.fingerprint import compute_fingerprint
from app.services.error_tracker.scrubber import scrub_event
from app.models.error_tracker import ErrorTrackingConfig


# ── Envelope parser ───────────────────────────────────────────


def _mk_envelope(items: list[tuple[dict, dict | None]]) -> bytes:
    parts: list[bytes] = [orjson.dumps({"event_id": "abc"})]
    for hdr, payload in items:
        if payload is None:
            parts.append(orjson.dumps(hdr))
            parts.append(b"")
        else:
            body = orjson.dumps(payload)
            parts.append(orjson.dumps({**hdr, "length": len(body)}))
            parts.append(body)
    return b"\n".join(parts) + b"\n"


def test_envelope_parses_multiple_items():
    body = _mk_envelope([
        ({"type": "event"}, {"message": "hi"}),
        ({"type": "session"}, {"started": 1}),
    ])
    env = parse_envelope(body)
    assert env.event_id == "abc"
    assert [i.type for i in env.items] == ["event", "session"]
    assert env.items[0].json() == {"message": "hi"}


def test_envelope_lengthless_item_runs_to_newline():
    body = b'{"event_id":"x"}\n{"type":"event"}\n{"m":1}\n'
    env = parse_envelope(body)
    assert env.items[0].json() == {"m": 1}


def test_envelope_empty_body_rejected():
    with pytest.raises(EnvelopeParseError):
        parse_envelope(b"")


# ── Sentry-Auth header parser ─────────────────────────────────


def test_parse_sentry_auth_header_strips_scheme_and_splits():
    got = parse_sentry_auth_header(
        "Sentry sentry_version=7, sentry_key=abc, sentry_client=js/8.0.0"
    )
    assert got == {
        "sentry_version": "7",
        "sentry_key": "abc",
        "sentry_client": "js/8.0.0",
    }


def test_extract_public_key_falls_back_to_query():
    assert extract_public_key(auth_header=None, query={"sentry_key": "k"}) == "k"


# ── Origin normalisation ──────────────────────────────────────


@pytest.mark.parametrize(
    "origin,expected",
    [
        ("https://foo.example.com", "https://foo.example.com"),
        ("https://foo.example.com:443/x", "https://foo.example.com"),
        ("http://foo.example.com:80", "http://foo.example.com"),
        ("http://foo.example.com:8080", "http://foo.example.com:8080"),
        ("", None),
        (None, None),
        ("not-a-url", None),
    ],
)
def test_normalize_origin(origin, expected):
    assert normalize_origin(origin) == expected


def test_origin_allowed_empty_list_rejects_browser():
    p = ErrorTrackingConfig(project_id="p", allowed_origins=[])
    assert origin_allowed(p, None) is True  # server-to-server
    assert origin_allowed(p, "https://evil") is False


def test_origin_allowed_wildcard_lets_anything_through():
    p = ErrorTrackingConfig(
        project_id="p",
        allowed_origin_wildcard=True,
        allowed_origins=[],
    )
    assert origin_allowed(p, "https://foo.example.com") is True


def test_cors_headers_reflect_specific_origin_not_star():
    p = ErrorTrackingConfig(
        project_id="p",
        allowed_origins=["https://app.example.com"],
    )
    headers = cors_headers_for(p, "https://app.example.com")
    assert headers["Access-Control-Allow-Origin"] == "https://app.example.com"
    assert headers["Vary"] == "Origin"


# ── Fingerprint ───────────────────────────────────────────────


def test_fingerprint_stable_across_minor_changes():
    event = {
        "exception": {
            "values": [
                {
                    "type": "TypeError",
                    "value": "x is undefined",
                    "stacktrace": {
                        "frames": [
                            {"function": "main", "module": "App", "in_app": True},
                            {
                                "function": "handleClick",
                                "module": "App.Login",
                                "in_app": True,
                            },
                        ]
                    },
                }
            ]
        }
    }
    fp1, title, _ = compute_fingerprint(event)
    # Changing the message shouldn't change fingerprint.
    event2 = dict(event)
    event2["exception"]["values"][0]["value"] = "y is undefined"
    fp2, _, _ = compute_fingerprint(event2)
    assert fp1 == fp2
    assert title.startswith("TypeError:")


def test_fingerprint_user_override_wins():
    e = {"fingerprint": ["custom-key"], "message": "msg"}
    fp, _, _ = compute_fingerprint(e)
    assert len(fp) == 32


# ── Scrubber ──────────────────────────────────────────────────


def test_scrubber_filters_auth_header_and_cookie():
    e = {
        "request": {
            "headers": {
                "Authorization": "Bearer abc.def.ghi",
                "Cookie": "session=super-secret",
                "User-Agent": "okay",
            },
            "query_string": "token=abc&page=1",
        }
    }
    scrubbed = scrub_event(e)
    h = scrubbed["request"]["headers"]
    assert h["Authorization"] == "[filtered]"
    assert h["Cookie"] == "[filtered]"
    assert h["User-Agent"] == "okay"
    assert "token=[filtered]" in scrubbed["request"]["query_string"]


def test_scrubber_drops_frame_vars():
    e = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {"function": "f", "vars": {"password": "secret"}},
                        ]
                    }
                }
            ]
        }
    }
    scrubbed = scrub_event(e)
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame["vars"] is None


def test_scrubber_removes_user_ip_by_default():
    e = {"user": {"ip": "1.2.3.4", "id": "u1"}}
    out = scrub_event(e)
    assert "ip" not in out["user"]


def test_scrubber_masks_bearer_tokens_in_strings():
    e = {"extra": {"note": "Saw header: Authorization=Bearer abcdef12345"}}
    out = scrub_event(e)
    assert "Bearer [filtered]" in out["extra"]["note"]


# ── capture._build_sentry_event ───────────────────────────────


def test_capture_builds_valid_sentry_event():
    """_build_sentry_event returns a parseable event with the expected shape."""
    from app.services.error_tracker.capture import _build_sentry_event

    try:
        raise ValueError("boom")
    except ValueError as exc:
        eid, payload = _build_sentry_event(exc, extra={"key": "value"})

    event = orjson.loads(payload)
    assert event["event_id"] == eid
    assert event["platform"] == "python"
    assert event["level"] == "error"
    values = event["exception"]["values"]
    assert len(values) == 1
    assert values[0]["type"] == "ValueError"
    assert values[0]["value"] == "boom"
    # Stack frames must include this test file somewhere.
    frames = values[0]["stacktrace"]["frames"]
    assert any("test_error_tracker_unit" in (f.get("filename") or "") for f in frames)
    assert event["extra"] == {"key": "value"}


def test_capture_chains_exceptions():
    """Exception cause chain is captured innermost-first (Sentry convention)."""
    from app.services.error_tracker.capture import _build_sentry_event

    try:
        try:
            raise RuntimeError("root cause")
        except RuntimeError as inner:
            raise ValueError("wrapper") from inner
    except ValueError as exc:
        _, payload = _build_sentry_event(exc)

    event = orjson.loads(payload)
    values = event["exception"]["values"]
    # Two entries: innermost (RuntimeError) first, outermost (ValueError) last.
    assert len(values) == 2
    assert values[0]["type"] == "RuntimeError"
    assert values[1]["type"] == "ValueError"


@pytest.mark.asyncio
async def test_capture_no_project_logs_warning(caplog):
    """capture_exception warns (not raises) when no ErrorTrackingConfig exists."""
    import logging
    from app.services.error_tracker import capture as capture_mod

    # Reset cache so this test starts fresh.
    capture_mod._cached_ids = None

    with caplog.at_level(logging.WARNING, logger="app.services.error_tracker.capture"):
        await capture_mod.capture_exception(ValueError("test"))

    assert any("no ErrorTrackingConfig" in r.message for r in caplog.records)
