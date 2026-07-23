"""Behavioral tests for api/routes/portfolio.py.

Uses a fresh FastAPI app (not the real api.app) so the router is tested in isolation,
same pattern as tests/api/test_articles.py. adapters.wordpress is monkeypatched so no
network call ever leaves the test.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.portfolio import router
from scripts.portfolio_prefill import CANDIDATES


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
FIRST_SLUG = "fisher-island-7900-flat-roofs"


def test_list_requires_auth_role():
    """article_read is granted to sales too — sales can list."""
    c = _sales_client()
    r = c.get("/portfolio", headers=AUTH)
    assert r.status_code == 200, r.text
    assert len(r.json()) == len(CANDIDATES)


def test_list_includes_expected_fields(monkeypatch):
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: None)

    c = _admin_client()
    r = c.get("/portfolio", headers=AUTH)
    assert r.status_code == 200, r.text
    item = r.json()[0]
    for key in ("slug", "name", "city", "property_type", "roof_type",
                "permission_property", "permission_photos", "permission_video",
                "wp_post_id", "wp_status", "wp_admin_url"):
        assert key in item


def test_list_reports_existing_wp_draft(monkeypatch):
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: {"id": 8287, "status": "draft"})
    monkeypatch.setattr(wp, "resolved_wp_url", lambda: "https://staging.perkinsroofing.net")

    c = _admin_client()
    r = c.get("/portfolio", headers=AUTH)
    item = next(i for i in r.json() if i["slug"] == FIRST_SLUG)
    assert item["wp_post_id"] == 8287
    assert item["wp_status"] == "draft"
    assert item["wp_admin_url"] == "https://staging.perkinsroofing.net/wp-admin/post.php?post=8287&action=edit"


def test_publish_requires_manage_articles_role():
    c = _sales_client()
    r = c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 403, r.text


def test_publish_unknown_slug_404():
    c = _admin_client()
    r = c.post("/portfolio/does-not-exist/publish", headers=AUTH)
    assert r.status_code == 404, r.text


def test_publish_blocked_by_permission_gate():
    """No candidate has confirmed client permissions yet — publish must 422, and the
    detail must name the missing permissions."""
    c = _admin_client()
    r = c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "Permission to name property" in detail
    assert "Permission to use photos" in detail
    assert "Permission to use video" in detail


def test_publish_never_calls_wp_when_gate_fails(monkeypatch):
    """Server-side enforcement: the gate must short-circuit before any WP call."""
    import adapters.wordpress as wp
    called = []
    monkeypatch.setattr(wp, "publish_portfolio_post", lambda post, **kw: called.append(post))

    c = _admin_client()
    c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert called == []


def test_publish_succeeds_once_gate_is_open(monkeypatch):
    """Simulates a confirmed-permissions project by patching the module-level gate
    dict directly (there is no persistence for these yet — see route module docstring)."""
    import adapters.wordpress as wp
    import api.routes.portfolio as portfolio_routes

    monkeypatch.setitem(portfolio_routes._PERMISSION_GATE, "Permission to name property", True)
    monkeypatch.setitem(portfolio_routes._PERMISSION_GATE, "Permission to use photos", True)
    monkeypatch.setitem(portfolio_routes._PERMISSION_GATE, "Permission to use video", True)
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: None)
    monkeypatch.setattr(
        wp, "publish_portfolio_post",
        lambda post, **kw: {"title": post["title"], "status": "created", "post_id": 9001},
    )

    c = _admin_client()
    r = c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["publish_result"]["status"] == "created"
    assert data["publish_result"]["post_id"] == 9001


def test_publish_wp_error_returns_502(monkeypatch):
    import requests

    import adapters.wordpress as wp
    import api.routes.portfolio as portfolio_routes

    monkeypatch.setitem(portfolio_routes._PERMISSION_GATE, "Permission to name property", True)
    monkeypatch.setitem(portfolio_routes._PERMISSION_GATE, "Permission to use photos", True)
    monkeypatch.setitem(portfolio_routes._PERMISSION_GATE, "Permission to use video", True)

    def _boom(post, **kw):
        raise requests.HTTPError("500 server error")
    monkeypatch.setattr(wp, "publish_portfolio_post", _boom)

    c = _admin_client()
    r = c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 502, r.text
