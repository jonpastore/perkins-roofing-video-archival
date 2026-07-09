"""Coverage tests for core/status.py — scheduled_breakdown and action_counters."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Article,
    Base,
    CommentDraft,
    GraphNode,
    MiniSeries,
    ScheduledContent,
)
from core.status import action_counters, scheduled_breakdown


@pytest.fixture()
def db():
    # Isolated in-memory DB per test — the suite-wide SessionLocal (conftest) shares
    # one SQLite file polluted with every prior wave's committed rows, which breaks
    # the "empty db" / exact-count assertions here. A fresh engine guarantees isolation.
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    session.info["platform_scope"] = True
    try:
        yield session
    finally:
        session.close()


_NOW = datetime(2026, 7, 9, 12, 0, 0)


class TestScheduledBreakdown:
    def test_empty_db_returns_zero_counts(self, db):
        result = scheduled_breakdown(db)
        assert result["articles"]["count"] == 0
        assert result["articles"]["next_up"] is None
        assert result["social"] == {}

    def test_article_scheduled_content_counted(self, db):
        db.add(ScheduledContent(
            kind="article", ref_id="slug-1",
            publish_at=_NOW, status="scheduled", target="wp",
        ))
        db.flush()
        result = scheduled_breakdown(db)
        assert result["articles"]["count"] == 1
        assert result["articles"]["next_up"] is not None

    def test_published_content_excluded(self, db):
        db.add(ScheduledContent(
            kind="article", ref_id="slug-2",
            publish_at=_NOW, status="published", target="wp",
        ))
        db.flush()
        result = scheduled_breakdown(db)
        assert result["articles"]["count"] == 0

    def test_social_reel_grouped_by_platform(self, db):
        db.add(ScheduledContent(
            kind="reel", ref_id="s1",
            publish_at=_NOW, status="scheduled", target="instagram",
        ))
        db.add(ScheduledContent(
            kind="reel", ref_id="s2",
            publish_at=_NOW, status="scheduled", target="tiktok",
        ))
        db.flush()
        result = scheduled_breakdown(db)
        assert "instagram" in result["social"]
        assert "tiktok" in result["social"]
        assert result["social"]["instagram"]["count"] == 1

    def test_next_up_is_earliest_date(self, db):
        early = datetime(2026, 7, 1, 0, 0, 0)
        late = datetime(2026, 8, 1, 0, 0, 0)
        db.add(ScheduledContent(kind="article", ref_id="a1",
                                publish_at=late, status="scheduled", target="wp"))
        db.add(ScheduledContent(kind="article", ref_id="a2",
                                publish_at=early, status="scheduled", target="wp"))
        db.flush()
        result = scheduled_breakdown(db)
        assert "2026-07-01" in result["articles"]["next_up"]

    def test_reel_without_publish_at_handled(self, db):
        db.add(ScheduledContent(
            kind="reel", ref_id="s3",
            publish_at=None, status="scheduled", target="instagram",
        ))
        db.flush()
        result = scheduled_breakdown(db)
        assert result["social"]["instagram"]["next_up"] is None


class TestActionCounters:
    def test_empty_db_all_zero(self, db):
        result = action_counters(db)
        assert result["content_opportunities"] == 0
        assert result["comments_pending"] == 0
        assert result["videos_pending"] == 0

    def test_comment_draft_needs_reply_counted(self, db):
        db.add(CommentDraft(
            video_id="v1", comment_id="c1",
            comment_text="hi", needs_reply=True, status="pending",
        ))
        db.flush()
        result = action_counters(db)
        assert result["comments_pending"] == 1

    def test_dismissed_comment_not_counted(self, db):
        db.add(CommentDraft(
            video_id="v2", comment_id="c2",
            comment_text="bye", needs_reply=True, status="dismissed",
        ))
        db.flush()
        result = action_counters(db)
        assert result["comments_pending"] == 0

    def test_mini_series_pending_approval_counted(self, db):
        db.add(MiniSeries(
            video_id="v3", title="Series 1",
            parts_json=[], approved=0,
        ))
        db.flush()
        result = action_counters(db)
        assert result["videos_pending"] >= 1

    def test_approved_series_not_counted(self, db):
        db.add(MiniSeries(
            video_id="v4", title="Approved",
            parts_json=[], approved=1,
        ))
        db.flush()
        result = action_counters(db)
        assert result["videos_pending"] == 0

    def test_uncovered_topic_counted_as_opportunity(self, db):
        db.add(GraphNode(
            video_id="v5", kind="topics", label="Roof Repair", start=0.0, version="1",
        ))
        db.flush()
        result = action_counters(db)
        assert result["content_opportunities"] >= 1

    def test_topic_covered_by_article_not_counted(self, db):
        db.add(GraphNode(
            video_id="v6", kind="topics", label="Shingle Replacement", start=0.0, version="1",
        ))
        db.add(Article(
            slug="shingle-replacement", title="Shingle Replacement",
            status="published", role="pillar",
        ))
        db.flush()
        result = action_counters(db)
        # "shingle replacement" matches article title — should not count as uncovered
        assert result["content_opportunities"] == 0
