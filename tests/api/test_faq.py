"""Behavioral tests for api/routes/faq.py.

Uses a fresh FastAPI app (not the real api.app) so the router is tested in
isolation. The conftest.py sets DB_URL to a temp SQLite file before any import.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.faq import router
from app.models import GraphNode, SessionLocal, init_db


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(_make_app())


def _sales_client():
    set_verifier(lambda token: {"uid": "u2", "email": "sales@x.com", "role": "sales"})
    return TestClient(_make_app())


AUTH = {"Authorization": "Bearer tok"}


def setup_module(module):
    init_db()
    # Seed content_graph with objection + claim rows for tests
    with SessionLocal() as db:
        existing = db.query(GraphNode).filter(
            GraphNode.video_id == "testvid1"
        ).count()
        if existing == 0:
            db.add(GraphNode(
                video_id="testvid1",
                kind="objections",
                label="Metal roofs are too noisy in rain",
                detail="Many homeowners worry about rain noise on metal roofs",
                start=42.0,
                version="v1",
            ))
            db.add(GraphNode(
                video_id="testvid1",
                kind="claims",
                label="How long does a roof installation take?",
                detail="Typical installation timeline for a full replacement",
                start=90.0,
                version="v1",
            ))
            db.add(GraphNode(
                video_id="testvid2",
                kind="objections",
                label="Shingles vs metal cost comparison",
                detail="",
                start=15.0,
                version="v1",
            ))
            # A row without start — should be excluded from mined
            db.add(GraphNode(
                video_id="testvid1",
                kind="claims",
                label="No timestamp claim",
                detail="",
                start=None,
                version="v1",
            ))
            db.commit()


# ---------------------------------------------------------------------------
# GET /faq/mined — helpers
# ---------------------------------------------------------------------------

def _fake_rephrase(statements):
    """LLM stub: prefix each statement with 'Rephrased: ' and append '?'."""
    return [f"Rephrased: {s}?" for s in statements]


def _failing_rephrase(statements):
    """LLM stub that simulates a failure (returns empty list → fallback)."""
    return []


# ---------------------------------------------------------------------------
# GET /faq/mined
# ---------------------------------------------------------------------------

def test_mined_returns_list(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    assert len(items) >= 3


def test_mined_item_shape(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined", headers=AUTH)
    assert r.status_code == 200, r.text
    item = r.json()[0]
    assert "question" in item
    assert "video_id" in item
    assert "t" in item
    assert "url" in item
    assert item["url"].startswith("https://youtu.be/")
    assert "?t=" in item["url"]


def test_mined_question_comes_from_rephraser(monkeypatch):
    """Questions should come from the LLM rephraser when it succeeds."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined", headers=AUTH)
    items = r.json()
    assert len(items) >= 1
    for item in items:
        assert item["question"].startswith("Rephrased: "), (
            f"Expected rephrased question, got: {item['question']!r}"
        )
        assert item["question"].endswith("?"), f"Not a question: {item['question']!r}"


def test_mined_fallback_when_llm_fails(monkeypatch):
    """When the rephraser returns [], fall back to the heuristic (still ends with '?')."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _failing_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    for item in items:
        assert item["question"].endswith("?"), f"Not a question: {item['question']!r}"
        assert not item["question"].startswith("Rephrased: "), "Fallback should not use rephraser prefix"


def test_mined_question_ends_with_questionmark(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined", headers=AUTH)
    items = r.json()
    for item in items:
        assert item["question"].endswith("?"), f"Not a question: {item['question']!r}"


def test_mined_excludes_rows_without_start(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined", headers=AUTH)
    questions = [i["question"] for i in r.json()]
    # The row with label "No timestamp claim" and start=None must be absent
    assert not any("No timestamp claim" in q for q in questions)


def test_mined_filter_by_q(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined?q=noisy", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    for item in items:
        assert "noisy" in item["question"].lower()


def test_mined_filter_no_match(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined?q=zzznomatchzzz", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_mined_limit(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _admin_client()
    r = c.get("/faq/mined?limit=2", headers=AUTH)
    assert r.status_code == 200, r.text
    assert len(r.json()) <= 2


def test_sales_can_get_mined(monkeypatch):
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _sales_client()
    r = c.get("/faq/mined", headers=AUTH)
    assert r.status_code == 200, r.text


def test_mined_401_without_token():
    c = _admin_client()
    r = c.get("/faq/mined")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# POST /faq/build
# ---------------------------------------------------------------------------

def test_build_returns_faq(monkeypatch):
    # Monkeypatch app.answer.ask to avoid live LLM/network
    import api.routes.faq as faq_module

    def fake_ask(question):
        return {
            "answer": f"Answer for: {question}",
            "citations": ["https://youtu.be/testvid1?t=42"],
        }

    monkeypatch.setattr(faq_module, "ask", fake_ask, raising=False)
    # Also patch at the import path used inside the route
    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "ask", fake_ask)

    c = _admin_client()
    r = c.post(
        "/faq/build",
        json={"questions": ["What is the best roofing material?"]},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "faq" in data
    assert len(data["faq"]) == 1
    entry = data["faq"][0]
    assert entry["question"] == "What is the best roofing material?"
    assert "answer" in entry
    assert "citations" in entry


def test_build_skips_blank_questions(monkeypatch):
    import app.answer as answer_mod

    calls = []

    def fake_ask(question):
        calls.append(question)
        return {"answer": "ok", "citations": []}

    monkeypatch.setattr(answer_mod, "ask", fake_ask)

    c = _admin_client()
    r = c.post(
        "/faq/build",
        json={"questions": ["Valid question?", "", "   ", "Another?"]},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # blank/whitespace-only questions must be skipped
    assert len(data["faq"]) == 2


def test_sales_cannot_build():
    c = _sales_client()
    r = c.post(
        "/faq/build",
        json={"questions": ["What is metal roofing?"]},
        headers=AUTH,
    )
    assert r.status_code == 403, r.text


def test_build_401_without_token():
    c = _admin_client()
    r = c.post("/faq/build", json={"questions": ["Q?"]})
    assert r.status_code == 401, r.text
