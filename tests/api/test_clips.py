"""Hermetic tests for api/routes/clips.py.

Uses a temp SQLite DB (set via DB_URL env before importing app.models) and a
fake token verifier (api.auth.set_verifier) — no live Firebase or LLM needed.

Coverage:
  POST /clips/suggest  — role gating, LLM path, fallback path, no-transcript 404
  POST /clips/save     — upsert (insert + update), role gating
  GET  /clips/renderable — lists approved unrendered series, role gating
  Unit — _source_video_path archive vs yt-dlp selection
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Isolate to a fresh SQLite DB before any app.models import
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from api.routes.clips import router  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    GraphNode,
    MiniSeries,
    Segment,
    SessionLocal,
    SocialPost,
    Video,
    engine,
)

Base.metadata.create_all(engine)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_HDR = {"Authorization": "Bearer tok"}


def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "admin@test.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all relevant tables between tests."""
    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(MiniSeries).delete()
        db.query(GraphNode).delete()
        db.query(Segment).delete()
        db.query(Video).delete()
        db.commit()
    yield


@pytest.fixture()
def seeded_video():
    """Insert a Video + Segments + GraphNodes; return the video_id."""
    video_id = "vid_clip_test"
    with SessionLocal() as db:
        db.add(Video(
            id=video_id,
            title="How to Fix a Leaky Roof",
            duration=120.0,
            archive_uri="gs://test-bucket/media/vid_clip_test.mp4",
        ))
        # Segments grounding the timestamps
        db.add(Segment(video_id=video_id, text="Welcome, today we cover roof leaks.", start=0.0, end=10.0, source="youtube_caption"))
        db.add(Segment(video_id=video_id, text="The most common cause is flashing failure.", start=10.0, end=35.0, source="youtube_caption"))
        db.add(Segment(video_id=video_id, text="Here is how you fix it step by step.", start=35.0, end=60.0, source="youtube_caption"))
        db.add(Segment(video_id=video_id, text="Call us for a free inspection today.", start=60.0, end=80.0, source="youtube_caption"))
        # GraphNodes for fallback path
        db.add(GraphNode(video_id=video_id, kind="topics", label="Flashing Failure", start=10.0, version="v1"))
        db.add(GraphNode(video_id=video_id, kind="ctas", label="Free Inspection", start=60.0, version="v1"))
        db.commit()
    return video_id


# ---------------------------------------------------------------------------
# POST /clips/suggest — role gating
# ---------------------------------------------------------------------------

def test_suggest_403_sales(seeded_video):
    client = _make_client("sales")
    resp = client.post("/clips/suggest", json={"video_id": seeded_video}, headers=ADMIN_HDR)
    assert resp.status_code == 403


def test_suggest_401_no_token(seeded_video):
    client = _make_client("admin")
    resp = client.post("/clips/suggest", json={"video_id": seeded_video})
    assert resp.status_code == 401


def test_suggest_200_admin(seeded_video, monkeypatch):
    """Admin gets suggestions grounded in the seeded transcript timestamps."""
    fake_clips = {
        "clips": [
            {"start": 10.0, "end": 35.0, "title": "Flashing Fix", "caption": "#roof", "hook": "Did you know?", "reason": "High info density"},
            {"start": 60.0, "end": 80.0, "title": "Free Inspection", "caption": "#roofer", "hook": "Call now!", "reason": "Strong CTA"},
            {"start": 35.0, "end": 60.0, "title": "Step by Step", "caption": "#DIY", "hook": "Watch this", "reason": "Actionable"},
            {"start": 0.0, "end": 10.0, "title": "Intro Hook", "caption": "#leak", "hook": "Leaky roof?", "reason": "Hook"},
        ]
    }
    monkeypatch.setattr("app.llm.chat", lambda prompt, want_json=False, timeout=300: fake_clips)

    client = _make_client("admin")
    resp = client.post("/clips/suggest", json={"video_id": seeded_video, "count": 4}, headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()

    assert data["video_id"] == seeded_video
    assert data["video_title"] == "How to Fix a Leaky Roof"
    assert len(data["suggestions"]) == 4

    # All required fields present
    for s in data["suggestions"]:
        assert "start" in s
        assert "end" in s
        assert "title" in s
        assert "caption" in s
        assert "hook" in s
        assert "reason" in s

    # Timestamps are grounded in real segments (not invented)
    starts = {s["start"] for s in data["suggestions"]}
    assert starts.issubset({0.0, 10.0, 35.0, 60.0})


def test_suggest_200_web_admin(seeded_video, monkeypatch):
    """web_admin role also has approve_video permission."""
    monkeypatch.setattr("app.llm.chat", lambda prompt, want_json=False, timeout=300: {"clips": [
        {"start": 10.0, "end": 35.0, "title": "T", "caption": "C", "hook": "H", "reason": "R"},
        {"start": 60.0, "end": 80.0, "title": "T2", "caption": "C2", "hook": "H2", "reason": "R2"},
        {"start": 35.0, "end": 60.0, "title": "T3", "caption": "C3", "hook": "H3", "reason": "R3"},
        {"start": 0.0, "end": 10.0, "title": "T4", "caption": "C4", "hook": "H4", "reason": "R4"},
    ]})
    client = _make_client("web_admin")
    resp = client.post("/clips/suggest", json={"video_id": seeded_video}, headers=ADMIN_HDR)
    assert resp.status_code == 200


def test_suggest_404_no_video():
    client = _make_client("admin")
    resp = client.post("/clips/suggest", json={"video_id": "nonexistent"}, headers=ADMIN_HDR)
    assert resp.status_code == 404


def test_suggest_404_no_transcript():
    """Video exists but has no segments -> 404."""
    with SessionLocal() as db:
        db.add(Video(id="vid_notranscript", title="Empty", duration=60.0))
        db.commit()

    client = _make_client("admin")
    resp = client.post("/clips/suggest", json={"video_id": "vid_notranscript"}, headers=ADMIN_HDR)
    assert resp.status_code == 404
    assert "transcript" in resp.json()["detail"].lower()


def test_suggest_fallback_on_llm_failure(seeded_video, monkeypatch):
    """When LLM raises, fallback to propose_parts — still returns clip-shaped dicts."""
    def _bad_chat(prompt, want_json=False, timeout=300):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("app.llm.chat", _bad_chat)

    client = _make_client("admin")
    resp = client.post("/clips/suggest", json={"video_id": seeded_video, "count": 4}, headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["suggestions"]) >= 1
    for s in data["suggestions"]:
        assert "start" in s and "end" in s and "title" in s


def test_suggest_fallback_on_empty_llm_response(seeded_video, monkeypatch):
    """When LLM returns empty/malformed JSON, fallback to propose_parts."""
    monkeypatch.setattr("app.llm.chat", lambda prompt, want_json=False, timeout=300: {})

    client = _make_client("admin")
    resp = client.post("/clips/suggest", json={"video_id": seeded_video, "count": 4}, headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["suggestions"]) >= 1


# ---------------------------------------------------------------------------
# POST /clips/save — role gating + upsert
# ---------------------------------------------------------------------------

def test_save_403_sales(seeded_video):
    client = _make_client("sales")
    resp = client.post("/clips/save", json={
        "video_id": seeded_video,
        "title": "My Clips",
        "parts": [{"title": "Part 1", "start": 10.0, "end": 35.0}],
    }, headers=ADMIN_HDR)
    assert resp.status_code == 403


def test_save_401_no_token(seeded_video):
    client = _make_client("admin")
    resp = client.post("/clips/save", json={
        "video_id": seeded_video,
        "title": "My Clips",
        "parts": [{"title": "Part 1", "start": 10.0, "end": 35.0}],
    })
    assert resp.status_code == 401


def test_save_inserts_approved_miniseries(seeded_video):
    client = _make_client("admin")
    resp = client.post("/clips/save", json={
        "video_id": seeded_video,
        "title": "Roof Leak Clips",
        "parts": [
            {"title": "Flashing Fix", "start": 10.0, "end": 35.0},
            {"title": "Free Inspection CTA", "start": 60.0, "end": 80.0},
        ],
    }, headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_id"] == seeded_video
    assert data["title"] == "Roof Leak Clips"
    assert data["approved"] == 1
    assert len(data["parts"]) == 2
    assert data["parts"][0]["title"] == "Flashing Fix"
    assert data["id"] is not None

    # Verify DB row
    with SessionLocal() as db:
        row = db.get(MiniSeries, data["id"])
        assert row is not None
        assert row.approved == 1
        assert len(row.parts_json) == 2


def test_save_upserts_existing_series(seeded_video):
    """Second save for the same video_id updates the existing MiniSeries row."""
    client = _make_client("admin")
    # First save
    r1 = client.post("/clips/save", json={
        "video_id": seeded_video,
        "title": "Original",
        "parts": [{"title": "Part 1", "start": 0.0, "end": 30.0}],
    }, headers=ADMIN_HDR)
    assert r1.status_code == 200
    series_id = r1.json()["id"]

    # Second save — should update, not create a new row
    r2 = client.post("/clips/save", json={
        "video_id": seeded_video,
        "title": "Updated",
        "parts": [
            {"title": "New Part A", "start": 10.0, "end": 35.0},
            {"title": "New Part B", "start": 60.0, "end": 80.0},
        ],
    }, headers=ADMIN_HDR)
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["id"] == series_id  # same row
    assert data2["title"] == "Updated"
    assert len(data2["parts"]) == 2

    # Only one MiniSeries row in DB
    with SessionLocal() as db:
        count = db.query(MiniSeries).filter(MiniSeries.video_id == seeded_video).count()
        assert count == 1


def test_save_404_unknown_video():
    client = _make_client("admin")
    resp = client.post("/clips/save", json={
        "video_id": "does_not_exist",
        "title": "X",
        "parts": [{"title": "P", "start": 0.0, "end": 30.0}],
    }, headers=ADMIN_HDR)
    assert resp.status_code == 404


def test_save_422_empty_parts(seeded_video):
    client = _make_client("admin")
    resp = client.post("/clips/save", json={
        "video_id": seeded_video,
        "title": "Empty",
        "parts": [],
    }, headers=ADMIN_HDR)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /clips/renderable — role gating + filtering
# ---------------------------------------------------------------------------

def test_renderable_403_sales():
    client = _make_client("sales")
    resp = client.get("/clips/renderable", headers=ADMIN_HDR)
    assert resp.status_code == 403


def test_renderable_401_no_token():
    client = _make_client("admin")
    resp = client.get("/clips/renderable")
    assert resp.status_code == 401


def test_renderable_lists_approved_unrendered(seeded_video):
    """An approved MiniSeries with no SocialPost must appear in renderable."""
    with SessionLocal() as db:
        db.add(MiniSeries(
            video_id=seeded_video,
            title="Clip Series",
            parts_json=[{"title": "P", "start": 10.0, "end": 35.0}],
            approved=1,
        ))
        db.commit()

    client = _make_client("admin")
    resp = client.get("/clips/renderable", headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["video_id"] == seeded_video
    assert data[0]["approved"] == 1
    assert data[0]["parts_count"] == 1


def test_renderable_excludes_unapproved(seeded_video):
    """Pending (approved=0) MiniSeries must NOT appear."""
    with SessionLocal() as db:
        db.add(MiniSeries(
            video_id=seeded_video,
            title="Pending",
            parts_json=[{"title": "P", "start": 0.0, "end": 30.0}],
            approved=0,
        ))
        db.commit()

    client = _make_client("admin")
    resp = client.get("/clips/renderable", headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert resp.json() == []


def test_renderable_excludes_already_rendered(seeded_video):
    """A series with a SocialPost (gcs_url set) must NOT appear."""
    with SessionLocal() as db:
        ms = MiniSeries(
            video_id=seeded_video,
            title="Done",
            parts_json=[{"title": "P", "start": 0.0, "end": 30.0}],
            approved=1,
        )
        db.add(ms)
        db.flush()
        db.add(SocialPost(
            series_id=ms.id,
            part=0,
            platform="instagram",
            gcs_url="gs://bucket/reel.mp4",
            status="rendered",
        ))
        db.commit()

    client = _make_client("admin")
    resp = client.get("/clips/renderable", headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert resp.json() == []


def test_renderable_empty_when_none():
    client = _make_client("admin")
    resp = client.get("/clips/renderable", headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Unit — _source_video_path: archive vs yt-dlp selection
# ---------------------------------------------------------------------------

def test_source_video_path_uses_archive(tmp_path, monkeypatch):
    """When archive_uri is set, source path is downloaded from GCS (not yt-dlp)."""
    from jobs.render_job import _source_video_path  # noqa: PLC0415

    archive_uri = "gs://test-bucket/media/vid123.mp4"
    fake_local = str(tmp_path / "vid123_archived.mp4")

    # Write a fake MP4 so the file exists after "download"
    def _fake_open_read_stream(bucket, key):
        import io
        assert bucket == "test-bucket"
        assert key == "media/vid123.mp4"
        return io.BytesIO(b"fake-mp4-content")

    yt_dlp_called = []

    def _fake_pull_video(video_id, dst):
        yt_dlp_called.append(video_id)
        return dst + "/fallback.mp4"

    monkeypatch.setattr("adapters.storage.open_read_stream", _fake_open_read_stream)
    monkeypatch.setattr("adapters.yt_dlp.pull_video", _fake_pull_video)

    result = _source_video_path("vid123", archive_uri, str(tmp_path))

    assert result == str(tmp_path / "vid123_archived.mp4")
    assert os.path.exists(result)
    assert open(result, "rb").read() == b"fake-mp4-content"
    assert yt_dlp_called == [], "yt-dlp must NOT be called when archive_uri is present"


def test_source_video_path_falls_back_to_ytdlp_when_no_archive(tmp_path, monkeypatch):
    """When archive_uri is None, yt-dlp is called."""
    from jobs.render_job import _source_video_path  # noqa: PLC0415

    yt_dlp_called = []

    def _fake_pull_video(video_id, dst):
        yt_dlp_called.append(video_id)
        # Create a fake file so the path is real
        path = os.path.join(dst, f"{video_id}.mp4")
        open(path, "wb").write(b"yt-dlp-content")
        return path

    monkeypatch.setattr("adapters.yt_dlp.pull_video", _fake_pull_video)

    result = _source_video_path("vid_ytdlp", None, str(tmp_path))

    assert yt_dlp_called == ["vid_ytdlp"]
    assert result.endswith(".mp4")


def test_source_video_path_falls_back_to_ytdlp_on_gcs_error(tmp_path, monkeypatch):
    """When archive_uri is set but GCS download fails, yt-dlp is used as fallback."""
    from jobs.render_job import _source_video_path  # noqa: PLC0415

    def _bad_open_read_stream(bucket, key):
        raise RuntimeError("GCS connection refused")

    yt_dlp_called = []

    def _fake_pull_video(video_id, dst):
        yt_dlp_called.append(video_id)
        path = os.path.join(dst, f"{video_id}.mp4")
        open(path, "wb").write(b"yt-dlp-fallback")
        return path

    monkeypatch.setattr("adapters.storage.open_read_stream", _bad_open_read_stream)
    monkeypatch.setattr("adapters.yt_dlp.pull_video", _fake_pull_video)

    result = _source_video_path("vid_gcs_fail", "gs://bucket/media/vid_gcs_fail.mp4", str(tmp_path))

    assert yt_dlp_called == ["vid_gcs_fail"]
    assert result.endswith(".mp4")


# ---------------------------------------------------------------------------
# Unit — _brand_scene_config: bucket/key validation (SSRF/LFI guards)
# ---------------------------------------------------------------------------

def test_brand_scene_config_rejects_foreign_bucket(tmp_path, monkeypatch):
    """_brand_scene_config must return None for a gs:// URI pointing at a foreign bucket."""
    import io
    from app.models import PlatformConfig, SessionLocal  # noqa: PLC0415

    # Seed platform_config to enable brand scenes with a foreign-bucket URI.
    with SessionLocal() as db:
        db.merge(PlatformConfig(key="REEL_APPLY_BRAND_SCENES", value="true"))
        db.merge(PlatformConfig(key="REEL_TITLE_IMG", value="gs://evil-bucket/brand/title.png"))
        db.merge(PlatformConfig(key="REEL_CLOSING_IMG", value=""))
        db.commit()

    # Monkeypatch _reels_bucket so it returns a known allowed bucket.
    monkeypatch.setattr("jobs.render_job._GOOGLE_CLOUD_PROJECT", "myproject")

    open_read_called = []

    def _spy_stream(bucket, key):
        open_read_called.append(bucket)
        return io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    monkeypatch.setattr("adapters.storage.open_read_stream", _spy_stream)

    from jobs.render_job import _brand_scene_config  # noqa: PLC0415

    title_path, closing_path = _brand_scene_config(str(tmp_path))

    assert title_path is None, "Foreign bucket URI must be rejected"
    assert closing_path is None
    assert open_read_called == [], "open_read_stream must NOT be called for a foreign bucket"


def test_brand_scene_config_rejects_key_outside_brand_prefix(tmp_path, monkeypatch):
    """_brand_scene_config must return None for a gs:// key that doesn't start with brand/."""
    import io
    from app.models import PlatformConfig, SessionLocal  # noqa: PLC0415

    monkeypatch.setattr("jobs.render_job._GOOGLE_CLOUD_PROJECT", "myproject")
    allowed_bucket = "myproject-reels"

    with SessionLocal() as db:
        db.merge(PlatformConfig(key="REEL_APPLY_BRAND_SCENES", value="true"))
        # Key is in the right bucket but wrong prefix (path traversal attempt).
        db.merge(PlatformConfig(key="REEL_TITLE_IMG",
                                value=f"gs://{allowed_bucket}/../../etc/passwd"))
        db.merge(PlatformConfig(key="REEL_CLOSING_IMG", value=""))
        db.commit()

    open_read_called = []

    def _spy_stream(bucket, key):
        open_read_called.append((bucket, key))
        return io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    monkeypatch.setattr("adapters.storage.open_read_stream", _spy_stream)

    from jobs.render_job import _brand_scene_config  # noqa: PLC0415

    title_path, closing_path = _brand_scene_config(str(tmp_path))

    assert title_path is None, "Key outside brand/ prefix must be rejected"
    assert open_read_called == [], "open_read_stream must NOT be called for keys outside brand/"


def test_brand_scene_config_rejects_local_path_by_default(tmp_path, monkeypatch):
    """_brand_scene_config must return None for a local path when ALLOW_LOCAL_BRAND_PATHS is off."""
    from app.models import PlatformConfig, SessionLocal  # noqa: PLC0415

    # Create a real file so the old code would have returned it.
    local_file = tmp_path / "title.png"
    local_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    monkeypatch.setattr("jobs.render_job._GOOGLE_CLOUD_PROJECT", "myproject")
    monkeypatch.delenv("ALLOW_LOCAL_BRAND_PATHS", raising=False)

    with SessionLocal() as db:
        db.merge(PlatformConfig(key="REEL_APPLY_BRAND_SCENES", value="true"))
        db.merge(PlatformConfig(key="REEL_TITLE_IMG", value=str(local_file)))
        db.merge(PlatformConfig(key="REEL_CLOSING_IMG", value=""))
        db.commit()

    from jobs.render_job import _brand_scene_config  # noqa: PLC0415

    title_path, closing_path = _brand_scene_config(str(tmp_path))

    assert title_path is None, "Arbitrary local path must be rejected when ALLOW_LOCAL_BRAND_PATHS is unset"


def test_brand_scene_config_accepts_valid_brand_uri(tmp_path, monkeypatch):
    """A valid gs://<reels_bucket>/brand/... URI downloads into scratch and returns the path."""
    import io
    from app.models import PlatformConfig, SessionLocal  # noqa: PLC0415

    monkeypatch.setattr("jobs.render_job._GOOGLE_CLOUD_PROJECT", "myproject")
    allowed_bucket = "myproject-reels"

    with SessionLocal() as db:
        db.merge(PlatformConfig(key="REEL_APPLY_BRAND_SCENES", value="true"))
        db.merge(PlatformConfig(key="REEL_TITLE_IMG",
                                value=f"gs://{allowed_bucket}/brand/title_scene.png"))
        db.merge(PlatformConfig(key="REEL_CLOSING_IMG", value=""))
        db.commit()

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

    def _fake_stream(bucket, key):
        assert bucket == allowed_bucket
        assert key == "brand/title_scene.png"
        return io.BytesIO(fake_png)

    monkeypatch.setattr("adapters.storage.open_read_stream", _fake_stream)

    from jobs.render_job import _brand_scene_config  # noqa: PLC0415

    title_path, closing_path = _brand_scene_config(str(tmp_path))

    assert title_path is not None, "Valid brand URI should be accepted"
    assert title_path.startswith(str(tmp_path)), "Downloaded file must live inside scratch"
    assert open(title_path, "rb").read() == fake_png
    assert closing_path is None
