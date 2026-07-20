"""Behavioral tests for POST /clips/{clip_id}/preflight — per-platform spec check."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.clips import router

AUTH = {"Authorization": "Bearer tok"}

_CONFORMING = {
    "duration_seconds": 30, "width": 1080, "height": 1920,
    "size_mb": 50, "codec_video": "h264", "codec_audio": "aac",
}


def _client(role="admin"):
    set_verifier(lambda token: {"uid": "u1", "email": f"{role}@x.com", "role": role, "email_verified": True})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_preflight_conforming_passes():
    r = _client().post("/clips/c1/preflight", headers=AUTH,
                       json={"platforms": ["instagram", "tiktok"], "meta": _CONFORMING})
    assert r.status_code == 200
    results = r.json()["results"]
    assert results["instagram"]["ok"] is True
    assert results["tiktok"]["ok"] is True


def test_preflight_overlong_fails_instagram():
    meta = {**_CONFORMING, "duration_seconds": 120}
    r = _client().post("/clips/c1/preflight", headers=AUTH,
                       json={"platforms": ["instagram"], "meta": meta})
    assert r.status_code == 200
    ig = r.json()["results"]["instagram"]
    assert ig["ok"] is False
    assert any("duration" in f for f in ig["failures"])


def test_preflight_empty_platforms_422():
    r = _client().post("/clips/c1/preflight", headers=AUTH, json={"platforms": [], "meta": _CONFORMING})
    assert r.status_code == 422
