"""Behavioral tests for jobs/search_indexing_job.py (jobs/ are coverage-omitted).

adapters.search_indexing.submit_urls is monkeypatched — real HTTP is validated
separately in tests/adapters/test_search_indexing.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

import jobs.search_indexing_job as J
from app.config import settings
from app.models import Article, Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _seed_article(s, slug, status, updated_at):
    a = Article(slug=slug, title=slug, content_md="x", status=status)
    s.add(a)
    s.flush()
    a.updated_at = updated_at
    s.add(a)


def test_submits_site_root_and_recent_published_articles(monkeypatch):
    monkeypatch.setattr(settings, "WP_URL", "https://perkinsroofing.net")
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
    monkeypatch.setattr(settings, "WP_URL", "")
    s = SessionLocal()
    _seed_article(s, "a", "published", datetime.now(timezone.utc).replace(tzinfo=None))
    s.commit(); s.close()

    calls = []
    monkeypatch.setattr(J.search_indexing, "submit_urls", lambda urls: calls.append(urls) or {})

    result = J.run()
    assert result == {"submitted": 0}
    assert calls == [[]]
