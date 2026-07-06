"""Tests for the new archive KPI filters, fields, and backfill/poll endpoints.

Hermetic: temp SQLite DB + fake token verifier. YouTube calls are monkeypatched.
"""
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# --- temp DB before any app.models import ---
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from api.auth import set_verifier  # noqa: E402
from api.routes.archive import router  # noqa: E402
from app.models import Base, SessionLocal, Video, MiniSeries, SocialPost, Article, engine  # noqa: E402

Base.metadata.create_all(engine)

AUTH = {"Authorization": "Bearer tok"}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VID_LONG = "vid_long"
VID_SHORT = "vid_short"
VID_CLIPS = "vid_clips"
VID_SOCIAL = "vid_social"
VID_ART = "vid_art"


@pytest.fixture(autouse=True)
def seed_db():
    """Insert varied test videos + related rows; wipe after each test."""
    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(MiniSeries).delete()
        db.query(Article).delete()
        db.query(Video).delete()

        db.add(Video(
            id=VID_LONG,
            title="Long Roof Video",
            duration=600.0,
            upload_date="2024-06-01",
            url="https://youtube.com/watch?v=long",
            archive_uri="gs://bucket/long.mp4",
            views=1000,
            likes=50,
            comment_count=10,
            last_comment_at=datetime(2024, 6, 10, 12, 0, 0),
            kpis_polled_at=datetime(2024, 6, 11, 0, 0, 0),
            last_pulled_at=datetime(2024, 6, 1, 0, 0, 0),
        ))
        db.add(Video(
            id=VID_SHORT,
            title="Short Tip",
            duration=45.0,
            upload_date="2024-05-01",
            url="https://youtube.com/watch?v=short",
            archive_uri=None,
        ))
        db.add(Video(
            id=VID_CLIPS,
            title="Clips Video",
            duration=300.0,
            upload_date="2024-04-01",
            url="https://youtube.com/watch?v=clips",
            archive_uri="gs://bucket/clips.mp4",
        ))
        db.add(Video(
            id=VID_SOCIAL,
            title="Social Video",
            duration=200.0,
            upload_date="2024-03-01",
            url="https://youtube.com/watch?v=social",
            archive_uri="gs://bucket/social.mp4",
        ))
        db.add(Video(
            id=VID_ART,
            title="Article Video",
            duration=400.0,
            upload_date="2024-02-01",
            url="https://youtube.com/watch?v=art",
            archive_uri="gs://bucket/art.mp4",
        ))

        # MiniSeries for VID_CLIPS
        db.add(MiniSeries(id=1, video_id=VID_CLIPS, title="Clips Series", parts_json=[]))

        # SocialPost for VID_SOCIAL (via MiniSeries)
        db.add(MiniSeries(id=2, video_id=VID_SOCIAL, title="Social Series", parts_json=[]))
        db.add(SocialPost(series_id=2, part=1, platform="instagram", status="published"))

        # Article referencing VID_ART
        db.add(Article(
            slug="art-article",
            title="Art Article",
            content_md=f"This article references {VID_ART} in the text.",
            status="published",
        ))

        db.commit()
    yield
    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(MiniSeries).delete()
        db.query(Article).delete()
        db.query(Video).delete()
        db.commit()


def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# New fields on GET /archive/videos
# ---------------------------------------------------------------------------

def test_list_videos_includes_kpi_fields():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers=AUTH)
    assert resp.status_code == 200
    data = {v["id"]: v for v in resp.json()}
    v = data[VID_LONG]
    assert v["views"] == 1000
    assert v["likes"] == 50
    assert v["comment_count"] == 10
    assert v["last_comment_at"] is not None
    assert v["kpis_polled_at"] is not None
    assert v["last_pulled_at"] is not None


def test_list_videos_includes_content_length():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers=AUTH)
    assert resp.status_code == 200
    data = {v["id"]: v for v in resp.json()}
    assert data[VID_LONG]["content_length"] == 600
    assert data[VID_SHORT]["content_length"] == 45


def test_list_videos_kpi_fields_null_when_unset():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers=AUTH)
    data = {v["id"]: v for v in resp.json()}
    v = data[VID_SHORT]
    assert v["views"] is None
    assert v["likes"] is None
    assert v["kpis_polled_at"] is None
    assert v["last_pulled_at"] is None


def test_list_videos_boolean_flags():
    client = _make_client("admin")
    resp = client.get("/archive/videos", headers=AUTH)
    data = {v["id"]: v for v in resp.json()}
    assert data[VID_CLIPS]["clips_generated"] is True
    assert data[VID_LONG]["clips_generated"] is False
    assert data[VID_SOCIAL]["social_generated"] is True
    assert data[VID_LONG]["social_generated"] is False
    assert data[VID_ART]["articles_generated"] is True
    assert data[VID_LONG]["articles_generated"] is False


# ---------------------------------------------------------------------------
# min_length / max_length filter
# ---------------------------------------------------------------------------

def test_filter_min_length():
    client = _make_client("admin")
    resp = client.get("/archive/videos?min_length=300", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_LONG in ids       # 600s
    assert VID_CLIPS in ids      # 300s
    assert VID_ART in ids        # 400s
    assert VID_SHORT not in ids  # 45s
    assert VID_SOCIAL not in ids # 200s


def test_filter_max_length():
    client = _make_client("admin")
    resp = client.get("/archive/videos?max_length=200", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_SHORT in ids      # 45s
    assert VID_SOCIAL in ids     # 200s
    assert VID_LONG not in ids   # 600s


def test_filter_min_max_length_combined():
    client = _make_client("admin")
    resp = client.get("/archive/videos?min_length=200&max_length=400", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_CLIPS in ids      # 300s
    assert VID_SOCIAL in ids     # 200s
    assert VID_ART in ids        # 400s
    assert VID_LONG not in ids   # 600s
    assert VID_SHORT not in ids  # 45s


# ---------------------------------------------------------------------------
# uploaded_after / uploaded_before filter
# ---------------------------------------------------------------------------

def test_filter_uploaded_after():
    client = _make_client("admin")
    resp = client.get("/archive/videos?uploaded_after=2024-05-01", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_LONG in ids       # 2024-06-01
    assert VID_SHORT in ids      # 2024-05-01
    assert VID_CLIPS not in ids  # 2024-04-01


def test_filter_uploaded_before():
    client = _make_client("admin")
    resp = client.get("/archive/videos?uploaded_before=2024-03-01", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_SOCIAL in ids     # 2024-03-01
    assert VID_ART in ids        # 2024-02-01
    assert VID_LONG not in ids   # 2024-06-01


# ---------------------------------------------------------------------------
# clips / articles / social boolean filters
# ---------------------------------------------------------------------------

def test_filter_clips_yes():
    client = _make_client("admin")
    resp = client.get("/archive/videos?clips=yes", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_CLIPS in ids
    assert VID_SOCIAL in ids  # also has MiniSeries
    assert VID_LONG not in ids


def test_filter_clips_no():
    client = _make_client("admin")
    resp = client.get("/archive/videos?clips=no", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_LONG in ids
    assert VID_CLIPS not in ids


def test_filter_articles_yes():
    client = _make_client("admin")
    resp = client.get("/archive/videos?articles=yes", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_ART in ids
    assert VID_LONG not in ids


def test_filter_articles_no():
    client = _make_client("admin")
    resp = client.get("/archive/videos?articles=no", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_LONG in ids
    assert VID_ART not in ids


def test_filter_social_yes():
    client = _make_client("admin")
    resp = client.get("/archive/videos?social=yes", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_SOCIAL in ids
    assert VID_LONG not in ids


def test_filter_social_no():
    client = _make_client("admin")
    resp = client.get("/archive/videos?social=no", headers=AUTH)
    assert resp.status_code == 200
    ids = {v["id"] for v in resp.json()}
    assert VID_LONG in ids
    assert VID_SOCIAL not in ids


# ---------------------------------------------------------------------------
# POST /archive/backfill
# ---------------------------------------------------------------------------

def test_backfill_inserts_missing(monkeypatch):
    """Backfill calls backfill_archive.run() and returns {added, checked}."""
    import jobs.backfill_archive as _job
    monkeypatch.setattr(_job, "run", lambda **kw: {"added": 3, "checked": 10, "failed_tabs": []})
    client = _make_client("admin")
    resp = client.post("/archive/backfill", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 3
    assert data["checked"] == 10


def test_backfill_403_sales_role():
    client = _make_client("sales")
    resp = client.post("/archive/backfill", headers=AUTH)
    assert resp.status_code == 403


def test_backfill_401_no_token():
    client = _make_client("admin")
    resp = client.post("/archive/backfill")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /archive/check-new
# ---------------------------------------------------------------------------

def test_check_new_returns_count(monkeypatch):
    import jobs.backfill_archive as _job
    monkeypatch.setattr(_job, "check_new", lambda **kw: {"new_count": 5, "last_pulled_at": "2024-06-01T00:00:00"})
    client = _make_client("admin")
    resp = client.get("/archive/check-new", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_count"] == 5
    assert data["last_pulled_at"] == "2024-06-01T00:00:00"


def test_check_new_403_sales():
    client = _make_client("sales")
    resp = client.get("/archive/check-new", headers=AUTH)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /archive/poll-kpis
# ---------------------------------------------------------------------------

def test_poll_kpis_no_body(monkeypatch):
    import jobs.poll_archive_kpis as _job
    calls = []
    monkeypatch.setattr(_job, "run", lambda limit=None: calls.append(limit) or {"polled": 2})
    client = _make_client("admin")
    resp = client.post("/archive/poll-kpis", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["polled"] == 2
    assert calls == [None]


def test_poll_kpis_with_limit(monkeypatch):
    import jobs.poll_archive_kpis as _job
    calls = []
    monkeypatch.setattr(_job, "run", lambda limit=None: calls.append(limit) or {"polled": 1})
    client = _make_client("admin")
    resp = client.post("/archive/poll-kpis", json={"limit": 10}, headers=AUTH)
    assert resp.status_code == 200
    assert calls == [10]


def test_poll_kpis_403_sales():
    client = _make_client("sales")
    resp = client.post("/archive/poll-kpis", headers=AUTH)
    assert resp.status_code == 403


def test_poll_kpis_401_no_token():
    client = _make_client("admin")
    resp = client.post("/archive/poll-kpis")
    assert resp.status_code == 401
