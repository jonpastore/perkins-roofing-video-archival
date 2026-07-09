"""Topic freshness detection — pure logic, no I/O.

Determines whether new source videos have appeared for a topic since its
articles were last generated.  Consumed by api/routes/topics.py to surface a
"fresh sources" signal in the topic search UI.
"""
from __future__ import annotations

from datetime import date, datetime


def _to_date(value) -> date | None:
    """Normalize an upload_date / timestamp to a ``datetime.date``.

    Handles:
      - None              → None
      - datetime          → .date()
      - date              → itself
      - str               → take first 10 chars, parse as ISO date; None on error
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def topic_freshness(video_upload_dates: list, latest_article_at) -> dict:
    """Compute freshness signal for a topic.

    Args:
        video_upload_dates: List of upload_date values (str, date, datetime, or
            None) for every source video belonging to the topic.
        latest_article_at:  The most recent article generation timestamp for
            this topic (datetime, date, str, or None).  None means no articles
            have been generated yet.

    Returns:
        {"stale": bool, "new_source_count": int}

        stale=False and new_source_count=0 when latest_article_at is None
        (topic has no articles — never stale).
        stale=True when at least one source video has an upload_date strictly
        greater than the article generation date.
    """
    article_date = _to_date(latest_article_at)
    if article_date is None:
        return {"stale": False, "new_source_count": 0}

    new_source_count = sum(
        1
        for raw in video_upload_dates
        if (d := _to_date(raw)) is not None and d > article_date
    )
    return {"stale": new_source_count > 0, "new_source_count": new_source_count}
