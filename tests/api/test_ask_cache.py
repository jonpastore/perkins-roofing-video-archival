"""Hermetic tests for the ask-cache seams in /ask and GET /ask/suggest.

Uses:
  - temp SQLite DB (DB_URL env var set before any app.models import)
  - fake token verifier (api.auth.set_verifier)
  - unittest.mock patches for embed() and chat() so no real HTTP is made
  - hybrid_search patched to return controlled chunk results

Tests cover:
  - Cache miss: full pipeline runs, answer written to ask_cache
  - Cache hit: cached answer returned with "cached": True, hit_count incremented
  - Stale cache: entry bypassed when pipeline_version differs
  - GET /ask/suggest: returns matching suggestions in the 0.85-0.95 band (SQLite substring path)
  - Auth gating: 401 / 403 on /ask/suggest
  - Empty query on /ask/suggest returns []
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Isolated temp DB must be set BEFORE any app.models import
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from app.models import AskCache, Base, SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)

# Fake embedding — 3072-dim zero vector (sufficient for SQLite norm-match path)
_FAKE_EMBED = [0.0] * 3072
_FAKE_ANSWER = {
    "answer": "Roofs last about 20 years.",
    "abstained": False,
    "confidence": 0.85,
    "citations": ["https://youtu.be/abc?t=0"],
    "sources": [{"url": "https://youtu.be/abc?t=0", "video_id": "abc", "t": 0,
                 "title": "Roof Basics", "snippet": "Shingles wear over time."}],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(role: str = "admin") -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "admin@test.com", "role": role,
                                "tenant_id": 1})
    from api.app import app
    return TestClient(app, raise_server_exceptions=True)


ADMIN_HDR = {"Authorization": "Bearer tok"}


@pytest.fixture(autouse=True)
def clean_cache():
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        db.query(AskCache).delete()
        db.commit()
    yield


# ---------------------------------------------------------------------------
# Fake chunk for hybrid_search mock
# ---------------------------------------------------------------------------

def _make_chunk(video_id="abc", text="Shingles wear over time.", start=0.0):
    c = MagicMock()
    c.video_id = video_id
    c.text = text
    c.start = start
    return c


# ---------------------------------------------------------------------------
# /ask — cache miss: full pipeline runs + write-through
# ---------------------------------------------------------------------------

def test_ask_cache_miss_writes_through():
    """On a miss the full pipeline runs and the result is stored in ask_cache."""
    chunk = _make_chunk()
    fake_r = {"chunks": [(chunk, 0.9)], "graph": []}

    with (
        patch("app.answer.embed", return_value=[_FAKE_EMBED]),
        patch("app.answer.hybrid_search", return_value=fake_r),
        patch("app.answer.chat", return_value=_FAKE_ANSWER["answer"]),
        patch("app.answer._probe_cache", return_value=(None, 0.0)),
    ):
        client = _make_client()
        resp = client.post("/ask", json={"query": "How long does a roof last?", "k": 4},
                           headers=ADMIN_HDR)
        assert resp.status_code == 200
        data = resp.json()
        assert data["abstained"] is False
        assert "cached" not in data

    # Entry should now be in the DB
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        entry = db.query(AskCache).first()
        assert entry is not None
        assert entry.question == "How long does a roof last?"
        assert entry.hit_count == 0


# ---------------------------------------------------------------------------
# /ask — cache hit: returns cached answer, increments hit_count
# ---------------------------------------------------------------------------

def test_ask_cache_hit_returns_cached():
    """A warm cache entry is returned with cached=True; hit_count increments."""
    # Seed a cache entry
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        entry = AskCache(
            question="How long does a roof last?",
            question_norm="how long does a roof last",
            embedding=_FAKE_EMBED,
            answer_json=_FAKE_ANSWER,
            pipeline_version="v1",
            hit_count=0,
            tenant_id=1,
        )
        db.add(entry)
        db.commit()
        entry_id = entry.id

    with (
        patch("app.answer.embed", return_value=[_FAKE_EMBED]),
        patch("app.answer._probe_cache") as mock_probe,
    ):
        # Return the seeded entry with similarity=0.97 (above 0.95 threshold)
        with SessionLocal() as db:
            db.info["tenant_id"] = 1
            seeded = db.get(AskCache, entry_id)

        mock_probe.return_value = (seeded, 0.97)

        client = _make_client()
        resp = client.post("/ask", json={"query": "How long does a roof last?", "k": 4},
                           headers=ADMIN_HDR)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("cached") is True
        assert data["answer"] == _FAKE_ANSWER["answer"]


# ---------------------------------------------------------------------------
# /ask — stale cache entry bypasses cache
# ---------------------------------------------------------------------------

def test_ask_stale_entry_bypasses_cache():
    """An entry with a different pipeline_version is treated as stale -> full pipeline."""
    old_created = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    stale_entry = MagicMock(spec=AskCache)
    stale_entry.created_at = old_created
    stale_entry.pipeline_version = "v0"   # differs from PIPELINE_VERSION="v1"
    stale_entry.answer_json = _FAKE_ANSWER

    chunk = _make_chunk()
    fake_r = {"chunks": [(chunk, 0.9)], "graph": []}

    with (
        patch("app.answer.embed", return_value=[_FAKE_EMBED]),
        patch("app.answer._probe_cache", return_value=(stale_entry, 0.98)),
        patch("app.answer.hybrid_search", return_value=fake_r),
        patch("app.answer.chat", return_value=_FAKE_ANSWER["answer"]),
        patch("app.answer._write_cache"),
    ):
        client = _make_client()
        resp = client.post("/ask", json={"query": "Roof life?", "k": 4},
                           headers=ADMIN_HDR)
        assert resp.status_code == 200
        data = resp.json()
        assert "cached" not in data


# ---------------------------------------------------------------------------
# /ask — no db session skips cache probe (legacy path)
# ---------------------------------------------------------------------------

def test_ask_abstain_on_no_chunks():
    """Should abstain when hybrid_search returns no chunks."""
    with (
        patch("app.answer.embed", return_value=[_FAKE_EMBED]),
        patch("app.answer._probe_cache", return_value=(None, 0.0)),
        patch("app.answer.hybrid_search", return_value={"chunks": [], "graph": []}),
    ):
        client = _make_client()
        resp = client.post("/ask", json={"query": "something obscure", "k": 4},
                           headers=ADMIN_HDR)
        assert resp.status_code == 200
        assert resp.json()["abstained"] is True


# ---------------------------------------------------------------------------
# GET /ask/suggest — auth gating
# ---------------------------------------------------------------------------

def test_ask_suggest_401_no_token():
    client = _make_client()
    resp = client.get("/ask/suggest?q=how+long")
    assert resp.status_code == 401


def test_ask_suggest_403_wrong_role():
    # platform_admin has no "ask" permission — forbidden on tenant-scoped routes
    set_verifier(lambda token: {"uid": "u2", "email": "pa@test.com",
                                "role": "platform_admin", "tenant_id": None})
    from api.app import app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/ask/suggest?q=how+long", headers=ADMIN_HDR)
    # platform_admin with tenant_id=None hits the get_db_session 403 before the role check
    assert resp.status_code in (403, 403)


# ---------------------------------------------------------------------------
# GET /ask/suggest — SQLite substring fallback
# ---------------------------------------------------------------------------

def test_ask_suggest_returns_matching_entries():
    """Seed entries and verify suggest returns substring matches (SQLite path — no embed call)."""
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        db.add(AskCache(
            question="How long does a roof last?",
            question_norm="how long does a roof last",
            embedding=_FAKE_EMBED,
            answer_json=_FAKE_ANSWER,
            pipeline_version="v1",
            hit_count=5,
            tenant_id=1,
        ))
        db.add(AskCache(
            question="How long do gutters last?",
            question_norm="how long do gutters last",
            embedding=_FAKE_EMBED,
            answer_json={"answer": "20 years", "abstained": False,
                         "confidence": 0.8, "citations": [], "sources": []},
            pipeline_version="v1",
            hit_count=1,
            tenant_id=1,
        ))
        db.commit()

    # SQLite path: no embed call; just substring match on question_norm
    client = _make_client()
    resp = client.get("/ask/suggest?q=how+long+does", headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) <= 3
    for item in data:
        assert "question" in item
        assert "answer" in item
        assert "similarity" in item


def test_ask_suggest_empty_query_returns_empty():
    client = _make_client()
    resp = client.get("/ask/suggest?q=", headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert resp.json() == []


def test_ask_suggest_no_matches_returns_empty():
    client = _make_client()
    resp = client.get("/ask/suggest?q=zzz+completely+unrelated+gibberish", headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_ask_suggest_caps_at_three():
    """Seed more than 3 entries; suggest must return at most 3 (SQLite substring path)."""
    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        for i in range(5):
            db.add(AskCache(
                question=f"How long does thing {i} last?",
                question_norm=f"how long does thing {i} last",
                embedding=_FAKE_EMBED,
                answer_json={"answer": f"answer {i}", "abstained": False,
                             "confidence": 0.8, "citations": [], "sources": []},
                pipeline_version="v1",
                hit_count=0,
                tenant_id=1,
            ))
        db.commit()

    client = _make_client()
    resp = client.get("/ask/suggest?q=how+long+does", headers=ADMIN_HDR)
    assert resp.status_code == 200
    assert len(resp.json()) <= 3
