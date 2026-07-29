"""The portfolio publisher's create-vs-update behaviour.

This is the bug that made the whole curation feature inert: every candidate already had a
draft (created 2026-07-22), and publish_portfolio_post returned "skipped-exists" for an
existing title. So an editor could curate a gallery, press Publish, get a 200 — and the page
would never change.
"""
import pytest

import adapters.wordpress as wp

POST = {"title": "Miami Isola Roof", "content": "<p>new body</p>", "status": "draft",
        "category": "Commercial", "tags": ["Miami"], "skills": ["Tile"]}


class _Resp:
    def __init__(self, payload=None):
        self._payload = payload or {"id": 4242}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture()
def calls(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(wp, "_auth", lambda: ("u", "p"))
    monkeypatch.setattr(wp, "_wp_api_url", lambda path: f"https://wp.test{path}")
    monkeypatch.setattr(wp, "_get_or_create_portfolio_term", lambda tax, name: 7)
    monkeypatch.setattr(wp._session, "post",
                        lambda url, **kw: seen.append({"url": url, **kw}) or _Resp())
    return seen


def test_existing_post_is_skipped_by_default(calls, monkeypatch):
    """Default stays non-destructive — a bulk backfill must not overwrite live pages."""
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: {"id": 99, "status": "draft"})
    result = wp.publish_portfolio_post(POST)
    assert result["status"] == "skipped-exists"
    assert calls == [], "nothing may be written when skipping"


def test_update_existing_writes_to_the_existing_post_id(calls, monkeypatch):
    """The fix: curation has to reach the draft that already exists."""
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: {"id": 99, "status": "publish"})
    result = wp.publish_portfolio_post(POST, update_existing=True)

    assert result == {"title": POST["title"], "status": "updated", "post_id": 99}
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/avada_portfolio/99"), "must PATCH the existing post"
    assert calls[0]["json"]["content"] == "<p>new body</p>"


def test_an_update_never_changes_the_posts_status(calls, monkeypatch):
    """Re-publishing a curated gallery must not revert a live page to draft."""
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: {"id": 99, "status": "publish"})
    wp.publish_portfolio_post(POST, update_existing=True)
    assert "status" not in calls[0]["json"]


def test_a_new_post_is_still_created(calls, monkeypatch):
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: None)
    result = wp.publish_portfolio_post(POST, update_existing=True)
    assert result["status"] == "created"
    assert calls[0]["url"].endswith("/avada_portfolio")
    assert calls[0]["json"]["status"] == "draft"
