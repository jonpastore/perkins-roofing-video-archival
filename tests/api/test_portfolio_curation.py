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

from adapters.companycam import projects_tag_id, projects_video_tag_id  # noqa: E402
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
                                   tags=[projects_tag_id()], raw={}, content_hash=f"h{i}"))
        db.add(CompanyCamVideo(tenant_id=1, companycam_video_id="vid_ok", project_id=CC_PROJECT,
                               url="http://cdn/v.m3u8", internal=False, raw={},
                               tags=[projects_video_tag_id()], content_hash="hv"))
        db.add(CompanyCamVideo(tenant_id=1, companycam_video_id="vid_internal",
                               project_id=CC_PROJECT, url="http://cdn/vi.m3u8",
                               internal=True, raw={}, tags=[projects_video_tag_id()],
                               content_hash="hvi"))
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


def test_only_publish_tagged_media_is_offered_for_curation():
    """Building 77 mirrors 312 photos and 22 videos; 9 and 2 carry the publish tags. The
    gallery must offer the tagged subset — a crew's tear-off and damage frames are in the
    same project and were never meant to be public.

    Asserts against media that IS mirrored and IS permitted but is NOT tagged, which is the
    only thing that would change if the tag filter were dropped."""
    from app.models import CompanyCamPhoto, CompanyCamVideo, SessionLocal

    with SessionLocal() as db:
        db.add(CompanyCamPhoto(tenant_id=1, companycam_photo_id="untagged_ph",
                               project_id=CC_PROJECT, url="http://cdn/teardown.jpg",
                               tags=[], raw={}, content_hash="h_untagged"))
        db.add(CompanyCamPhoto(tenant_id=1, companycam_photo_id="other_tag_ph",
                               project_id=CC_PROJECT, url="http://cdn/other.jpg",
                               tags=["99999"], raw={}, content_hash="h_other"))
        db.add(CompanyCamVideo(tenant_id=1, companycam_video_id="untagged_vid",
                               project_id=CC_PROJECT, url="http://cdn/raw.m3u8",
                               internal=False, tags=[], raw={}, content_hash="hv_untagged"))
        db.commit()

    c = _client()
    body = c.put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": True,
        "selections": [],
    }).json()

    photo_ids = [p["companycam_photo_id"] for p in body["available"]["photos"]]
    assert "untagged_ph" not in photo_ids, "an untagged photo must never be offered"
    assert "other_tag_ph" not in photo_ids, "a DIFFERENT tag must not open the gallery"
    assert len(photo_ids) == 4, photo_ids

    video_ids = [v["companycam_video_id"] for v in body["available"]["videos"]]
    assert "untagged_vid" not in video_ids
    assert video_ids == ["vid_ok"]


def test_the_gallery_reads_newest_first():
    """Wendy wants the gallery to read finished roof -> job start, so captured_at DESC."""
    from datetime import datetime

    from app.models import CompanyCamPhoto, SessionLocal

    with SessionLocal() as db:
        db.query(CompanyCamPhoto).delete()
        for i, day in enumerate((3, 1, 2)):  # deliberately out of order
            db.add(CompanyCamPhoto(
                tenant_id=1, companycam_photo_id=f"ord{day}", project_id=CC_PROJECT,
                url=f"http://cdn/ord{day}.jpg", tags=[projects_tag_id()], raw={},
                captured_at=datetime(2026, 8, day), content_hash=f"ho{i}"))
        db.commit()

    body = _client().put(f"/portfolio/{SLUG}/curation", headers=_auth(), json={
        "permission_property": True, "permission_photos": True, "permission_video": False,
        "selections": [],
    }).json()

    assert [p["companycam_photo_id"] for p in body["available"]["photos"]] == \
        ["ord3", "ord2", "ord1"]


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
