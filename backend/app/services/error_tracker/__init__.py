"""Error tracker service layer.

Ingest API, workers, fingerprinting, scrubbing and MCP adapters live
here. See `Error Tracker (Sentry互換) 機能仕様 v2` and the v3 decision
addendum for the split across T1–T14.
"""

from .auth import (
    AuthError,
    AuthedProject,
    cors_headers_for,
    extract_public_key,
    normalize_origin,
    origin_allowed,
    parse_sentry_auth_header,
    resolve_error_project,
)
from .envelope import Envelope, EnvelopeItem, EnvelopeParseError, parse_envelope
from .events import (
    collection_name_for,
    drop_expired_event_collections,
    ensure_event_collection,
    get_event_collection_for_date,
    list_event_collections,
)
from .stream import CONSUMER_GROUP, STREAM_KEY, EnqueuedEvent, enqueue_event
from .worker import ErrorTrackerWorker, error_tracker_worker, set_event_handler

__all__ = [
    # events / partitioning (T1)
    "collection_name_for",
    "drop_expired_event_collections",
    "ensure_event_collection",
    "get_event_collection_for_date",
    "list_event_collections",
    # envelope parser (T2)
    "Envelope",
    "EnvelopeItem",
    "EnvelopeParseError",
    "parse_envelope",
    # auth + CORS (T3)
    "AuthError",
    "AuthedProject",
    "cors_headers_for",
    "extract_public_key",
    "normalize_origin",
    "origin_allowed",
    "parse_sentry_auth_header",
    "resolve_error_project",
    # stream producer + worker (T4)
    "STREAM_KEY",
    "CONSUMER_GROUP",
    "EnqueuedEvent",
    "enqueue_event",
    "ErrorTrackerWorker",
    "error_tracker_worker",
    "set_event_handler",
]
