"""Security tests for the CompanyCam webhook (HMAC-verified, unauthenticated endpoint).

The webhook is authenticated ONLY by its signature, so these assert the auth boundary:
valid signature -> mirror + 200; bad signature -> 401; no secret -> 503.
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from app.models import CompanyCamPhoto, SessionLocal, init_db

SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def client():
    return TestClient(appmod.app)


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _photo_event(photo_id="p1", url="https://cc/x.jpg"):
    return {
        "type": "photo.created",
        "payload": {
            "id": photo_id,
            "project_id": "proj1",
            "uris": [{"type": "original", "uri": url}],
            "captured_at": 1_700_000_000,
            "coordinates": {"lat": 26.1, "lon": -80.1},
            "tags": ["roof"],
        },
    }


def test_valid_signature_mirrors_photo(client, monkeypatch):
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    body = json.dumps(_photo_event()).encode()
    r = client.post("/companycam/webhook", content=body,
                    headers={"X-CompanyCam-Signature": _sign(body)})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        row = db.query(CompanyCamPhoto).filter_by(companycam_photo_id="p1").one()
        assert row.url == "https://cc/x.jpg"
        assert row.tenant_id == 1


def test_bad_signature_rejected_401(client, monkeypatch):
    # Distinct id so the assertion is robust to shared test-DB state (init_db is create_all,
    # it does not truncate between tests).
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    body = json.dumps(_photo_event(photo_id="badsig-photo")).encode()
    r = client.post("/companycam/webhook", content=body,
                    headers={"X-CompanyCam-Signature": "deadbeef"})
    assert r.status_code == 401
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        assert db.query(CompanyCamPhoto).filter_by(companycam_photo_id="badsig-photo").count() == 0


def test_unconfigured_secret_refuses_503(client, monkeypatch):
    monkeypatch.delenv("COMPANYCAM_WEBHOOK_SECRET", raising=False)
    body = json.dumps(_photo_event(photo_id="unconfig-photo")).encode()
    r = client.post("/companycam/webhook", content=body,
                    headers={"X-CompanyCam-Signature": _sign(body)})
    assert r.status_code == 503  # never accept an unverifiable body


def test_non_photo_event_acked_without_write(client, monkeypatch):
    monkeypatch.setenv("COMPANYCAM_WEBHOOK_SECRET", SECRET)
    body = json.dumps({"type": "project.created", "payload": {"id": "x"}}).encode()
    r = client.post("/companycam/webhook", content=body,
                    headers={"X-CompanyCam-Signature": _sign(body)})
    assert r.status_code == 200
    assert r.json()["ignored"] == "project.created"
