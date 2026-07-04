"""Hermetic tests for api/routes/archive.py.

Uses a temp SQLite DB (set via DB_URL env before importing app.models) and a fake
token verifier (set via api.auth.set_verifier) — no real Firebase or GCS needed.
"""
import os
import sys
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# --- set up temp DB before any app.models import ---
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from api.auth import set_verifier  # noqa: E402
from api.routes.archive import router  # noqa: E402
from app.models import Base, SessionLocal, Video, engine  # noqa: E402

Base.metadata.create_all(engine)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VIDEO_ARCHIVED = "vid_archived"
VIDEO_PENDING = "vid_pending"


@pytest.fixture(autouse=True)
def seed_db():
    """Wipe videos and insert two known rows before each test."""
    with SessionLocal() as db:
        db.query(Video).delete()
        db.add(Video(
            id=VIDEO_ARCHIVED,
            title="Roof Repair 101",
            duration=300.0,
            upload_date="2024-03-15",
            url="https://youtube.com/watch?v=abc",
            archive_uri="gs://test-project-media/videos/vid_archived.mp4",
        ))
        db.add(Video(
            id=VIDEO_PENDING,
            title="Gutters Explained",
            duration=180.0,
            upload_date="2024-02-10",
            url="https://youtube.com/watch?v=def",
            archive_uri=None,
        ))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(Video).delete()
        db.commit()


def _make_client(role: str | None) -> TestClient:
    """Build a TestClient with a fake verifier for the given role (or no-token for None)."""
    if role is not None:
        set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    else:
        set_verifier(lambda token: (_ for _ in ()).throw(ValueError("no token")))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# GET /archive/videos
# ---------------------------------------------------------------------------

def test_list_videos_401_no_token():
    client = _make_client("admin")
    resp = client.get("/archive/videos")
    assert resp.status_code == 401


def test_list_videos_200_admin():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ids = {v["id"] for v in data}
    assert VIDEO_ARCHIVED in ids
    assert VIDEO_PENDING in ids


def test_list_videos_200_sales():
    client = _make_client("sales")
    resp = client.get("/archive/videos", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_videos_archived_flag():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers={"Authorization": "Bearer tok"})
    data = {v["id"]: v for v in resp.json()}
    assert data[VIDEO_ARCHIVED]["archived"] is True
    assert data[VIDEO_PENDING]["archived"] is False


def test_list_videos_archived_only():
    client = _make_client("admin")
    resp = client.get(
        "/archive/videos?archived_only=true",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == VIDEO_ARCHIVED


def test_list_videos_title_search():
    client = _make_client("admin")
    resp = client.get(
        "/archive/videos?q=roof",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == VIDEO_ARCHIVED


def test_list_videos_ordered_by_upload_date_desc():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers={"Authorization": "Bearer tok"})
    dates = [v["upload_date"] for v in resp.json()]
    assert dates == sorted(dates, reverse=True)


def test_list_videos_youtube_url_present():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers={"Authorization": "Bearer tok"})
    data = {v["id"]: v for v in resp.json()}
    assert data[VIDEO_ARCHIVED]["youtube_url"] == "https://youtube.com/watch?v=abc"


# ---------------------------------------------------------------------------
# GET /archive/{video_id}/download
# ---------------------------------------------------------------------------

def test_download_archived_returns_url(monkeypatch):
    import adapters.storage as storage  # noqa: PLC0415 — ensure importable
    monkeypatch.setattr(
        "adapters.storage.signed_download_url",
        lambda bucket, key, *, filename, ttl_seconds=3600: f"https://storage.example.com/{key}?sig=fake",
    )
    client = _make_client("admin")
    resp = client.get(
        f"/archive/{VIDEO_ARCHIVED}/download",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "download_url" in data
    assert "vid_archived.mp4" in data["download_url"]


def test_download_pending_returns_404():
    client = _make_client("admin")
    resp = client.get(
        f"/archive/{VIDEO_PENDING}/download",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 404


def test_download_unknown_video_returns_404():
    client = _make_client("admin")
    resp = client.get(
        "/archive/nonexistent_id/download",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 404


def test_download_401_no_token():
    client = _make_client("admin")
    resp = client.get(f"/archive/{VIDEO_ARCHIVED}/download")
    assert resp.status_code == 401


def test_download_sales_role(monkeypatch):
    monkeypatch.setattr(
        "adapters.storage.signed_download_url",
        lambda bucket, key, *, filename, ttl_seconds=3600: f"https://storage.example.com/{key}?sig=fake",
    )
    client = _make_client("sales")
    resp = client.get(
        f"/archive/{VIDEO_ARCHIVED}/download",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
