"""Read surface for the CompanyCam mirror (#360).

The sync job has been writing companycam_photos/videos since 2026-07-28 with no reader of
its own. These cover what the reader must NOT do as much as what it must: leak internal
media, leak coordinates, or return the whole table.
"""
import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import CompanyCamPhoto, CompanyCamVideo, SessionLocal, init_db

AUTH = {"Authorization": "Bearer x"}


@pytest.fixture(autouse=True)
def _seed():
    init_db()
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        if db.query(CompanyCamPhoto).filter_by(companycam_photo_id="r1").count() == 0:
            db.add_all([
                CompanyCamPhoto(tenant_id=1, companycam_photo_id="r1", project_id="rp1",
                                url="https://cc/1.jpg", lat=26.7, lon=-80.05,
                                tags=["roof"], raw={}, content_hash="h1"),
                CompanyCamPhoto(tenant_id=1, companycam_photo_id="r2", project_id="rp2",
                                url="https://cc/2.jpg", raw={}, content_hash="h2"),
                CompanyCamVideo(tenant_id=1, companycam_video_id="rv1", project_id="rp1",
                                url="https://cc/1.mp4", internal=False, raw={},
                                content_hash="h3"),
                CompanyCamVideo(tenant_id=1, companycam_video_id="rv2", project_id="rp1",
                                url="https://cc/2.mp4", internal=True, raw={},
                                content_hash="h4"),
            ])
            db.commit()


@pytest.fixture()
def client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                            "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                            "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


def test_photos_filtered_by_project(client):
    r = client.get("/companycam/photos?project_id=rp1", headers=AUTH)
    assert r.status_code == 200, r.text
    assert [p["companycam_photo_id"] for p in r.json()] == ["r1"]


def test_photos_never_return_coordinates(client):
    """CompanyCam also burns these coordinates into the pixels; the DB columns are the half
    we can actually withhold, so this endpoint withholds them."""
    body = client.get("/companycam/photos?project_id=rp1", headers=AUTH).json()
    assert body and not ({"lat", "lon"} & set(body[0]))


def test_videos_hide_internal_by_default(client):
    ids = [v["companycam_video_id"]
           for v in client.get("/companycam/videos?project_id=rp1", headers=AUTH).json()]
    assert ids == ["rv1"], "internal media must never be returned unless asked for"


def test_videos_include_internal_when_asked(client):
    ids = {v["companycam_video_id"] for v in client.get(
        "/companycam/videos?project_id=rp1&include_internal=true", headers=AUTH).json()}
    assert ids == {"rv1", "rv2"}


def test_limit_is_bounded(client):
    assert client.get("/companycam/photos?limit=5000", headers=AUTH).status_code == 422
    assert client.get("/companycam/photos?limit=1", headers=AUTH).status_code == 200


def test_sales_can_read(sales_client):
    assert sales_client.get("/companycam/photos", headers=AUTH).status_code == 200


def test_unauthenticated_401(client):
    assert client.get("/companycam/photos").status_code == 401
