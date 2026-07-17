"""Hermetic tests for POST /clips/search (api/routes/clips.py).

Uses a temp SQLite DB + fake token verifier (same pattern as tests/api/test_clips.py),
plus monkeypatched app.retrieval.hybrid_search and app.llm.chat — no live DB/LLM needed.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from api.routes.clips import router  # noqa: E402
from app.models import Base, engine  # noqa: E402

Base.metadata.create_all(engine)

ADMIN_HDR = {"Authorization": "Bearer tok"}


def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "admin@test.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def _fake_chunk(video_id: str, start: float, end: float, text: str) -> SimpleNamespace:
    """Stand-in for app.models.Chunk — route only reads these four attributes."""
    return SimpleNamespace(video_id=video_id, start=start, end=end, text=text)


@pytest.fixture()
def fake_hits(monkeypatch):
    """Two candidate chunks from two different videos, as app.retrieval.hybrid_search returns them."""
    chunks = [
        (_fake_chunk("vid_a", 10.0, 35.0, "The most common cause is flashing failure."), 0.8),
        (_fake_chunk("vid_b", 60.0, 85.0, "Call us for a free inspection today."), 0.6),
    ]
    monkeypatch.setattr(
        "app.retrieval.hybrid_search",
        lambda prompt, k=8, db=None: {"chunks": chunks, "graph": []},
    )
    return chunks


def test_search_403_sales(fake_hits):
    client = _make_client("sales")
    resp = client.post("/clips/search", json={"prompt": "flashing failure"}, headers=ADMIN_HDR)
    assert resp.status_code == 403


def test_search_401_no_token(fake_hits):
    client = _make_client("admin")
    resp = client.post("/clips/search", json={"prompt": "flashing failure"})
    assert resp.status_code == 401


def test_search_422_k_over_limit(fake_hits):
    client = _make_client("admin")
    resp = client.post("/clips/search", json={"prompt": "flashing failure", "k": 21}, headers=ADMIN_HDR)
    assert resp.status_code == 422


def test_search_200_llm_ranks_and_recovers_video_id(fake_hits, monkeypatch):
    monkeypatch.setattr(
        "app.llm.chat",
        lambda prompt, want_json=False, timeout=300: (
            '[{"start": 10.0, "end": 35.0, "score": 91, "reason": "strong hook"},'
            ' {"start": 60.0, "end": 85.0, "score": 40, "reason": "weaker CTA"}]'
        ),
    )
    client = _make_client("admin")
    resp = client.post(
        "/clips/search", json={"prompt": "flashing failure", "k": 8}, headers=ADMIN_HDR
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    results = data["results"]
    assert len(results) == 2
    assert results[0]["video_id"] == "vid_a"
    assert results[0]["score"] == 91
    assert results[0]["reason"] == "strong hook"
    assert results[0]["text"] == "The most common cause is flashing failure."


def test_search_200_llm_failure_falls_back_to_retrieval_score(fake_hits, monkeypatch):
    def _bad_chat(prompt, want_json=False, timeout=300):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("app.llm.chat", _bad_chat)

    client = _make_client("admin")
    resp = client.post("/clips/search", json={"prompt": "flashing failure"}, headers=ADMIN_HDR)
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2
    # Retrieval-score fallback ordering: vid_a (0.8) before vid_b (0.6); no LLM reason.
    assert results[0]["video_id"] == "vid_a"
    assert results[0]["reason"] == ""


def test_search_200_empty_chunks(monkeypatch):
    monkeypatch.setattr(
        "app.retrieval.hybrid_search",
        lambda prompt, k=8, db=None: {"chunks": [], "graph": []},
    )
    client = _make_client("admin")
    resp = client.post("/clips/search", json={"prompt": "nothing matches"}, headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert resp.json() == {"results": []}
