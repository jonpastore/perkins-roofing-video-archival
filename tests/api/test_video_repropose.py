"""Hermetic tests for POST /video/{series_id}/repropose.

Exercises the content-driven re-proposal that fixes the old 0/.25/.5/.75
equal-quarter parts bug. Uses a temp SQLite DB + a fake token verifier, and
monkeypatches the LLM so the deterministic content-graph fallback is exercised.
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
from api.routes.video import router  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    GraphNode,
    MiniSeries,
    Segment,
    SessionLocal,
    Video,
    engine,
)

Base.metadata.create_all(engine)

AUTH = {"Authorization": "Bearer tok"}


def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clean_db():
    with SessionLocal() as db:
        db.query(MiniSeries).delete()
        db.query(GraphNode).delete()
        db.query(Segment).delete()
        db.query(Video).delete()
        db.commit()
    yield


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Force the deterministic content-graph fallback in every test."""
    def _bad_chat(prompt, want_json=False, timeout=300):
        raise RuntimeError("LLM disabled in tests")

    monkeypatch.setattr("app.llm.chat", _bad_chat)


@pytest.fixture()
def bad_series():
    """A MiniSeries with the OLD degenerate 0/.25/.5/.75 parts + emoji title."""
    video_id = "vid_repro"
    with SessionLocal() as db:
        db.add(Video(id=video_id, title="\U0001F3E0 Roof Repair 101 #diy", duration=300.0))
        cap = "youtube_caption"
        db.add(Segment(video_id=video_id, text="Intro to leaks", start=0.0, end=30.0, source=cap))
        db.add(Segment(video_id=video_id, text="Flashing failure explained", start=30.0, end=90.0, source=cap))
        db.add(Segment(video_id=video_id, text="Call us for a free inspection", start=200.0, end=240.0, source=cap))
        db.add(GraphNode(video_id=video_id, kind="topics", label="Flashing Failure", start=40.0, version="v1"))
        db.add(GraphNode(video_id=video_id, kind="ctas", label="Free Inspection", start=210.0, version="v1"))
        s = MiniSeries(
            video_id=video_id,
            title="\U0001F3E0 Roof Repair 101 #diy",
            parts_json=[
                {"title": "Part 1", "start": 0.0, "end": 0.25},
                {"title": "Part 2", "start": 0.25, "end": 0.5},
                {"title": "Part 3", "start": 0.5, "end": 0.75},
                {"title": "Part 4", "start": 0.75, "end": 1.0},
            ],
            approved=1,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id


# ---------------------------------------------------------------------------
# role gating
# ---------------------------------------------------------------------------

def test_repropose_401_no_token(bad_series):
    client = _make_client("admin")
    resp = client.post(f"/video/{bad_series}/repropose")
    assert resp.status_code == 401


def test_repropose_403_sales(bad_series):
    client = _make_client("sales")
    resp = client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    assert resp.status_code == 403


def test_repropose_404_unknown():
    client = _make_client("admin")
    resp = client.post("/video/99999/repropose", headers=AUTH)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# behavior — fixes the fraction bug
# ---------------------------------------------------------------------------

def test_repropose_replaces_fraction_parts_with_real_seconds(bad_series):
    client = _make_client("admin")
    resp = client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()

    parts = data["parts"]
    assert len(parts) >= 1
    # Old bug: every end <= 1.0. New parts must be real seconds into a 300s video.
    assert all(p["end"] > 1.0 for p in parts)
    assert any(p["end"] > 30.0 for p in parts)
    # anchored on real content-graph node starts
    starts = {p["start"] for p in parts}
    assert 40.0 in starts or 210.0 in starts
    # non-overlapping + in-bounds
    prev = -1.0
    for p in parts:
        assert 0.0 <= p["start"] < p["end"] <= 300.0
        assert p["start"] >= prev - 1e-6
        prev = p["end"]


def test_repropose_cleans_title_and_resets_approved(bad_series):
    client = _make_client("admin")
    resp = client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    data = resp.json()
    assert "\U0001F3E0" not in data["title"]
    assert "#" not in data["title"]
    assert "Roof Repair 101" in data["title"]
    # re-proposal must go back to pending for re-review
    assert data["approved"] == 0
    assert data["duration"] == 300.0


def test_repropose_part_titles_have_name_and_part_n(bad_series):
    client = _make_client("admin")
    resp = client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    parts = resp.json()["parts"]
    for i, p in enumerate(parts, start=1):
        assert p["title"].rstrip().endswith(f"(Part {i})")
        assert "Roof Repair 101" in p["title"]


def test_repropose_persists_to_db(bad_series):
    client = _make_client("admin")
    client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    with SessionLocal() as db:
        row = db.get(MiniSeries, bad_series)
        assert row.approved == 0
        assert all(p["end"] > 1.0 for p in row.parts_json)


def test_repropose_uses_llm_clips_when_available(bad_series, monkeypatch):
    """When the LLM returns valid clip windows, those real-second windows are used."""
    fake = {
        "clips": [
            {"start": 30.0, "end": 85.0, "title": "Flashing Deep Dive"},
            {"start": 200.0, "end": 240.0, "title": "Book Your Inspection"},
        ]
    }
    monkeypatch.setattr("app.llm.chat", lambda prompt, want_json=False, timeout=300: fake)

    client = _make_client("admin")
    resp = client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    assert resp.status_code == 200
    parts = resp.json()["parts"]
    assert len(parts) == 2
    assert parts[0]["start"] == 30.0 and parts[0]["end"] == 85.0
    assert "Flashing Deep Dive" in parts[0]["title"]
    assert parts[0]["title"].rstrip().endswith("(Part 1)")


def test_repropose_404_when_video_missing(bad_series):
    """Series exists but its source Video row is gone -> 404."""
    with SessionLocal() as db:
        db.query(Video).delete()
        db.commit()
    client = _make_client("admin")
    resp = client.post(f"/video/{bad_series}/repropose", headers=AUTH)
    assert resp.status_code == 404
