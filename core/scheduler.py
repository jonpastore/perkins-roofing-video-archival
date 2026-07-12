"""Pure scheduling logic — select which scheduled_content rows are due for promotion.
Shared by articles and reels; the Cloud Scheduler cron calls the promoter which uses this."""
from datetime import datetime, timezone


def _as_naive_utc(dt):
    """Coerce a datetime to naive UTC so aware/naive values compare safely.

    Storage convention is naive UTC, but a stray offset-aware ``publish_at`` (or
    ``now``) would otherwise raise ``TypeError: can't compare offset-naive and
    offset-aware datetimes`` and abort promotion.
    """
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def due(rows, now):
    """Rows that should be promoted now: status 'scheduled' and publish_at <= now.
    rows are objects/dicts with .status and .publish_at (a naive UTC datetime)."""
    now = _as_naive_utc(now)
    out = []
    for r in rows:
        status = getattr(r, "status", None)
        publish_at = _as_naive_utc(getattr(r, "publish_at", None))
        if status == "scheduled" and publish_at is not None and publish_at <= now:
            out.append(r)
    return out
