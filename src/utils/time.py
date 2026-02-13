"""
Datetime utilities — single source of truth for timezone handling.

Rule: ALL internal datetimes must be timezone-aware (UTC).
External inputs (K8s, CloudWatch, CloudTrail) may be naive — wrap with ensure_aware().
"""

from datetime import datetime, timezone
from typing import Union


def ensure_aware(dt: Union[datetime, str, None]) -> datetime:
    """
    Ensure a datetime is timezone-aware (UTC).

    - naive datetime → assume UTC, add tzinfo
    - aware datetime → return as-is
    - ISO string → parse and ensure aware
    - None → return current UTC time

    Examples:
        >>> ensure_aware(datetime(2026, 1, 1))
        datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)

        >>> ensure_aware("2026-01-01T00:00:00Z")
        datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    """
    if dt is None:
        return datetime.now(timezone.utc)

    if isinstance(dt, str):
        # Normalize common formats
        dt = dt.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt)

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt


def utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)
