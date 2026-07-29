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


def test_publish_succeeds_and_reports_the_gate(monkeypatch):
    import adapters.wordpress as wp
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
