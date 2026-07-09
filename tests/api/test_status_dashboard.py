"""Tests for the extended /status dashboard helpers (core/status.py).

Tests core.status.scheduled_breakdown and core.status.action_counters directly
— no api.app import (avoids google.auth / python-multipart dev-env gaps).
These helpers are wired into GET /status in api/app.py.
"""
import os
import tempfile
from datetime import datetime

import pytest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from app.models import (  # noqa: E402
    Article,
    Base,
    CommentDraft,
    GraphNode,
    MiniSeries,
    ScheduledContent,
    SessionLocal,
    Video,
    engine,
    init_db,
)
from core.status import action_counters, scheduled_breakdown  # noqa: E402

Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with SessionLocal() as db:
        db.query(CommentDraft).delete()
        db.query(MiniSeries).delete()
        db.query(ScheduledContent).delete()
        db.query(GraphNode).delete()
        db.query(Article).delete()
        db.query(Video).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(CommentDraft).delete()
        db.query(MiniSeries).delete()
        db.query(ScheduledContent).delete()
        db.query(GraphNode).delete()
        db.query(Article).delete()
        db.query(Video).delete()
        db.commit()


# ---------------------------------------------------------------------------
# scheduled_breakdown — shape
# ---------------------------------------------------------------------------

def test_breakdown_shape_empty_db():
    """Empty DB: articles.count=0, articles.next_up=None, social={}."""
    with SessionLocal() as db:
        result = scheduled_breakdown(db)
    assert result["articles"]["count"] == 0
    assert result["articles"]["next_up"] is None
    assert result["social"] == {}


def test_breakdown_has_required_keys():
    with SessionLocal() as db:
        result = scheduled_breakdown(db)
    assert "articles" in result
    assert "social" in result
    assert "count" in result["articles"]
    assert "next_up" in result["articles"]


# ---------------------------------------------------------------------------
# scheduled_breakdown — articles
# ---------------------------------------------------------------------------

def test_breakdown_articles_counts_only_scheduled():
    """Only status='scheduled' rows count; 'published' and 'error' are excluded."""
    with SessionLocal() as db:
        db.add(ScheduledContent(kind="article", ref_id="a", status="scheduled",
                                publish_at=datetime(2026, 9, 1)))
        db.add(ScheduledContent(kind="article", ref_id="b", status="scheduled",
                                publish_at=datetime(2026, 9, 2)))
        db.add(ScheduledContent(kind="article", ref_id="c", status="published",
                                publish_at=datetime(2026, 8, 1)))
        db.commit()
        result = scheduled_breakdown(db)
    assert result["articles"]["count"] == 2


def test_breakdown_articles_next_up_is_earliest():
    """next_up must be the earliest scheduled publish_at."""
    with SessionLocal() as db:
        db.add(ScheduledContent(kind="article", ref_id="a", status="scheduled",
                                publish_at=datetime(2026, 10, 5)))
        db.add(ScheduledContent(kind="article", ref_id="b", status="scheduled",
                                publish_at=datetime(2026, 9, 1)))
        db.commit()
        result = scheduled_breakdown(db)
    assert result["articles"]["next_up"] is not None
    assert "2026-09-01" in result["articles"]["next_up"]


def test_breakdown_articles_next_up_none_when_no_dates():
    """next_up is None when no publish_at is set."""
    with SessionLocal() as db:
        db.add(ScheduledContent(kind="article", ref_id="x", status="scheduled",
                                publish_at=None))
        db.commit()
        result = scheduled_breakdown(db)
    assert result["articles"]["count"] == 1
    assert result["articles"]["next_up"] is None


# ---------------------------------------------------------------------------
# scheduled_breakdown — social
# ---------------------------------------------------------------------------

def test_breakdown_social_groups_by_platform():
    """Reel rows with status='scheduled' are grouped by target platform."""
    with SessionLocal() as db:
        db.add(ScheduledContent(kind="reel", ref_id="1", status="scheduled",
                                target="instagram", publish_at=datetime(2026, 9, 5)))
        db.add(ScheduledContent(kind="reel", ref_id="2", status="scheduled",
                                target="instagram", publish_at=datetime(2026, 9, 6)))
        db.add(ScheduledContent(kind="reel", ref_id="3", status="scheduled",
                                target="tiktok", publish_at=datetime(2026, 9, 7)))
        db.commit()
        result = scheduled_breakdown(db)
    assert result["social"]["instagram"]["count"] == 2
    assert result["social"]["tiktok"]["count"] == 1


def test_breakdown_social_excludes_published():
    """Published reel rows must not appear in social counts."""
    with SessionLocal() as db:
        db.add(ScheduledContent(kind="reel", ref_id="1", status="published",
                                target="instagram", publish_at=datetime(2026, 8, 1)))
        db.commit()
        result = scheduled_breakdown(db)
    assert "instagram" not in result["social"]


def test_breakdown_social_next_up_per_platform():
    """Each platform entry must have next_up = earliest scheduled publish_at for that platform."""
    with SessionLocal() as db:
        db.add(ScheduledContent(kind="reel", ref_id="x", status="scheduled",
                                target="instagram", publish_at=datetime(2026, 11, 1)))
        db.add(ScheduledContent(kind="reel", ref_id="y", status="scheduled",
                                target="instagram", publish_at=datetime(2026, 10, 1)))
        db.commit()
        result = scheduled_breakdown(db)
    assert "2026-10-01" in result["social"]["instagram"]["next_up"]


# ---------------------------------------------------------------------------
# action_counters
# ---------------------------------------------------------------------------

def test_action_counters_shape():
    with SessionLocal() as db:
        result = action_counters(db)
    for key in ("content_opportunities", "comments_pending", "videos_pending"):
        assert key in result, f"missing key: {key}"
        assert isinstance(result[key], int), f"{key} must be int"
        assert result[key] >= 0


def test_comments_pending_counts_flagged_undecided():
    """comments_pending counts needs_reply=True rows in pending/drafted states only."""
    with SessionLocal() as db:
        vid = Video(id="v1", title="T")
        db.add(vid)
        db.flush()
        db.add(CommentDraft(video_id="v1", comment_id="c1", author="A",
                            comment_text="help?", needs_reply=True, status="pending"))
        db.add(CommentDraft(video_id="v1", comment_id="c2", author="B",
                            comment_text="nice", needs_reply=True, status="drafted"))
        db.add(CommentDraft(video_id="v1", comment_id="c3", author="C",
                            comment_text="ok", needs_reply=True, status="ready"))   # skip
        db.add(CommentDraft(video_id="v1", comment_id="c4", author="D",
                            comment_text="spam", needs_reply=False, status="pending"))  # skip
        db.commit()
        result = action_counters(db)
    assert result["comments_pending"] == 2


def test_videos_pending_counts_unapproved_series():
    """videos_pending counts MiniSeries rows with approved=0."""
    with SessionLocal() as db:
        db.add(Video(id="v2", title="T2"))
        db.flush()
        db.add(MiniSeries(video_id="v2", title="S1", parts_json=[], approved=0))
        db.add(MiniSeries(video_id="v2", title="S2", parts_json=[], approved=0))
        db.add(MiniSeries(video_id="v2", title="S3", parts_json=[], approved=1))  # skip
        db.commit()
        result = action_counters(db)
    assert result["videos_pending"] == 2


def test_content_opportunities_excludes_covered_topics():
    """Topics whose label matches an article title must not count as opportunities."""
    from app.models import GraphNode
    with SessionLocal() as db:
        db.add(GraphNode(video_id="v3", kind="topics", label="Roof Repair",
                         start=1.0, version="v1"))
        db.add(GraphNode(video_id="v3", kind="topics", label="Gutters",
                         start=2.0, version="v1"))
        db.add(Article(slug="roof-repair", title="Roof Repair", content_md="",
                       role="pillar", status="published"))
        db.add(Video(id="v3", title="T3"))
        db.commit()
        result = action_counters(db)
    # "Roof Repair" covered by article → only "Gutters" counts
    assert result["content_opportunities"] == 1


def test_action_counters_all_zero_empty_db():
    with SessionLocal() as db:
        result = action_counters(db)
    assert result["comments_pending"] == 0
    assert result["videos_pending"] == 0
    assert result["content_opportunities"] == 0
