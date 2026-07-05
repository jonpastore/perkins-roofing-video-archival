"""Behavioral tests for api/routes/articles.py.

Uses a fresh FastAPI app (not the real api.app) so the router is tested in isolation
without coupling to the full app's middleware. The conftest.py sets DB_URL to a temp
SQLite file before any import, so SessionLocal() is already isolated.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.articles import router
from app.models import init_db


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(_make_app())


def _sales_client():
    set_verifier(lambda token: {"uid": "u2", "email": "sales@x.com", "role": "sales"})
    return TestClient(_make_app())


AUTH = {"Authorization": "Bearer tok"}


def setup_module(module):
    init_db()


# ---------------------------------------------------------------------------
# Admin happy path: create -> get -> list -> update -> delete
# ---------------------------------------------------------------------------

def test_admin_create_article():
    c = _admin_client()
    r = c.post("/articles", json={"title": "My First Article"}, headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["slug"] == "my-first-article"
    assert data["title"] == "My First Article"
    assert data["status"] == "draft"
    assert data["role"] == "standalone"


def test_admin_get_article():
    c = _admin_client()
    # create first
    c.post("/articles", json={"title": "Get Test"}, headers=AUTH)
    r = c.get("/articles/get-test", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["slug"] == "get-test"
    assert "content_md" in data
    assert "faq_json" in data


def test_admin_list_articles():
    c = _admin_client()
    c.post("/articles", json={"title": "List Alpha"}, headers=AUTH)
    c.post("/articles", json={"title": "List Beta"}, headers=AUTH)
    r = c.get("/articles", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    slugs = [i["slug"] for i in items]
    assert "list-alpha" in slugs
    assert "list-beta" in slugs
    # summary only — no content_md in list
    for item in items:
        assert "content_md" not in item


def test_admin_update_article():
    c = _admin_client()
    c.post("/articles", json={"title": "Update Me"}, headers=AUTH)
    r = c.put("/articles/update-me",
              json={"title": "Updated Title", "status": "published"},
              headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["title"] == "Updated Title"
    assert data["status"] == "published"


def test_admin_delete_article():
    c = _admin_client()
    c.post("/articles", json={"title": "Delete Me"}, headers=AUTH)
    r = c.delete("/articles/delete-me", headers=AUTH)
    assert r.status_code == 204, r.text
    # confirm gone
    r2 = c.get("/articles/delete-me", headers=AUTH)
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Sales role: read allowed, write forbidden
# ---------------------------------------------------------------------------

def test_sales_can_list_articles():
    # Ensure there's at least one article (admin creates it)
    admin = _admin_client()
    admin.post("/articles", json={"title": "Sales Read Test"}, headers=AUTH)

    c = _sales_client()
    r = c.get("/articles", headers=AUTH)
    assert r.status_code == 200, r.text


def test_sales_can_get_article():
    admin = _admin_client()
    admin.post("/articles", json={"title": "Sales Get Test"}, headers=AUTH)

    c = _sales_client()
    r = c.get("/articles/sales-get-test", headers=AUTH)
    assert r.status_code == 200, r.text


def test_sales_cannot_create():
    c = _sales_client()
    r = c.post("/articles", json={"title": "Forbidden"}, headers=AUTH)
    assert r.status_code == 403, r.text


def test_sales_cannot_update():
    admin = _admin_client()
    admin.post("/articles", json={"title": "Sales Update Forbidden"}, headers=AUTH)

    c = _sales_client()
    r = c.put("/articles/sales-update-forbidden", json={"title": "Nope"}, headers=AUTH)
    assert r.status_code == 403, r.text


def test_sales_cannot_delete():
    admin = _admin_client()
    admin.post("/articles", json={"title": "Sales Delete Forbidden"}, headers=AUTH)

    c = _sales_client()
    r = c.delete("/articles/sales-delete-forbidden", headers=AUTH)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_404_on_missing_slug():
    c = _admin_client()
    r = c.get("/articles/does-not-exist-xyz", headers=AUTH)
    assert r.status_code == 404, r.text


def test_404_on_update_missing():
    c = _admin_client()
    r = c.put("/articles/no-such-article", json={"title": "X"}, headers=AUTH)
    assert r.status_code == 404, r.text


def test_404_on_delete_missing():
    c = _admin_client()
    r = c.delete("/articles/no-such-article", headers=AUTH)
    assert r.status_code == 404, r.text


def test_409_on_duplicate_slug():
    c = _admin_client()
    c.post("/articles", json={"title": "Duplicate"}, headers=AUTH)
    r = c.post("/articles", json={"title": "Duplicate"}, headers=AUTH)
    assert r.status_code == 409, r.text


def test_explicit_slug_accepted():
    c = _admin_client()
    r = c.post("/articles",
               json={"title": "Some Title", "slug": "my-custom-slug"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "my-custom-slug"


def test_401_without_token():
    c = _admin_client()
    r = c.get("/articles")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# Publish endpoint
# ---------------------------------------------------------------------------

def test_publish_sets_status_and_publish_at():
    c = _admin_client()
    c.post("/articles", json={"title": "Publish Me"}, headers=AUTH)
    r = c.post("/articles/publish-me/publish", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "published"
    assert data["publish_at"] is not None


def test_publish_returns_full_article():
    c = _admin_client()
    c.post(
        "/articles",
        json={"title": "Full Publish", "content_md": "Hello **world**", "meta": "desc"},
        headers=AUTH,
    )
    r = c.post("/articles/full-publish/publish", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "content_md" in data
    assert "faq_json" in data
    assert data["slug"] == "full-publish"


def test_publish_404_on_missing():
    c = _admin_client()
    r = c.post("/articles/no-such-slug/publish", headers=AUTH)
    assert r.status_code == 404, r.text


def test_publish_requires_admin():
    admin = _admin_client()
    admin.post("/articles", json={"title": "Auth Publish Test"}, headers=AUTH)

    c = _sales_client()
    r = c.post("/articles/auth-publish-test/publish", headers=AUTH)
    assert r.status_code == 403, r.text


def test_publish_no_wp_creds_still_succeeds(monkeypatch):
    """When WP env vars are absent the endpoint sets status without external call."""
    monkeypatch.delenv("WP_URL", raising=False)
    monkeypatch.delenv("WP_USER", raising=False)
    monkeypatch.delenv("WP_APP_PWD", raising=False)

    c = _admin_client()
    c.post("/articles", json={"title": "No WP Creds"}, headers=AUTH)
    r = c.post("/articles/no-wp-creds/publish", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
