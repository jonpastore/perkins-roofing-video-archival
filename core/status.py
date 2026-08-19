"""Pure-logic helpers for the /status dashboard endpoint.

Extracted from api/app.py so they can be unit-tested without the full FastAPI
application (which pulls in google.auth and python-multipart).

All functions accept a SQLAlchemy session and return plain dicts.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Scheduled-content breakdown
# ---------------------------------------------------------------------------

def scheduled_breakdown(db: Session) -> dict:
    """Return article and social scheduled-content counts + next-up timestamps.

    Only rows with status='scheduled' are counted (published/error excluded).

    Returns::

        {
            "articles": {"count": int, "next_up": str | None},  # ISO datetime
            "social": {
                "<platform>": {"count": int, "next_up": str | None},
                ...
            }
        }
    """
    from app.models import ScheduledContent

    rows = (
        db.query(ScheduledContent)
        .filter(ScheduledContent.status == "scheduled")
        .all()
    )

    art_rows = [r for r in rows if r.kind == "article"]
    reel_rows = [r for r in rows if r.kind == "reel"]

    # Articles
    art_count = len(art_rows)
    art_dates = [r.publish_at for r in art_rows if r.publish_at is not None]
    art_next = min(art_dates).isoformat() if art_dates else None

    # Social: group by target platform
    platform_map: dict[str, list] = {}
    for r in reel_rows:
        platform = r.target or "unknown"
        platform_map.setdefault(platform, []).append(r)

    social: dict[str, dict] = {}
    for platform, platform_rows in platform_map.items():
        dates = [r.publish_at for r in platform_rows if r.publish_at is not None]
        social[platform] = {
            "count": len(platform_rows),
            "next_up": min(dates).isoformat() if dates else None,
        }

    return {
        "articles": {"count": art_count, "next_up": art_next},
        "social": social,
    }


# ---------------------------------------------------------------------------
# Action counters
# ---------------------------------------------------------------------------

def action_counters(db: Session) -> dict:
    """Return counts for actionable items on the dashboard.

    Returns::

        {
            "content_opportunities": int,  # topic labels not yet covered by an article
            "comments_pending": int,        # CommentDraft needs_reply=True, status pending/drafted
            "videos_pending": int,          # MiniSeries awaiting approval (approved=0)
        }
    """
    from app.models import Article, CommentDraft, GraphNode, MiniSeries

    # content_opportunities: unique topic labels not matched by any article title.
    # Deduped label set rather than raw node count — mirrors /suggestions/counts cheaply.
    articles = db.query(Article).all()
    article_titles_lower = {(a.title or "").strip().lower() for a in articles}

    topic_rows = db.query(GraphNode).filter(GraphNode.kind == "topics").all()
    topic_labels: set[str] = set()
    for row in topic_rows:
        if row.label:
            topic_labels.add(row.label.strip().lower())
    uncovered_topics = sum(1 for t in topic_labels if t not in article_titles_lower)

    comments_pending = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.needs_reply.is_(True),
            CommentDraft.status.in_(("pending", "drafted")),
        )
        .count()
    )

    videos_pending = (
        db.query(MiniSeries)
        .filter(MiniSeries.approved == 0)
        .count()
    )

    return {
        "content_opportunities": uncovered_topics,
        "comments_pending": comments_pending,
        "videos_pending": videos_pending,
    }


# Ingest cron: Cloud Scheduler `run-ingest` is `0 9-18 * * *` America/New_York,
# 25 videos/run, oldest video id first. Not a per-minute drain.
INGEST_HOUR_START = 9
INGEST_HOUR_END = 18
INGEST_BATCH = 25
INGEST_TZ_NAME = "America/New_York"


def next_ingest_at(now: datetime) -> datetime:
    """Next top-of-hour ingest fire in America/New_York, returned tz-aware."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    et = now.astimezone(ZoneInfo(INGEST_TZ_NAME))
    for hour in range(INGEST_HOUR_START, INGEST_HOUR_END + 1):
        cand = et.replace(hour=hour, minute=0, second=0, microsecond=0)
        if cand > et:
            return cand
    nxt = et + timedelta(days=1)
    return nxt.replace(hour=INGEST_HOUR_START, minute=0, second=0, microsecond=0)


def queue_wait_reason(
    *,
    status: str,
    archive_uri: str | None,
    now: datetime | None = None,
) -> str:
    """Why a pending/running ingest row has not finished."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    if status == "running":
        return "Worker has this stage now."
    if not archive_uri:
        return "Waiting for archive (07:30 ET) before STT can start."
    clock = now or datetime.now(timezone.utc)
    nxt = next_ingest_at(clock)
    et = clock.astimezone(ZoneInfo(INGEST_TZ_NAME))
    if INGEST_HOUR_START <= et.hour <= INGEST_HOUR_END:
        return (
            f"Ingest runs hourly {INGEST_HOUR_START}:00–{INGEST_HOUR_END}:00 ET, "
            f"{INGEST_BATCH} videos/run, oldest id first. Waiting its turn; next fire "
            f"{nxt.strftime('%H:%M')} ET."
        )
    return (
        f"Ingest is idle overnight. Next run {nxt.strftime('%H:%M')} ET "
        f"({INGEST_HOUR_START}:00–{INGEST_HOUR_END}:00, {INGEST_BATCH}/run)."
    )
