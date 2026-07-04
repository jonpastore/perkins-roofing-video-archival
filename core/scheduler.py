"""Pure scheduling logic — select which scheduled_content rows are due for promotion.
Shared by articles and reels; the Cloud Scheduler cron calls the promoter which uses this."""


def due(rows, now):
    """Rows that should be promoted now: status 'scheduled' and publish_at <= now.
    rows are objects/dicts with .status and .publish_at (a naive UTC datetime)."""
    out = []
    for r in rows:
        status = getattr(r, "status", None)
        publish_at = getattr(r, "publish_at", None)
        if status == "scheduled" and publish_at is not None and publish_at <= now:
            out.append(r)
    return out
