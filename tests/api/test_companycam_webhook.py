"""Security tests for the CompanyCam webhook (signature-verified, unauthenticated endpoint).

The webhook is authenticated ONLY by its signature, so these assert the auth boundary:
valid signature -> mirror + 200; bad signature -> 401; no secret -> 503; stale event -> 401.

The signing scheme here is CompanyCam's published one — base64(HMAC-SHA1(raw body)) keyed by
the webhook token — deliberately NOT re-derived from the implementation. The previous version
of this file signed with sha256-hexdigest and passed against a route that verified the same
way, which is why a scheme that would have 401'd every real event tested green.
"""
import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from app.models import CompanyCamPhoto, CompanyCamVideo, SessionLocal, init_db

SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def client():
    return TestClient(appmod.app)


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha1).digest()).decode()


def _event(event_type, payload, created_at=None):
    return {
        "event_type": event_type,
        "created_at": int(created_at if created_at is not None else time.time()),
        "webhook_id": 42,
        "payload": payload,
    }


def _photo_event(photo_id="p1", url="https://cc/x.jpg", created_at=None):
    return _event("photo.created", {
        "id": photo_id,
        "project_id": "proj1",
        "uris": [{"type": "original", "uri": url}],
        "captured_at": 1_700_000_000,
        "coordinates": {"lat": 26.1, "lon": -80.1},
        "tags": ["roof"],
    }, created_at)


def _post(client, body_dict, signature=None):
    body = json.dumps(body_dict).encode()
    return client.post("/companycam/webhook", content=body,
                       headers={"X-CompanyCam-Signature": signature or _sign(body)})


def test_valid_signature_mirrors_photo(client, monkeypatch):
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    r = _post(client, _photo_event())
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        row = db.query(CompanyCamPhoto).filter_by(companycam_photo_id="p1").one()
        assert row.url == "https://cc/x.jpg"
        assert row.tenant_id == 1


def test_video_event_mirrors_video(client, monkeypatch):
    """video.* is a separate v2 resource, not a photo with a flag — it must reach upsert_video."""
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    r = _post(client, _event("video.created", {
        "id": "v1", "project_id": "proj1", "playback_url": "https://cc/v.mp4",
        "thumbnail_urls": {"large": "https://cc/v.jpg"}, "internal": True,
    }))
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        row = db.query(CompanyCamVideo).filter_by(companycam_video_id="v1").one()
        assert row.url == "https://cc/v.mp4"
        assert row.internal is True


def test_sha256_hexdigest_signature_rejected(client, monkeypatch):
    """The scheme this route used to implement. It is not CompanyCam's, so it must not pass."""
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    body = json.dumps(_photo_event(photo_id="sha256-photo")).encode()
    wrong = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = client.post("/companycam/webhook", content=body,
                    headers={"X-CompanyCam-Signature": wrong})
    assert r.status_code == 401


def test_bad_signature_rejected_401(client, monkeypatch):
    # Distinct id so the assertion is robust to shared test-DB state (init_db is create_all,
    # it does not truncate between tests).
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    r = _post(client, _photo_event(photo_id="badsig-photo"), signature="deadbeef")
    assert r.status_code == 401
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        assert db.query(CompanyCamPhoto).filter_by(companycam_photo_id="badsig-photo").count() == 0


def test_unconfigured_secret_refuses_503(client, monkeypatch):
    monkeypatch.delenv("COMPANYCAM_WEBHOOK_SECRET", raising=False)
    r = _post(client, _photo_event(photo_id="unconfig-photo"))
    assert r.status_code == 503  # never accept an unverifiable body


def test_iso_created_at_from_modern_api_is_accepted(client, monkeypatch):
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    from datetime import datetime, timezone
    body = _photo_event(photo_id="iso-photo")
    body["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = _post(client, body)
    assert r.status_code == 200, r.text


def test_replayed_event_rejected_401(client, monkeypatch):
    """A captured request keeps its valid signature forever; the signed created_at is what
    expires. Signature is genuine here — only the age is wrong."""
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    stale = _photo_event(photo_id="replay-photo", created_at=time.time() - 3600)
    r = _post(client, stale)
    assert r.status_code == 401
    assert "replay" in r.json()["detail"]
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        assert db.query(CompanyCamPhoto).filter_by(companycam_photo_id="replay-photo").count() == 0


def test_missing_created_at_rejected_401(client, monkeypatch):
    """Dropping the field must not be a way to switch replay protection off."""
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    body = _photo_event(photo_id="nots-photo")
    del body["created_at"]
    assert _post(client, body).status_code == 401


def test_non_media_event_acked_without_write(client, monkeypatch):
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    r = _post(client, _event("project.created", {"id": "x"}))
    assert r.status_code == 200
    assert r.json()["ignored"] == "project.created"
