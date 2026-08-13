"""Pure scheduling logic — select which scheduled_content rows are due for promotion.
Shared by articles and reels; the Cloud Scheduler cron calls the promoter which uses this."""
from datetime import datetime, timedelta, timezone


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

#: In-flight states, and what each releases BACK to when a claim is reaped.
#: Neither is in CLAIMABLE — that is the point of a claim — so a row left in one by a process
#: that died is invisible forever. See migration 0059.
IN_FLIGHT_RELEASE: dict[str, str] = {
    "promoting": "error",           # promote_job's own except path uses 'error' too
    "publishing": "awaiting_social",  # social_job's finally reverts to this
}

#: How long a claim may be held before it is assumed dead. Comfortably above both the promote
#: cron's 15-minute period and any real publish, so a LIVE sibling is never stolen from.
STALE_CLAIM_MINUTES = 30


def stale_claims(rows, now, *, minutes: int = STALE_CLAIM_MINUTES):
    """Rows whose in-flight claim is old enough to be presumed dead.

    A row is stale when it is in an in-flight state AND (claimed_at is older than *minutes*, OR
    claimed_at is NULL). NULL counts because rows stranded BEFORE migration 0059 have no stamp —
    without that clause the very rows this exists to rescue would be skipped forever.

    Deliberately conservative: only time can distinguish a dead holder from a live one, so the
    threshold is well past any plausible runtime rather than tight.
    """
    now = _as_naive_utc(now)
    cutoff = now - timedelta(minutes=minutes)
    out = []
    for r in rows:
        status = getattr(r, "status", None) if not isinstance(r, dict) else r.get("status")
        if status not in IN_FLIGHT_RELEASE:
            continue
        claimed = getattr(r, "claimed_at", None) if not isinstance(r, dict) else r.get("claimed_at")
        if claimed is None or _as_naive_utc(claimed) <= cutoff:
            out.append(r)
    return out


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
