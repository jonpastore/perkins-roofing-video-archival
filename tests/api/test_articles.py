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

def test_article_update_returns_publish_at_with_explicit_utc_marker():
    c = _admin_client()
    c.post("/articles", json={"title": "Scheduled Article TZ"}, headers=AUTH)

    r = c.put(
        "/articles/scheduled-article-tz",
        json={"status": "scheduled", "publish_at": "2026-07-15T13:00:00.000Z"},
        headers=AUTH,
    )

    assert r.status_code == 200, r.text
    assert r.json()["publish_at"] == "2026-07-15T13:00:00Z"


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


# ---------------------------------------------------------------------------
# XSS sanitization: stored content_md must survive bleach on write
# ---------------------------------------------------------------------------

_XSS_PAYLOADS = [
    '<script>alert("xss")</script>',
    '<img src=x onerror=alert(1)>',
    '<a href="javascript:alert(1)">click</a>',
    '<iframe src="javascript:alert(1)"></iframe>',
    '<div onmouseover="evil()">hover</div>',
]

_SAFE_HTML = (
    "<h2>Roof Repair Guide</h2>"
    "<p>Perkins Roofing serves <strong>Columbus, OH</strong>.</p>"
    "<ul><li>Shingles</li><li>Flashing</li></ul>"
    '<a href="https://example.com">Learn more</a>'
    '<iframe src="https://www.youtube.com/embed/abc123" allowfullscreen></iframe>'
)


def test_xss_script_stripped_on_create():
    """<script> payload in content_md must be stripped before storage."""
    c = _admin_client()
    payload = '<script>alert("xss")</script><p>Legit content</p>'
    r = c.post("/articles", json={"title": "XSS Create Test", "content_md": payload}, headers=AUTH)
    assert r.status_code == 201, r.text
    stored = r.json()["content_md"]
    assert "<script>" not in stored
    assert "alert" not in stored
    assert "Legit content" in stored


def test_xss_onerror_stripped_on_create():
    """onerror= event handler must be stripped on create."""
    c = _admin_client()
    payload = '<img src=x onerror=alert(1)><p>Text</p>'
    r = c.post("/articles", json={"title": "XSS Onerror Create", "content_md": payload}, headers=AUTH)
    assert r.status_code == 201, r.text
    stored = r.json()["content_md"]
    assert "onerror" not in stored


def test_xss_javascript_href_stripped_on_create():
    """javascript: href must be stripped on create."""
    c = _admin_client()
    payload = '<a href="javascript:alert(1)">click me</a>'
    r = c.post("/articles", json={"title": "XSS JS Href Create", "content_md": payload}, headers=AUTH)
    assert r.status_code == 201, r.text
    stored = r.json()["content_md"]
    assert "javascript:" not in stored


def test_xss_script_stripped_on_update():
    """<script> payload in content_md must be stripped on update."""
    c = _admin_client()
    c.post("/articles", json={"title": "XSS Update Test"}, headers=AUTH)
    payload = '<script>steal(document.cookie)</script><h2>Real Content</h2>'
    r = c.put("/articles/xss-update-test", json={"content_md": payload}, headers=AUTH)
    assert r.status_code == 200, r.text
    stored = r.json()["content_md"]
    assert "<script>" not in stored
    assert "steal" not in stored
    assert "<h2>" in stored


def test_xss_on_event_handler_stripped_on_update():
    """on* event handlers must be stripped on update."""
    c = _admin_client()
    c.post("/articles", json={"title": "XSS OnEvent Update"}, headers=AUTH)
    payload = '<div onmouseover="evil()">hover me</div><p>Safe</p>'
    r = c.put("/articles/xss-onevent-update", json={"content_md": payload}, headers=AUTH)
    assert r.status_code == 200, r.text
    stored = r.json()["content_md"]
    assert "onmouseover" not in stored
    assert "evil()" not in stored


def test_safe_html_survives_sanitization():
    """Legitimate article HTML (headings, lists, links, YouTube iframes) must not be stripped."""
    c = _admin_client()
    r = c.post("/articles", json={"title": "Safe HTML Survives", "content_md": _SAFE_HTML}, headers=AUTH)
    assert r.status_code == 201, r.text
    stored = r.json()["content_md"]
    assert "<h2>" in stored
    assert "<strong>" in stored
    assert "<ul>" in stored
    assert 'href="https://example.com"' in stored
    assert "<iframe" in stored
    assert "youtube.com" in stored


def test_sanitize_html_unit_script():
    """Unit test: sanitize_html strips <script> from raw content_md."""
    from jobs.article_job import sanitize_html
    result = sanitize_html('<script>alert("xss")</script><p>Clean</p>')
    assert "<script>" not in result
    assert "alert" not in result
    assert "Clean" in result


def test_sanitize_html_unit_onerror():
    """Unit test: sanitize_html strips onerror= event handler."""
    from jobs.article_job import sanitize_html
    result = sanitize_html('<img src=x onerror=alert(1)><p>Safe</p>')
    assert "onerror" not in result


def test_sanitize_html_unit_javascript_href():
    """Unit test: sanitize_html strips javascript: URI from href."""
    from jobs.article_job import sanitize_html
    result = sanitize_html('<a href="javascript:alert(1)">link</a>')
    assert "javascript:" not in result


def test_sanitize_html_unit_youtube_iframe_survives():
    """Unit test: sanitize_html preserves https YouTube iframes."""
    from jobs.article_job import sanitize_html
    iframe = '<iframe src="https://www.youtube.com/embed/abc123" allowfullscreen></iframe>'
    result = sanitize_html(iframe)
    assert "<iframe" in result
    assert "youtube.com" in result


# ---------------------------------------------------------------------------
# wp_url field
# ---------------------------------------------------------------------------

def test_get_article_wp_url_null_when_no_post_id():
    """GET /articles/{slug} returns wp_url=null when wp_post_id is not set."""
    c = _admin_client()
    c.post("/articles", json={"title": "No WP Post ID"}, headers=AUTH)
    r = c.get("/articles/no-wp-post-id", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "wp_url" in data
    assert data["wp_url"] is None


def test_get_article_wp_url_set_when_post_id_and_wp_url(monkeypatch):
    """GET /articles/{slug} returns full WP post URL when wp_post_id is set and WP_URL configured."""
    monkeypatch.setenv("WP_URL", "https://perkinsroofing.net")
    # Reload settings so WP_URL is picked up
    import app.config as cfg
    cfg.settings.WP_URL = "https://perkinsroofing.net"

    from app.models import Article, SessionLocal
    with SessionLocal() as db:
        a = db.get(Article, "wp-url-test-article")
        if a is None:
            a = Article(
                slug="wp-url-test-article",
                title="WP URL Test Article",
                meta="",
                content_md="content",
                faq_json=None,
                jsonld_json=None,
                role="standalone",
                pillar_slug=None,
                wp_post_id=42,
                status="published",
                publish_at=None,
            )
            db.add(a)
            db.commit()

    c = _admin_client()
    r = c.get("/articles/wp-url-test-article", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "wp_url" in data
    assert data["wp_url"] == "https://perkinsroofing.net/?p=42"


def test_list_articles_wp_url_field_present():
    """GET /articles list includes wp_url key in every summary item."""
    c = _admin_client()
    c.post("/articles", json={"title": "List WP URL Check"}, headers=AUTH)
    r = c.get("/articles", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) > 0
    for item in items:
        assert "wp_url" in item
