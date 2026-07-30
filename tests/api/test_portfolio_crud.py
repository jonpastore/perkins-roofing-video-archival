"""Project CRUD + the publish gate at the API boundary.

The gate tests are the important ones: they assert that publish REFUSES, because a gate that
only advises is not a gate. Privacy blockers must win over granted permissions.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from api.auth import set_verifier  # noqa: E402
from api.routes.portfolio import router  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    CompanyCamPhoto,
    KnowifyRawRecord,
    PortfolioCuration,
    PortfolioProject,
    SessionLocal,
    engine,
)

Base.metadata.create_all(engine)
AUTH = {"Authorization": "Bearer tok"}
CC_PROJECT = "60249175"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "list_portfolio_posts", lambda: [])
    monkeypatch.setattr(wp, "find_portfolio_post", lambda title: None)
    monkeypatch.setattr(wp, "list_location_page_slugs", lambda: [])
    with SessionLocal() as db:
        db.query(PortfolioProject).delete()
        db.query(PortfolioCuration).delete()
        db.query(CompanyCamPhoto).delete()
        db.query(KnowifyRawRecord).delete()
        db.commit()
    yield


def _client(role="admin"):
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role, "tenant_id": 1})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _create(c, **over):
    body = {"name": "Miami Beach Olsen Condo", "city": "Miami Beach", "section": "commercial",
            "companycam_url": f"https://app.companycam.com/projects/{CC_PROJECT}/photos",
            "search_terms": ["Olsen"]}
    body.update(over)
    return c.post("/portfolio", headers=AUTH, json=body)


# --- CRUD -----------------------------------------------------------------

def test_the_hardcoded_candidates_are_seeded_once():
    """The list used to BE code. First read migrates it, and a second read must not duplicate."""
    c = _client()
    first = c.get("/portfolio", headers=AUTH)
    assert first.status_code == 200
    assert len(first.json()) == 13
    assert len(c.get("/portfolio", headers=AUTH).json()) == 13


def test_create_read_update_archive_restore():
    c = _client()
    c.get("/portfolio", headers=AUTH)  # seed

    created = _create(c, name="Doral Warehouse Flat Re-Roof", city="Doral")
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]
    assert slug == "doral-warehouse-flat-re-roof"

    updated = c.put(f"/portfolio/{slug}", headers=AUTH, json={
        "name": "Doral Warehouse Flat Re-Roof", "city": "Doral Heights",
        "section": "commercial", "notes": "Two buildings.", "search_terms": ["Doral"],
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["city"] == "Doral Heights"

    assert c.delete(f"/portfolio/{slug}", headers=AUTH).json()["archived"] is True
    assert slug not in [p["slug"] for p in c.get("/portfolio", headers=AUTH).json()]

    assert c.post(f"/portfolio/{slug}/restore", headers=AUTH).status_code == 200
    assert slug in [p["slug"] for p in c.get("/portfolio", headers=AUTH).json()]


def test_a_duplicate_name_gets_its_own_slug():
    """The slug is the join key for curation, so a collision would graft one project's media
    onto another."""
    c = _client()
    c.get("/portfolio", headers=AUTH)
    first = _create(c, name="Tile Re-Roof")
    second = _create(c, name="Tile Re-Roof")
    assert first.json()["slug"] != second.json()["slug"]


def test_creating_a_project_with_an_address_is_refused():
    """PII is refused at the door, not just at publish — an address in the notes is a
    disclosure waiting for someone to press a button."""
    c = _client()
    c.get("/portfolio", headers=AUTH)
    r = _create(c, notes="Re-roof at 1424 Willow Rd, Miami Beach")
    assert r.status_code == 422
    assert any("street_address" in p for p in r.json()["detail"]["problems"])


def test_creating_a_project_named_after_a_person_is_refused():
    c = _client()
    c.get("/portfolio", headers=AUTH)
    r = _create(c, name="Melissa Butterworth", city="West Palm Beach")
    assert r.status_code == 422
    assert any("individual" in p for p in r.json()["detail"]["problems"])


def test_a_bad_url_is_refused():
    c = _client()
    c.get("/portfolio", headers=AUTH)
    r = _create(c, companycam_url="app.companycam.com/projects/1")
    assert r.status_code == 422


def test_crud_requires_the_manage_role():
    c = _client(role="sales")
    assert _create(c).status_code == 403
    assert c.delete("/portfolio/anything", headers=AUTH).status_code == 403


def test_editing_an_unknown_project_404s():
    c = _client()
    r = c.put("/portfolio/nope", headers=AUTH,
              json={"name": "X", "city": "Miami", "section": "commercial"})
    assert r.status_code == 404


# --- the gate -------------------------------------------------------------

def _curate(slug, alt="Olsen Condo roof view", n=4, video=False):
    """Give a project cleared permissions and a curated gallery."""
    with SessionLocal() as db:
        for i in range(n):
            db.add(CompanyCamPhoto(tenant_id=1, companycam_photo_id=f"ph{i}",
                                   project_id=CC_PROJECT, url=f"http://cdn/ph{i}.jpg",
                                   tags=[], raw={}, content_hash=f"h{i}"))
        db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).delete()
        db.add(PortfolioCuration(
            tenant_id=1, slug=slug, companycam_project_id=CC_PROJECT,
            permission_property=True, permission_photos=True, permission_video=video,
            selections=[{"kind": "photo", "id": f"ph{i}", "alt": f"{alt} {i}"} for i in range(n)],
        ))
        db.commit()


def test_the_media_view_carries_the_gate():
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug)
    body = c.get(f"/portfolio/{slug}/media", headers=AUTH).json()
    assert "gate" in body
    assert {"publishable", "blockers", "failing", "criteria"} <= set(body["gate"])


def test_publish_is_refused_without_client_permission():
    c = _client()
    c.get("/portfolio", headers=AUTH)
    r = c.post("/portfolio/miami-beach-olsen-condo/publish", headers=AUTH)
    assert r.status_code == 422
    keys = [b["key"] for b in r.json()["detail"]["blockers"]]
    assert "permission_property" in keys


def test_publish_is_refused_when_alt_text_hides_an_address(monkeypatch):
    """The prose is clean; the alt text names a street. A body-only check would publish it."""
    import adapters.wordpress as wp
    called = []
    monkeypatch.setattr(wp, "publish_portfolio_post", lambda post, **kw: called.append(post))

    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug, alt="Roof at 1424 Willow Rd")
    r = c.post(f"/portfolio/{slug}/publish", headers=AUTH)
    assert r.status_code == 422
    assert "no_pii" in [b["key"] for b in r.json()["detail"]["blockers"]]
    assert called == [], "WordPress must never be called when the gate refuses"


def test_publish_is_refused_for_a_person_named_project_even_with_permissions():
    """Privacy outranks permission: a cleared client cannot consent to us naming an individual
    in a page title."""
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "jim-malooly-delray-beach-roof"
    _curate(slug, alt="Delray Beach roof view")
    r = c.post(f"/portfolio/{slug}/publish", headers=AUTH)
    assert r.status_code == 422
    assert "title_not_a_person" in [b["key"] for b in r.json()["detail"]["blockers"]]


def _seed_scope():
    """Knowify project -> contract -> deliverables, the real join the scope lookup walks."""
    with SessionLocal() as db:
        db.add(KnowifyRawRecord(tenant_id=1, entity="projects", knowify_id="P1", is_present=True,
                                content_hash="a",
                                payload={"Id": "P1", "ClientId": "C1",
                                         "ProjectName": "Olsen Tile Re-Roof"}))
        db.add(KnowifyRawRecord(tenant_id=1, entity="contracts", knowify_id="K1", is_present=True,
                                content_hash="b", payload={"Id": "K1", "ProjectId": "P1"}))
        for i, desc in enumerate([
            '13" Concrete Tile Re-Roof', "Sika RoofPro System", "Terrace Deck Demo",
            "Stainless Steel Scupper Drains", "Polyglass 2-Ply Built-Up Roofing System",
        ]):
            db.add(KnowifyRawRecord(tenant_id=1, entity="deliverables", knowify_id=f"D{i}",
                                    is_present=True, content_hash=f"c{i}",
                                    payload={"ContractId": "K1", "Description": desc}))
        db.commit()


def test_the_contract_scope_reaches_the_page():
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug)
    _seed_scope()
    body = c.get(f"/portfolio/{slug}/media", headers=AUTH).json()
    assert '13" Concrete Tile Re-Roof' in body["scope_lines"]
    assert "Sika RoofPro System" in body["preview_html"]


def _mock_sanitize(monkeypatch):
    """Stand in for the CompanyCam-stamp crop + WP upload (network). Returns a WP-hosted url,
    which is what the images_sanitized blocker requires — see core/photo_privacy."""
    import adapters.wordpress as wp
    monkeypatch.setattr(wp, "sanitize_photo_to_media", lambda url, kind, mid: {
        "id": 4242, "source_url": f"https://wp.test/wp-content/uploads/perkins-{kind}-{mid}.jpg"})


def test_publish_succeeds_and_reports_the_gate(monkeypatch):
    import adapters.wordpress as wp
    _mock_sanitize(monkeypatch)
    monkeypatch.setattr(wp, "publish_portfolio_post",
                        lambda post, **kw: {"title": post["title"], "status": "updated",
                                            "post_id": 8296, "jsonld_stored": True})
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug)
    _seed_scope()
    r = c.post(f"/portfolio/{slug}/publish", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["publish_result"]["status"] == "updated"
    assert r.json()["gate"]["publishable"] is True


# --- the sanitizer must not deadlock the UI -------------------------------

def test_saving_a_selection_records_the_sanitized_url_so_the_preview_can_go_green(monkeypatch):
    """web/src/pages/Portfolio.tsx disables Publish on !gate.publishable. The gate runs on the
    curation PREVIEW too, so if sanitizing happened only at publish time, media_sanitized would
    be permanently red and Publish permanently disabled — the feature unreachable."""
    _mock_sanitize(monkeypatch)
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug)  # seeds the CompanyCam photos this selection refers to

    r = c.put(f"/portfolio/{slug}/curation", headers=AUTH, json={
        "permission_property": True, "permission_photos": True, "permission_video": False,
        "selections": [{"kind": "photo", "id": f"ph{i}", "alt": f"roof view {i}"}
                       for i in range(4)],
    })
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        saved = db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).one().selections
    assert all(s.get("wp_url", "").find("/wp-content/uploads/") > 0 for s in saved), saved

    gate = c.get(f"/portfolio/{slug}/media", headers=AUTH).json()["gate"]
    keys = [b["key"] for b in gate["blockers"]]
    assert "media_sanitized" not in keys, gate["blockers"]


def test_an_unsanitized_saved_selection_still_blocks_the_preview():
    """The mirror image of the test above: _curate writes raw CDN urls with no wp_url, which is
    what a selection saved before the sanitizer existed looks like. It must stay refused."""
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug)
    gate = c.get(f"/portfolio/{slug}/media", headers=AUTH).json()["gate"]
    assert "media_sanitized" in [b["key"] for b in gate["blockers"]]


def test_a_saved_wp_url_cannot_resurrect_media_whose_permission_was_revoked():
    """_apply_sanitized_urls overlays the saved WP copy onto the media map. That map is built by
    _available_media, which is permission-filtered — so the overlay can only ever touch media
    that is still permitted. A stale selection cannot drag a revoked photo back onto the page."""
    from api.routes.portfolio import _apply_sanitized_urls

    media = {"photo:1": {"url": "https://img.companycam.com/a"}}  # only permitted media present
    selections = [
        {"kind": "photo", "id": "1", "wp_url": "https://wp/wp-content/uploads/ok.jpg"},
        {"kind": "photo", "id": "99", "wp_url": "https://wp/wp-content/uploads/revoked.jpg"},
    ]
    _apply_sanitized_urls(selections, media)
    assert media["photo:1"]["url"] == "https://wp/wp-content/uploads/ok.jpg"
    assert "photo:99" not in media


def test_a_partial_sanitize_failure_blocks_the_whole_page(monkeypatch):
    """If one photo sanitizes and another does not, the page must still refuse. The failing
    photo keeps its CompanyCam url, which media_sanitized then catches — a partial success must
    never publish a gallery where one image still carries the capture stamp."""
    import adapters.wordpress as wp

    def flaky(url, kind, mid):
        if mid == "ph2":
            raise RuntimeError("CDN 500")
        return {"id": 1, "source_url": f"https://wp.test/wp-content/uploads/{mid}.jpg"}

    monkeypatch.setattr(wp, "sanitize_photo_to_media", flaky)
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    _curate(slug)
    r = c.put(f"/portfolio/{slug}/curation", headers=AUTH, json={
        "permission_property": True, "permission_photos": True, "permission_video": False,
        "selections": [{"kind": "photo", "id": f"ph{i}", "alt": f"roof view {i}"}
                       for i in range(4)],
    })
    assert r.status_code == 200, r.text
    gate = c.get(f"/portfolio/{slug}/media", headers=AUTH).json()["gate"]
    assert "media_sanitized" in [b["key"] for b in gate["blockers"]]
    assert gate["publishable"] is False


# --- gate failures are persisted, not just returned -----------------------

def test_publish_records_why_it_was_refused(monkeypatch):
    """Before 0051 the verdict existed only in the 422 body. Once that response was gone,
    neither a human nor a correction loop could answer "why is this one not published?"."""
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    assert c.post(f"/portfolio/{slug}/publish", headers=AUTH).status_code == 422

    with SessionLocal() as db:
        row = db.query(PortfolioProject).filter(PortfolioProject.slug == slug).one()
        keys = [f["key"] for f in (row.gate_failures or [])]
    assert "permission_property" in keys
    assert all("severity" in f and "label" in f for f in row.gate_failures), row.gate_failures


def test_never_gated_is_distinguishable_from_gated_and_clean():
    """NULL means nobody has checked; [] means checked and nothing failed. Code that conflates
    them reports unchecked projects as passing."""
    c = _client()
    projects = c.get("/portfolio", headers=AUTH).json()
    fresh = next(p for p in projects if p["slug"] == "miami-isola-roof")
    assert fresh["gate_failures"] is None
    assert fresh["gate_checked_at"] is None


def test_the_recorded_reason_is_exposed_to_the_list_view(monkeypatch):
    """The editor's list has to show it — that is the "a human can see and correct it" half."""
    c = _client()
    c.get("/portfolio", headers=AUTH)
    slug = "miami-beach-olsen-condo"
    c.post(f"/portfolio/{slug}/publish", headers=AUTH)
    listed = {p["slug"]: p for p in c.get("/portfolio", headers=AUTH).json()}[slug]
    assert listed["gate_checked_at"] is not None
    assert "permission_property" in [f["key"] for f in listed["gate_failures"]]
