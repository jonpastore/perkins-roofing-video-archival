"""Regression: a failing row in promote_job must NOT roll back rows already promoted
in the same run (per-row commit). Previously a single mid-loop rollback + trailing
commit reverted every prior promotion and inflated the count."""
from datetime import datetime, timedelta, timezone

import pytest

import jobs.promote_job as PJ
from app.models import Article, Base, ScheduledContent, SessionLocal, engine


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _seed_article(s, slug, wp_post_id):
    s.add(Article(slug=slug, title=slug, content_md="x", status="scheduled", wp_post_id=wp_post_id))
    s.add(ScheduledContent(kind="article", ref_id=slug, status="scheduled",
                           publish_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)))


def test_failing_row_does_not_revert_prior_promotions(monkeypatch):
    s = SessionLocal()
    _seed_article(s, "good", 101)
    _seed_article(s, "bad", 202)
    s.commit(); s.close()

    # second article's WordPress publish fails; first must remain published
    def fake_update_status(post_id, status):
        if post_id == 202:
            raise RuntimeError("WP 500")

    monkeypatch.setattr(PJ.wordpress, "update_status", fake_update_status)
    result = PJ.run()

    assert result == {"promoted": 1, "errored": 1}
    s = SessionLocal()
    by_ref = {r.ref_id: r.status for r in s.query(ScheduledContent).all()}
    s.close()
    assert by_ref["good"] == "published"   # NOT reverted by the later failure
    assert by_ref["bad"] == "error"


def test_reel_moves_to_awaiting_social(monkeypatch):
    s = SessionLocal()
    s.add(ScheduledContent(kind="reel", ref_id="7", status="scheduled",
                           publish_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)))
    s.commit(); s.close()
    result = PJ.run()
    assert result == {"promoted": 1, "errored": 0}
    s = SessionLocal()
    row = s.query(ScheduledContent).one()
    s.close()
    assert row.status == "awaiting_social"
