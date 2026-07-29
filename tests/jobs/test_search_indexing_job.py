"""Behavioral tests for jobs/search_indexing_job.py (jobs/ are coverage-omitted).

adapters.search_indexing.submit_urls is monkeypatched — real HTTP is validated
separately in tests/adapters/test_search_indexing.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

import jobs.search_indexing_job as J
from app.models import Article, SessionLocal, init_db

# Ensure tables exist — same pattern as tests/jobs/test_crawl_comments_rotation.py.
init_db()


@pytest.fixture(autouse=True)
def _fresh_db():
    """Ensure tables exist, then wipe only the rows this file touches. Never drop.

    The shared sqlite DB makes this suite order-sensitive in BOTH directions:

    - Dropping at teardown breaks others. Modules like test_crawl_comments_rotation.py call
      init_db() at import (pytest imports every module during collection, before any test) and
      then only DELETE rows; a drop_all teardown tears their tables out. A new file doing that
      caused 8 "no such table: comment_drafts" errors on 2026-07-28.
    - Not creating at setup breaks you. Several suites still drop_all at teardown, so a file
      that only deletes rows can find its tables already gone — converting this fixture to
      pure row-deletes produced "no such table: articles" here.

    init_db() is create_all, which is idempotent and self-healing, so create-but-never-drop is
    safe against both. Row deletes then give the isolation the drop was being used for.
    """
    init_db()
    with SessionLocal() as db:
        db.query(Article).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(Article).delete()
        db.commit()


def _seed_article(s, slug, status, updated_at):
    a = Article(slug=slug, title=slug, content_md="x", status=status)
    s.add(a)
    s.flush()
    a.updated_at = updated_at
    s.add(a)


def test_submits_site_root_and_recent_published_articles(monkeypatch):
    monkeypatch.setattr(J.wordpress, "resolved_wp_url", lambda: "https://perkinsroofing.net")
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    s = SessionLocal()
    _seed_article(s, "fresh-post", "published", now - timedelta(hours=1))
    _seed_article(s, "stale-post", "published", now - timedelta(days=10))
    _seed_article(s, "unpublished-post", "draft", now)
    s.commit(); s.close()

    calls = []
    monkeypatch.setattr(J.search_indexing, "submit_urls", lambda urls: calls.append(urls) or {"ok": True})

    result = J.run(now=now)

    assert result == {"submitted": 2}
    assert len(calls) == 1
    urls = calls[0]
    assert urls[0] == "https://perkinsroofing.net/"
    assert "https://perkinsroofing.net/fresh-post/" in urls
    assert "https://perkinsroofing.net/stale-post/" not in urls
    assert "https://perkinsroofing.net/unpublished-post/" not in urls


def test_no_wp_url_configured_submits_nothing(monkeypatch):
    monkeypatch.setattr(J.wordpress, "resolved_wp_url", lambda: "")
    s = SessionLocal()
    _seed_article(s, "a", "published", datetime.now(timezone.utc).replace(tzinfo=None))
    s.commit(); s.close()

    calls = []
    monkeypatch.setattr(J.search_indexing, "submit_urls", lambda urls: calls.append(urls) or {})

    result = J.run()
    assert result == {"submitted": 0}
    assert calls == [[]]
