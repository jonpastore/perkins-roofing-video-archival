"""Canonical datetime helpers for API serialization and scheduler storage.

The app stores most timestamps as naive UTC datetimes. Returning bare
``datetime.isoformat()`` strings makes browsers parse them as local time, which
can make scheduled dates look wrong. Use ``iso_utc`` for API responses.

Scheduling forms submit naive ``datetime-local`` values; for Perkins publishing
workflows those are America/New_York wall time. Use ``to_naive_utc`` before
persisting schedule inputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_PUBLISH_TZ = ZoneInfo("America/New_York")


def iso_utc(dt: datetime | None) -> str | None:
    """Serialize a datetime as ISO-8601 UTC with a trailing ``Z``.

    Naive datetimes are interpreted as UTC by storage convention; aware datetimes
    are converted to UTC first.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def to_naive_utc(dt: datetime, default_tz: ZoneInfo = DEFAULT_PUBLISH_TZ) -> datetime:
    """Normalize API input to naive UTC storage.

    Naive datetimes are treated as ``default_tz`` wall time; aware datetimes are
    converted from their supplied offset.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
