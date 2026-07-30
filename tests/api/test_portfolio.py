"""Behavioral tests for api/routes/portfolio.py.

Uses a fresh FastAPI app (not the real api.app) so the router is tested in isolation,
same pattern as tests/api/test_articles.py. adapters.wordpress is monkeypatched so no
network call ever leaves the test.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.portfolio import router
from app.models import (
    Base,
    CompanyCamPhoto,
    KnowifyRawRecord,
    PortfolioCuration,
    SessionLocal,
    engine,
)
from scripts.portfolio_prefill import CANDIDATES

# The routes read portfolio_curation (migration 0048) for permissions/curated media, so the
# table has to exist. create-but-never-drop: a drop_all teardown here would pull tables out
# from under modules that only DELETE rows (see the suite's isolation note).
Base.metadata.create_all(engine)


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


def _clear_permissions(slug=FIRST_SLUG):
    with SessionLocal() as db:
        db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).delete()
        db.commit()


CC_PROJECT = "60249175"


def _publishable(slug=FIRST_SLUG):
    """Cleared permissions + a real gallery + contract scope: everything the gate requires.

    The gate grades the PAGE, not just the permissions, so a bare permission grant no longer
    reaches WordPress — which is the point of it.
    """
    with SessionLocal() as db:
        db.query(CompanyCamPhoto).delete()
        db.query(KnowifyRawRecord).delete()
        for i in range(4):
            db.add(CompanyCamPhoto(tenant_id=1, companycam_photo_id=f"gp{i}",
                                   project_id=CC_PROJECT, url=f"http://cdn/gp{i}.jpg",
                                   tags=[], raw={}, content_hash=f"gh{i}"))
        db.add(KnowifyRawRecord(tenant_id=1, entity="projects", knowify_id="GP1",
                                is_present=True, content_hash="ga",
                                payload={"Id": "GP1", "ClientId": "GC1",
                                         "ProjectName": "7900 Flat Roofs"}))
        db.add(KnowifyRawRecord(tenant_id=1, entity="contracts", knowify_id="GK1",
                                is_present=True, content_hash="gb",
                                payload={"Id": "GK1", "ProjectId": "GP1"}))
        for i, desc in enumerate(["Polyglass 2-Ply Built-Up Roofing System",
                                  "Stockmeier Polyurethane Coating System",
                                  "Stainless Steel Scupper Drains"]):
            db.add(KnowifyRawRecord(tenant_id=1, entity="deliverables", knowify_id=f"GD{i}",
                                    is_present=True, content_hash=f"gc{i}",
                                    payload={"ContractId": "GK1", "Description": desc}))
        db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).delete()
        db.add(PortfolioCuration(
            tenant_id=1, slug=slug, companycam_project_id=CC_PROJECT,
            permission_property=True, permission_photos=True, permission_video=True,
            selections=[{"kind": "photo", "id": f"gp{i}", "alt": f"Fisher Island roof view {i}"}
                        for i in range(4)],
        ))
        db.commit()


def _grant_permissions(slug=FIRST_SLUG, **flags):
    """Record real client permissions — they persist in portfolio_curation (migration 0048)
    now, instead of the module-level constant these tests used to monkeypatch."""
    with SessionLocal() as db:
        db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).delete()
        db.add(PortfolioCuration(
            tenant_id=1, slug=slug,
            permission_property=flags.get("property", True),
            permission_photos=flags.get("photos", True),
            permission_video=flags.get("video", True),
            selections=[],
        ))
        db.commit()


def test_list_requires_auth_role(monkeypatch):
    """article_read is granted to sales too — sales can list. WP list mocked so the
    test never leaves the process (review LOW: it used to hit the real adapter)."""
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "list_portfolio_posts", lambda: [])
    c = _sales_client()
    r = c.get("/portfolio", headers=AUTH)
    assert r.status_code == 200, r.text
    assert len(r.json()) == len(CANDIDATES)


def test_list_includes_expected_fields(monkeypatch):
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "list_portfolio_posts", lambda: [])

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
    from core.portfolio import map_to_post
    from scripts.portfolio_prefill import CANDIDATES as _C
    first = next(c for c in _C if True)
    t = map_to_post({"name": first["name"], "city": first["city"], "section": first["section"]},
                    content_html="")["title"]
    monkeypatch.setattr(wp, "list_portfolio_posts",
                        lambda: [{"id": 8287, "status": "draft", "title": t}])
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
    """A project with no recorded permissions must 422, naming what is missing.

    Naming the property is ALWAYS required. Photo and video permission are demanded only when
    that medium is actually curated in — nothing is selected here, so a page that would ship no
    media must not wait on permissions no media needs. Both are covered below.
    """
    _clear_permissions()
    c = _admin_client()
    r = c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 422, r.text
    keys = [b["key"] for b in r.json()["detail"]["blockers"]]
    assert keys == ["permission_property"], keys


def test_publish_demands_video_permission_once_a_video_is_curated_in():
    """The moment a video is selected, its permission becomes a real gate."""
    with SessionLocal() as db:
        db.query(PortfolioCuration).filter(PortfolioCuration.slug == FIRST_SLUG).delete()
        db.add(PortfolioCuration(
            tenant_id=1, slug=FIRST_SLUG,
            permission_property=True, permission_photos=True, permission_video=False,
            selections=[{"kind": "video", "id": "v1"}],
        ))
        db.commit()

    r = _admin_client().post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 422, r.text
    assert "permission_video" in [b["key"] for b in r.json()["detail"]["blockers"]]
    _clear_permissions()


def test_publish_never_calls_wp_when_gate_fails(monkeypatch):
    """Server-side enforcement: the gate must short-circuit before any WP call."""
    import adapters.wordpress as wp
    called = []
    monkeypatch.setattr(wp, "publish_portfolio_post", lambda post, **kw: called.append(post))
    _clear_permissions()

    c = _admin_client()
    c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert called == []


def _mock_sanitize(monkeypatch):
    """Stand in for the CompanyCam-stamp crop + WP upload (network). Returns a WP-hosted url,
    which is what the images_sanitized blocker requires — see core/photo_privacy."""
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "sanitize_photo_to_media", lambda url, kind, mid: {
        "id": 4242, "source_url": f"https://wp.test/wp-content/uploads/perkins-{kind}-{mid}.jpg"})


def test_publish_succeeds_once_gate_is_open(monkeypatch):
    """A project that passes the whole gate — permissions, gallery and scope — publishes."""
    import adapters.wordpress as wp

    _publishable()
    _mock_sanitize(monkeypatch)
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

    _publishable()
    _mock_sanitize(monkeypatch)

    def _boom(post, **kw):
        raise requests.HTTPError("500 server error")
    monkeypatch.setattr(wp, "publish_portfolio_post", _boom)

    c = _admin_client()
    r = c.post(f"/portfolio/{FIRST_SLUG}/publish", headers=AUTH)
    assert r.status_code == 502, r.text
