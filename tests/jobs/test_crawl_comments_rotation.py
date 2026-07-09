"""Tests for crawl_comments rotation logic and KPI side-effect.

These tests exercise the video-selection ORDER (least-recently-crawled first,
never-crawled NULL first) and the KPI stamp side-effect, without making any
real YouTube API or LLM calls.

DB isolation: conftest.py sets DB_URL to a temp SQLite file before collection.
We share that same DB (so app.models.SessionLocal and crawl_comments.run() see
the same data) and wipe the tables we touch in each fixture.
"""
import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import CommentDraft, SessionLocal, Video, init_db

# Ensure tables exist
init_db()


@pytest.fixture(autouse=True)
def clean_db():
    with SessionLocal() as db:
        db.query(CommentDraft).delete()
        db.query(Video).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(CommentDraft).delete()
        db.query(Video).delete()
        db.commit()


def _make_video(vid_id: str, crawled_at: datetime | None = None) -> Video:
    return Video(id=vid_id, title=f"Video {vid_id}", comments_crawled_at=crawled_at)


def _utc(days_ago: int) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(tzinfo=None)


def _crawl_run(**kwargs):
    """Import and call crawl_comments.run() fresh each time (module may be cached)."""
    import jobs.crawl_comments as cc
    importlib.reload(cc)
    return cc.run(**kwargs)


# ---------------------------------------------------------------------------
# Rotation ordering tests
# ---------------------------------------------------------------------------

def test_never_crawled_comes_first():
    """Videos with NULL comments_crawled_at must be processed before older ones."""
    with SessionLocal() as db:
        db.add(_make_video("old", crawled_at=_utc(10)))
        db.add(_make_video("never", crawled_at=None))
        db.add(_make_video("recent", crawled_at=_utc(1)))
        db.commit()

    processed_order = []

    def fake_fetch(video_id, max_results=20, owner_channel_id=None):
        processed_order.append(video_id)
        return []

    import jobs.crawl_comments as cc
    with (
        patch.object(cc, "fetch_comments", side_effect=fake_fetch),
        patch.object(cc, "fetch_stats", return_value={}),
        patch.object(cc, "chat", return_value="draft"),
    ):
        # max_drafts must be > 0; passing 0 triggers immediate break before first video
        cc.run(limit=3, max_drafts=999)

    assert len(processed_order) == 3, f"Expected 3 videos processed, got: {processed_order}"
    assert processed_order[0] == "never", (
        f"NULL comments_crawled_at must sort first, got order: {processed_order}"
    )


def test_oldest_crawled_comes_before_recent():
    """Among crawled videos, the oldest crawled_at must be processed first."""
    with SessionLocal() as db:
        db.add(_make_video("a_recent", crawled_at=_utc(1)))
        db.add(_make_video("b_old", crawled_at=_utc(7)))
        db.add(_make_video("c_older", crawled_at=_utc(14)))
        db.commit()

    processed_order = []

    def fake_fetch(video_id, max_results=20, owner_channel_id=None):
        processed_order.append(video_id)
        return []

    import jobs.crawl_comments as cc
    with (
        patch.object(cc, "fetch_comments", side_effect=fake_fetch),
        patch.object(cc, "fetch_stats", return_value={}),
        patch.object(cc, "chat", return_value="draft"),
    ):
        cc.run(limit=3, max_drafts=999)

    assert processed_order == ["c_older", "b_old", "a_recent"], (
        f"Expected oldest-first order, got: {processed_order}"
    )


def test_limit_caps_videos_processed():
    """The `limit` argument must cap how many videos are processed."""
    with SessionLocal() as db:
        for i in range(10):
            db.add(_make_video(f"vid_{i:02d}"))
        db.commit()

    processed = []

    def fake_fetch(video_id, max_results=20, owner_channel_id=None):
        processed.append(video_id)
        return []

    import jobs.crawl_comments as cc
    with (
        patch.object(cc, "fetch_comments", side_effect=fake_fetch),
        patch.object(cc, "fetch_stats", return_value={}),
        patch.object(cc, "chat", return_value="draft"),
    ):
        cc.run(limit=4, max_drafts=999)

    assert len(processed) == 4, f"Expected 4 processed, got {len(processed)}"


def test_crawled_at_stamped_after_run():
    """Every processed video must have comments_crawled_at set after the run."""
    with SessionLocal() as db:
        db.add(_make_video("stamp_me", crawled_at=None))
        db.commit()

    import jobs.crawl_comments as cc
    with (
        patch.object(cc, "fetch_comments", return_value=[]),
        patch.object(cc, "fetch_stats", return_value={}),
        patch.object(cc, "chat", return_value="draft"),
    ):
        cc.run(limit=1, max_drafts=999)

    with SessionLocal() as db:
        v = db.get(Video, "stamp_me")
        assert v.comments_crawled_at is not None, "comments_crawled_at must be set after crawl"


# ---------------------------------------------------------------------------
# KPI side-effect tests
# ---------------------------------------------------------------------------

def test_kpi_stats_stamped_after_crawl():
    """crawl_comments must update views/likes/comment_count + kpis_polled_at."""
    with SessionLocal() as db:
        db.add(_make_video("kpi_vid", crawled_at=None))
        db.commit()

    fake_stats = {
        "kpi_vid": {"views": 1234, "likes": 56, "comments": 7},
    }

    import jobs.crawl_comments as cc
    with (
        patch.object(cc, "fetch_comments", return_value=[]),
        patch.object(cc, "fetch_stats", return_value=fake_stats),
        patch.object(cc, "chat", return_value="draft"),
    ):
        cc.run(limit=1, max_drafts=999)

    with SessionLocal() as db:
        v = db.get(Video, "kpi_vid")
        assert v.views == 1234
        assert v.likes == 56
        assert v.comment_count == 7
        assert v.kpis_polled_at is not None, "kpis_polled_at must be set after KPI refresh"


def test_kpi_fetch_failure_does_not_abort_crawl():
    """A KPI stats fetch failure must not propagate — summary is still returned."""
    with SessionLocal() as db:
        db.add(_make_video("resilient", crawled_at=None))
        db.commit()

    import jobs.crawl_comments as cc
    with (
        patch.object(cc, "fetch_comments", return_value=[]),
        patch.object(cc, "fetch_stats", side_effect=RuntimeError("quota")),
        patch.object(cc, "chat", return_value="draft"),
    ):
        result = cc.run(limit=1, max_drafts=999)

    assert "videos_processed" in result
    assert result["videos_processed"] == 1
