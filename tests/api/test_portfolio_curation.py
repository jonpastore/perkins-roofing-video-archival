"""Hermetic tests for the portfolio curation routes.

The boundary that matters: media is filtered by client permission on the way OUT, and a
selection is validated against those same permissions on the way IN — so an editor cannot
save a selection the page would then be legally unable to publish.
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
    CompanyCamVideo,
    PortfolioCuration,
    SessionLocal,
    engine,
)

Base.metadata.create_all(engine)

# Fisher Island 7900 — the first CANDIDATE, whose companycam_url carries project 60249175.
SLUG = "fisher-island-7900-flat-roofs"
CC_PROJECT = "60249175"


@pytest.fixture(autouse=True)
def seed():
    with SessionLocal() as db:
        db.query(CompanyCamPhoto).delete()
        db.query(CompanyCamVideo).delete()
        db.query(PortfolioCuration).delete()
        for i in range(4):
            db.add(CompanyCamPhoto(tenant_id=1, companycam_photo_id=f"ph{i}",
                                   project_id=CC_PROJECT, url=f"http://cdn/ph{i}.jpg",
                                   tags=[], raw={}, content_hash=f"h{i}"))
        db.add(CompanyCamVideo(tenant_id=1, companycam_video_id="vid_ok", project_id=CC_PROJECT,
                               url="http://cdn/v.m3u8", internal=False, raw={}, content_hash="hv"))
        db.add(CompanyCamVideo(tenant_id=1, companycam_video_id="vid_internal",
                               project_id=CC_PROJECT, url="http://cdn/vi.m3u8",
                               internal=True, raw={}, content_hash="hvi"))
        db.commit()
    yield


def _client(role="admin"):
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role, "tenant_id": 1})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _auth():
    return {"Authorization": "Bearer x"}


def test_media_is_hidden_until_permission_is_recorded():
    r = _client().get(f"/portfolio/{SLUG}/media", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["companycam_project_id"] == CC_PROJECT
    assert body["available"] == {"photos": [], "videos": []}, "no permission => no media"


def test_permission_reveals_photos_but_never_internal_video():
    c = _client()
    r = c.put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": True,
        "selections": [],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["available"]["photos"]) == 4
    ids = [v["companycam_video_id"] for v in body["available"]["videos"]]
    assert ids == ["vid_ok"], "internal video must never be offered for curation"


def test_saving_a_selection_round_trips_and_scores():
    c = _client()
    sel = [{"kind": "photo", "id": f"ph{i}", "alt": f"Fisher Island roof view {i}"}
           for i in range(4)]
    r = c.put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": False,
        "selections": sel,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["selections"]) == 4
    checks = {ch["key"]: ch["pass"] for ch in body["score"]["checks"]}
    assert checks["gallery_size"] is True
    assert checks["alt_unique"] is True
    assert body["score"]["blocking"] == [], "photos cleared + no video selected => publishable"


def test_duplicate_alt_text_is_rejected_with_the_reason():
    c = _client()
    sel = [{"kind": "photo", "id": f"ph{i}", "alt": "Perkins Roofing project"} for i in range(2)]
    r = c.put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": False,
        "selections": sel,
    })
    assert r.status_code == 422
    assert any("reused across images" in p for p in r.json()["detail"]["problems"])


def test_selecting_media_the_permissions_do_not_cover_is_rejected():
    """Photos cleared, video NOT — selecting the video must 422, not silently save."""
    c = _client()
    r = c.put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": False,
        "selections": [{"kind": "video", "id": "vid_ok"}],
    })
    assert r.status_code == 422
    assert any("not available" in p for p in r.json()["detail"]["problems"])


def test_internal_video_cannot_be_selected_even_with_video_permission():
    c = _client()
    r = c.put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": True,
        "selections": [{"kind": "video", "id": "vid_internal"}],
    })
    assert r.status_code == 422


def test_curation_requires_the_manage_role():
    r = _client(role="sales").put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": True,
        "selections": [],
    })
    assert r.status_code == 403


def test_unknown_slug_404s():
    r = _client().get("/portfolio/not-a-project/media", headers=_auth())
    assert r.status_code == 404
