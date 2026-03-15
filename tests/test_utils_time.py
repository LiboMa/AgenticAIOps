"""Tests for src/utils/time.py — boost coverage for ensure_aware + utcnow."""

from datetime import datetime, timezone

from src.utils.time import ensure_aware, utcnow


class TestEnsureAware:
    def test_none_returns_utc_now(self):
        result = ensure_aware(None)
        assert result.tzinfo == timezone.utc

    def test_naive_datetime_gets_utc(self):
        naive = datetime(2026, 3, 15, 4, 0, 0)
        result = ensure_aware(naive)
        assert result.tzinfo == timezone.utc
        assert result.year == 2026

    def test_aware_datetime_returned_as_is(self):
        aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = ensure_aware(aware)
        assert result is aware

    def test_iso_string_with_z(self):
        result = ensure_aware("2026-01-01T00:00:00Z")
        assert result == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_iso_string_with_offset(self):
        result = ensure_aware("2026-06-15T12:30:00+00:00")
        assert result.tzinfo is not None


class TestUtcnow:
    def test_returns_aware(self):
        now = utcnow()
        assert now.tzinfo == timezone.utc
