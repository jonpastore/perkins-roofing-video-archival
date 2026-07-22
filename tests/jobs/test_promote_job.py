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


def test_promotion_syncs_article_status(monkeypatch):
    """Promoting an article must also set Article.status='published', not just the
    ScheduledContent row. Otherwise the article stays status='scheduled' and a later regen
    (which derives WP status from Article.status) silently reverts the live post to draft."""
    s = SessionLocal()
    _seed_article(s, "post", 303)
    s.commit()
    s.close()

    monkeypatch.setattr(PJ.wordpress, "update_status", lambda pid, st: None)
    PJ.run()

    s = SessionLocal()
    art = s.query(Article).filter(Article.slug == "post").one()
    sc = s.query(ScheduledContent).filter(ScheduledContent.ref_id == "post").one()
    s.close()
    assert sc.status == "published"
    assert art.status == "published"   # kept in sync — the desync-prevention fix


def test_promotion_submits_article_for_search_indexing(monkeypatch):
    """Promoting an article (with a live wp_post_id) must trigger the on-publish
    IndexNow + Google Indexing API submission (jobs/search_indexing_job.py covers
    the daily catch-up; this is the primary path)."""
    s = SessionLocal()
    _seed_article(s, "indexed-post", 404)
    s.commit()
    s.close()

    monkeypatch.setattr(PJ.wordpress, "update_status", lambda pid, st: None)
    calls = []
    monkeypatch.setattr(PJ.search_indexing, "submit_urls", lambda urls: calls.append(urls) or {"ok": True})
    # Admin-config WP_URL (resolved_wp_url), not env — see jobs/promote_job._submit_for_indexing.
    monkeypatch.setattr(PJ.wordpress, "resolved_wp_url", lambda: "https://perkinsroofing.net")

    PJ.run()

    assert len(calls) == 1
    assert calls[0] == ["https://perkinsroofing.net/", "https://perkinsroofing.net/indexed-post/"]


def test_indexing_failure_does_not_block_publish(monkeypatch):
    """Best-effort: if search_indexing.submit_urls RAISES, promote_job must still
    publish the article (the exception is swallowed in _submit_for_indexing, AFTER the
    WP status flip). Regression lock for the reviewer-flagged gap."""
    s = SessionLocal()
    _seed_article(s, "idx-fail", 505)
    s.commit()
    s.close()

    monkeypatch.setattr(PJ.wordpress, "update_status", lambda pid, st: None)

    def boom(urls):
        raise RuntimeError("indexnow 500")

    monkeypatch.setattr(PJ.search_indexing, "submit_urls", boom)

    result = PJ.run()

    assert result == {"promoted": 1, "errored": 0}   # indexing failure did NOT block the publish
    s = SessionLocal()
    art = s.query(Article).filter(Article.slug == "idx-fail").one()
    s.close()
    assert art.status == "published"


def test_promotion_without_wp_post_id_skips_indexing(monkeypatch):
    """No wp_post_id means the article was never actually published to WordPress —
    submitting its URL for indexing would be wrong (the page doesn't exist there)."""
    s = SessionLocal()
    s.add(Article(slug="no-wp-id", title="no-wp-id", content_md="x", status="scheduled", wp_post_id=None))
    s.add(ScheduledContent(kind="article", ref_id="no-wp-id", status="scheduled",
                           publish_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)))
    s.commit()
    s.close()

    calls = []
    monkeypatch.setattr(PJ.search_indexing, "submit_urls", lambda urls: calls.append(urls) or {"ok": True})

    PJ.run()
    assert calls == []


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
