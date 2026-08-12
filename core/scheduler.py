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


#: How many times a failed promotion is retried before the row is left alone. Bounded so a
#: genuinely broken row stops instead of hammering WordPress every 15 minutes forever.
PROMOTE_MAX_ATTEMPTS = 5

#: Statuses the promoter may claim. 'error' is here deliberately — see due().
#:
#: Anything NOT listed is skipped, which is how a row gets parked on purpose. 'held' is used
#: for exactly that: a human decided this item must not publish yet (2026-08-12 — seven
#: production-targeted articles held back while the client's own site was mid-rebuild). It is
#: deliberately distinct from 'error', so "we chose not to publish this" is never mistaken for
#: "this failed", and flipping it back to 'scheduled' is all it takes to release.
CLAIMABLE = ("scheduled", "error")


def due(rows, now):
    """Rows that should be promoted now: publish_at <= now, and either never tried
    ('scheduled') or failed fewer than PROMOTE_MAX_ATTEMPTS times ('error').

    ⚠️ 'error' MUST stay claimable. It used to be terminal — due() and the row-claim both
    required status == 'scheduled', so one transient failure parked an article permanently
    while the cron kept reporting success. Measured in prod 2026-08-12: 277 rows stuck in
    'error', all overdue, from WordPress 401s (2026-07-27/28) and 403s (2026-08-04/07) that
    had both since cleared. Every one of them would have published on a later run if anything
    had been willing to try again.

    rows are objects/dicts with .status, .publish_at (naive UTC) and .attempts.
    """
    now = _as_naive_utc(now)
    out = []
    for r in rows:
        status = getattr(r, "status", None)
        publish_at = _as_naive_utc(getattr(r, "publish_at", None))
        if publish_at is None or publish_at > now:
            continue
        if status == "scheduled":
            out.append(r)
        elif status == "error" and (getattr(r, "attempts", 0) or 0) < PROMOTE_MAX_ATTEMPTS:
            out.append(r)
    return out
