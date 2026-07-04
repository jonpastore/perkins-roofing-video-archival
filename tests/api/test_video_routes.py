"""Hermetic tests for api/routes/video.py.

Uses a temp SQLite DB (set via DB_URL env before importing app.models) and a fake
token verifier (set via api.auth.set_verifier) — no real Firebase or DB needed.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# --- set up temp DB before any app.models import ---
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from api.routes.video import router  # noqa: E402
from app.models import Base, MiniSeries, SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_db():
    """Wipe mini_series between tests."""
    with SessionLocal() as db:
        db.query(MiniSeries).delete()
        db.commit()
    yield


@pytest.fixture()
def seeded_series():
    """Insert one pending MiniSeries and return its id."""
    with SessionLocal() as db:
        s = MiniSeries(
            video_id="vid_abc",
            title="Roof Repair Tips",
            parts_json=[
                {"title": "Intro", "start": 0.0, "end": 30.0},
                {"title": "Materials", "start": 30.0, "end": 90.0},
            ],
            approved=0,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id


def _make_client(role: str | None) -> TestClient:
    """Build a TestClient with a fake verifier for the given role."""
    if role is not None:
        set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    else:
        set_verifier(lambda token: (_ for _ in ()).throw(ValueError("no token")))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# GET /video/proposals — role gating
# ---------------------------------------------------------------------------

def test_proposals_401_no_token():
    client = _make_client("admin")
    resp = client.get("/video/proposals")
    assert resp.status_code == 401


def test_proposals_403_sales():
    client = _make_client("sales")
    resp = client.get("/video/proposals", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 403


def test_proposals_200_admin(seeded_series):
    client = _make_client("admin")
    resp = client.get("/video/proposals", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == seeded_series
    assert data[0]["approved"] == 0


def test_proposals_excludes_approved(seeded_series):
    """Already-approved series must not appear in proposals."""
    with SessionLocal() as db:
        s = db.get(MiniSeries, seeded_series)
        s.approved = 1
        db.commit()
    client = _make_client("admin")
    resp = client.get("/video/proposals", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /video/{series_id}
# ---------------------------------------------------------------------------

def test_get_series_200(seeded_series):
    client = _make_client("admin")
    resp = client.get(f"/video/{seeded_series}", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_id"] == "vid_abc"
    assert data["title"] == "Roof Repair Tips"
    assert len(data["parts"]) == 2


def test_get_series_404():
    client = _make_client("admin")
    resp = client.get("/video/99999", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 404


def test_get_series_403_sales(seeded_series):
    client = _make_client("sales")
    resp = client.get(f"/video/{seeded_series}", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /video/{series_id}/approve
# ---------------------------------------------------------------------------

def test_approve_sets_approved(seeded_series):
    client = _make_client("admin")
    resp = client.post(
        f"/video/{seeded_series}/approve",
        json={},
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] == 1
    # parts unchanged when not provided
    assert len(data["parts"]) == 2


def test_approve_updates_parts(seeded_series):
    new_parts = [
        {"title": "New Intro", "start": 0.0, "end": 20.0},
        {"title": "New Body", "start": 20.0, "end": 80.0},
        {"title": "Outro", "start": 80.0, "end": 100.0},
    ]
    client = _make_client("admin")
    resp = client.post(
        f"/video/{seeded_series}/approve",
        json={"parts": new_parts},
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] == 1
    assert len(data["parts"]) == 3
    assert data["parts"][0]["title"] == "New Intro"
    assert data["parts"][1]["end"] == 80.0


def test_approve_persists_to_db(seeded_series):
    """Verify the DB row is actually updated, not just returned from memory."""
    client = _make_client("admin")
    client.post(
        f"/video/{seeded_series}/approve",
        json={"parts": [{"title": "Solo", "start": 0.0, "end": 60.0}]},
        headers={"Authorization": "Bearer tok"},
    )
    with SessionLocal() as db:
        row = db.get(MiniSeries, seeded_series)
        assert row.approved == 1
        assert len(row.parts_json) == 1
        assert row.parts_json[0]["title"] == "Solo"


def test_approve_404_unknown():
    client = _make_client("admin")
    resp = client.post(
        "/video/99999/approve",
        json={},
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 404


def test_approve_403_sales(seeded_series):
    client = _make_client("sales")
    resp = client.post(
        f"/video/{seeded_series}/approve",
        json={},
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code == 403


def test_approve_401_no_token(seeded_series):
    client = _make_client("admin")
    resp = client.post(f"/video/{seeded_series}/approve", json={})
    assert resp.status_code == 401
