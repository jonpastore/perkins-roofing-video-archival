"""Tests for POST /clips/{id}/render and GET /clips/{id}/render-status.

Uses TestClient + set_verifier (no live Firebase). Monkeypatches the Cloud Run
API call and google.auth so no real GCP credentials are needed.

Coverage:
  POST /clips/{id}/render  — happy path calls Cloud Run with correct series id,
                             404 for missing/unapproved series, 403 for sales role.
  GET  /clips/{id}/render-status — counts SocialPost rows correctly,
                                   404 for missing/unapproved, 403 for sales.
  Unit — render_job.run() honours RENDER_SERIES_ID env var.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Isolate to a fresh SQLite DB before any app.models import.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from api.routes.clips import router  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    MiniSeries,
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
    """Wipe relevant tables between tests."""
    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(MiniSeries).delete()
        db.query(Video).delete()
        db.commit()
    yield


@pytest.fixture()
def approved_series():
    """Insert an approved MiniSeries with 2 parts; return its id."""
    with SessionLocal() as db:
        db.add(Video(id="vid_render_test", title="Roof Repair Tips", duration=120.0))
        ms = MiniSeries(
            video_id="vid_render_test",
            title="Roof Repair — Clips",
            parts_json=[
                {"title": "Part 1", "start": 0.0, "end": 30.0},
                {"title": "Part 2", "start": 30.0, "end": 60.0},
            ],
            approved=1,
        )
        db.add(ms)
        db.commit()
        db.refresh(ms)
        return ms.id


@pytest.fixture()
def unapproved_series():
    """Insert an unapproved MiniSeries; return its id."""
    with SessionLocal() as db:
        db.add(Video(id="vid_unapproved", title="Pending Video", duration=60.0))
        ms = MiniSeries(
            video_id="vid_unapproved",
            title="Pending Clips",
            parts_json=[{"title": "P", "start": 0.0, "end": 20.0}],
            approved=0,
        )
        db.add(ms)
        db.commit()
        db.refresh(ms)
        return ms.id


# ---------------------------------------------------------------------------
# POST /clips/{id}/render
# ---------------------------------------------------------------------------

def test_render_trigger_happy_path(approved_series, monkeypatch):
    """Admin POST triggers the Cloud Run job with the correct series_id and returns started."""
    captured = {}

    def _fake_bearer_token():
        return "fake-token"

    class _FakeResp:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {"name": "projects/p/locations/us-central1/jobs/render/executions/exec-1"}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = headers
        return _FakeResp()

    monkeypatch.setattr("api.routes.clips._cloud_run_bearer_token", _fake_bearer_token)
    monkeypatch.setattr("api.routes.clips._requests.post", _fake_post)

    client = _make_client("admin")
    resp = client.post(f"/clips/{approved_series}/render", headers=ADMIN_HDR)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "started"
    assert "exec-1" in data["execution"]

    # Verify the env override carried the correct series_id.
    env_overrides = captured["body"]["overrides"]["containerOverrides"][0]["env"]
    assert any(
        e["name"] == "RENDER_SERIES_ID" and e["value"] == str(approved_series)
        for e in env_overrides
    ), f"RENDER_SERIES_ID not set correctly: {env_overrides}"


def test_render_trigger_404_missing_series(monkeypatch):
    """POST on a non-existent series_id returns 404 without calling Cloud Run."""
    called = []

    def _fake_bearer_token():
        called.append(True)
        return "tok"

    monkeypatch.setattr("api.routes.clips._cloud_run_bearer_token", _fake_bearer_token)

    client = _make_client("admin")
    resp = client.post("/clips/99999/render", headers=ADMIN_HDR)
    assert resp.status_code == 404
    assert called == [], "Cloud Run must NOT be called for missing series"


def test_render_trigger_404_unapproved_series(unapproved_series, monkeypatch):
    """POST on an unapproved series returns 404."""
    called = []
    monkeypatch.setattr("api.routes.clips._cloud_run_bearer_token", lambda: called.append(True) or "tok")

    client = _make_client("admin")
    resp = client.post(f"/clips/{unapproved_series}/render", headers=ADMIN_HDR)
    assert resp.status_code == 404
    assert called == [], "Cloud Run must NOT be called for unapproved series"


def test_render_trigger_403_sales(approved_series):
    """Sales role is denied the render trigger."""
    client = _make_client("sales")
    resp = client.post(f"/clips/{approved_series}/render", headers=ADMIN_HDR)
    assert resp.status_code == 403


def test_render_trigger_502_on_cloud_run_error(approved_series, monkeypatch):
    """When the Cloud Run API returns a non-OK status, the route returns 502."""
    class _ErrorResp:
        ok = False
        status_code = 403
        text = "Permission denied"

    monkeypatch.setattr("api.routes.clips._cloud_run_bearer_token", lambda: "tok")
    monkeypatch.setattr("api.routes.clips._requests.post", lambda *a, **kw: _ErrorResp())

    client = _make_client("admin")
    resp = client.post(f"/clips/{approved_series}/render", headers=ADMIN_HDR)
    assert resp.status_code == 502


def test_render_trigger_503_on_network_error(approved_series, monkeypatch):
    """When the network call raises, the route returns 503 without leaking the traceback."""
    def _bad_post(*a, **kw):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr("api.routes.clips._cloud_run_bearer_token", lambda: "tok")
    monkeypatch.setattr("api.routes.clips._requests.post", _bad_post)

    client = _make_client("admin")
    resp = client.post(f"/clips/{approved_series}/render", headers=ADMIN_HDR)
    assert resp.status_code == 503
    # No traceback in the response body.
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# GET /clips/{id}/render-status
# ---------------------------------------------------------------------------

def test_render_status_unrendered(approved_series):
    """A freshly created series has 0 parts rendered."""
    client = _make_client("admin")
    resp = client.get(f"/clips/{approved_series}/render-status", headers=ADMIN_HDR)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["parts_total"] == 2
    assert data["parts_rendered"] == 0
    assert data["rendered"] is False


def test_render_status_partial(approved_series):
    """One rendered SocialPost makes parts_rendered=1, rendered=False."""
    with SessionLocal() as db:
        db.add(SocialPost(
            series_id=approved_series,
            part=0,
            platform="instagram",
            gcs_url="gs://bucket/reel_0.mp4",
            status="rendered",
        ))
        db.commit()

    client = _make_client("admin")
    resp = client.get(f"/clips/{approved_series}/render-status", headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["parts_total"] == 2
    assert data["parts_rendered"] == 1
    assert data["rendered"] is False


def test_render_status_fully_rendered(approved_series):
    """SocialPost rows for all parts → rendered=True."""
    with SessionLocal() as db:
        for part_idx in range(2):
            # Multiple platform rows for the same part — should count as 1 rendered part.
            for platform in ("instagram", "tiktok"):
                db.add(SocialPost(
                    series_id=approved_series,
                    part=part_idx,
                    platform=platform,
                    gcs_url=f"gs://bucket/reel_{part_idx}.mp4",
                    status="rendered",
                ))
        db.commit()

    client = _make_client("admin")
    resp = client.get(f"/clips/{approved_series}/render-status", headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert data["parts_total"] == 2
    assert data["parts_rendered"] == 2
    assert data["rendered"] is True


def test_render_status_404_missing():
    client = _make_client("admin")
    resp = client.get("/clips/99999/render-status", headers=ADMIN_HDR)
    assert resp.status_code == 404


def test_render_status_404_unapproved(unapproved_series):
    client = _make_client("admin")
    resp = client.get(f"/clips/{unapproved_series}/render-status", headers=ADMIN_HDR)
    assert resp.status_code == 404


def test_render_status_403_sales(approved_series):
    client = _make_client("sales")
    resp = client.get(f"/clips/{approved_series}/render-status", headers=ADMIN_HDR)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Unit — render_job.run() honours RENDER_SERIES_ID env var
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /clips/upload-brand-scene — size cap + magic-byte validation
# ---------------------------------------------------------------------------

def test_upload_brand_scene_rejects_oversized_file(monkeypatch):
    """Files larger than 10 MiB must be rejected with 413."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "myproject")

    client = _make_client("admin")
    # 10 MiB + 1 byte of valid-looking PNG header followed by padding
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024)
    import io
    resp = client.post(
        "/clips/upload-brand-scene?scene=title",
        files={"file": ("title.png", io.BytesIO(oversized), "image/png")},
        headers=ADMIN_HDR,
    )
    assert resp.status_code == 413, resp.text


def test_upload_brand_scene_rejects_non_image(monkeypatch):
    """Files whose magic bytes are not PNG/JPEG/WEBP must be rejected with 422."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "myproject")

    client = _make_client("admin")
    import io
    # An ELF binary header — definitely not an image.
    elf_header = b"\x7fELF" + b"\x00" * 64
    resp = client.post(
        "/clips/upload-brand-scene?scene=title",
        files={"file": ("evil.png", io.BytesIO(elf_header), "image/png")},
        headers=ADMIN_HDR,
    )
    assert resp.status_code == 422, resp.text
    assert "image" in resp.json()["detail"].lower()


def test_upload_brand_scene_rejects_non_image_sent_as_html(monkeypatch):
    """HTML file with image/png content-type must be rejected by magic-byte check."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "myproject")

    client = _make_client("admin")
    import io
    html_data = b"<html><body>not an image</body></html>" + b"\x00" * 32
    resp = client.post(
        "/clips/upload-brand-scene?scene=closing",
        files={"file": ("close.png", io.BytesIO(html_data), "image/png")},
        headers=ADMIN_HDR,
    )
    assert resp.status_code == 422, resp.text


def test_upload_brand_scene_accepts_valid_png(monkeypatch):
    """Valid PNG upload stores in brand/ with sniffed content_type and persists gs:// path."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "myproject")

    uploaded = {}

    class _FakeBlob:
        def upload_from_filename(self, path, content_type=None):
            import os
            uploaded["content_type"] = content_type
            uploaded["data"] = open(path, "rb").read()

    class _FakeBucket:
        def blob(self, key):
            uploaded["key"] = key
            return _FakeBlob()

    class _FakeClient:
        def bucket(self, name):
            uploaded["bucket"] = name
            return _FakeBucket()

    monkeypatch.setattr("google.cloud.storage.Client", lambda: _FakeClient())

    client = _make_client("admin")
    import io
    # Minimal valid PNG: header + IHDR chunk stub
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    resp = client.post(
        "/clips/upload-brand-scene?scene=title",
        files={"file": ("title.png", io.BytesIO(png_data), "image/png")},
        headers=ADMIN_HDR,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["key"] == "REEL_TITLE_IMG"
    assert data["gcs_path"].startswith("gs://myproject-reels/brand/")
    # Sniffed type must be used — not client header
    assert uploaded["content_type"] == "image/png"
    assert uploaded["key"] == "brand/title_scene.png"


def test_upload_brand_scene_sniffs_jpeg_regardless_of_client_header(monkeypatch):
    """A JPEG file sent with a wrong content-type header is sniffed correctly."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "myproject")

    uploaded = {}

    class _FakeBlob:
        def upload_from_filename(self, path, content_type=None):
            uploaded["content_type"] = content_type

    class _FakeBucket:
        def blob(self, key):
            uploaded["key"] = key
            return _FakeBlob()

    class _FakeClient:
        def bucket(self, name):
            return _FakeBucket()

    monkeypatch.setattr("google.cloud.storage.Client", lambda: _FakeClient())

    client = _make_client("admin")
    import io
    # JPEG magic bytes — client sends wrong content-type
    jpeg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 32

    resp = client.post(
        "/clips/upload-brand-scene?scene=closing",
        files={"file": ("close.jpg", io.BytesIO(jpeg_data), "application/octet-stream")},
        headers=ADMIN_HDR,
    )
    assert resp.status_code == 200, resp.text
    # Must use sniffed type, not client "application/octet-stream"
    assert uploaded["content_type"] == "image/jpeg"
    assert uploaded["key"] == "brand/closing_scene.jpg"


# ---------------------------------------------------------------------------
# Unit — render_job.run() honours RENDER_SERIES_ID env var
# ---------------------------------------------------------------------------

def test_render_job_honours_render_series_id(monkeypatch):
    """When RENDER_SERIES_ID is set, run() only processes that series."""
    # Build two approved series in the DB.
    with SessionLocal() as db:
        db.add(Video(id="vid_rj_a", title="A", duration=60.0))
        db.add(Video(id="vid_rj_b", title="B", duration=60.0))
        ms_a = MiniSeries(
            video_id="vid_rj_a",
            title="Series A",
            parts_json=[{"title": "P", "start": 0.0, "end": 20.0}],
            approved=1,
        )
        ms_b = MiniSeries(
            video_id="vid_rj_b",
            title="Series B",
            parts_json=[{"title": "P", "start": 0.0, "end": 20.0}],
            approved=1,
        )
        db.add(ms_a)
        db.add(ms_b)
        db.commit()
        db.refresh(ms_a)
        db.refresh(ms_b)
        target_id = ms_a.id

    # Set RENDER_SERIES_ID to target only ms_a.
    monkeypatch.setenv("RENDER_SERIES_ID", str(target_id))

    rendered_series_ids: list[int] = []

    def _fake_render_part(series_id, part_index, **kwargs):
        rendered_series_ids.append(series_id)
        return {"skipped": False, "series_id": series_id, "part_index": part_index,
                "gcs_url": "gs://b/k.mp4", "social_post_id": 1, "scheduled_content_id": 1}

    # Patch render_part inside the jobs.render_job module.
    import jobs.render_job as rj
    monkeypatch.setattr(rj, "render_part", _fake_render_part)

    result = rj.run()

    assert rendered_series_ids == [target_id], (
        f"Expected only series {target_id} to be rendered, got {rendered_series_ids}"
    )
    assert result["rendered"] == 1
    assert result["errored"] == 0
