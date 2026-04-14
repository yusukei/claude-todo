"""Tests for daily partition collection helpers."""

from datetime import UTC, datetime

import pytest

from app.services.error_tracker.events import collection_name_for


@pytest.mark.parametrize(
    "dt,expected",
    [
        (datetime(2026, 4, 14, 12, 0, tzinfo=UTC), "error_events_20260414"),
        (datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "error_events_20260101"),
    ],
)
def test_collection_name_for(dt, expected):
    assert collection_name_for(dt) == expected
