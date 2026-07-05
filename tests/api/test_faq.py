"""Behavioral tests for the persistent FAQ system (api/routes/faq.py).

Uses a fresh FastAPI app (not the real api.app) so the router is tested in
isolation. The conftest.py sets DB_URL to a temp SQLite file before any import.

All LLM calls (app.llm.chat via _rephrase_via_llm, app.answer.ask) are monkeypatched
so no live network calls are made.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.faq import router
from app.models import FaqEntry, GraphNode, SessionLocal, Video, init_db


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

# Node IDs assigned during seeding (populated in setup_module)
_NODE_IDS: dict = {}


def setup_module(module):
    init_db()
    with SessionLocal() as db:
        # Clean slate for FAQ entries (nodes may already exist from other test modules)
        db.query(FaqEntry).delete()
        db.commit()

        # Ensure video rows exist for title join tests
        if not db.query(Video).filter(Video.id == "testvid1").first():
            db.add(Video(id="testvid1", title="Roof Installation Guide"))
        if not db.query(Video).filter(Video.id == "testvid2").first():
            db.add(Video(id="testvid2", title="Shingles vs Metal"))
        db.commit()

        # Seed content_graph nodes (idempotent: skip if already present)
        existing = db.query(GraphNode).filter(GraphNode.video_id == "testvid1").count()
        if existing == 0:
            n1 = GraphNode(video_id="testvid1", kind="objections",
                           label="Metal roofs are too noisy in rain",
                           detail="Many homeowners worry about rain noise on metal roofs",
                           start=42.0, version="v1")
            n2 = GraphNode(video_id="testvid1", kind="claims",
                           label="How long does a roof installation take?",
                           detail="Typical installation timeline for a full replacement",
                           start=90.0, version="v1")
            n3 = GraphNode(video_id="testvid2", kind="objections",
                           label="Shingles vs metal cost comparison",
                           detail="", start=15.0, version="v1")
            # No timestamp — must be excluded from mining
            n4 = GraphNode(video_id="testvid1", kind="claims",
                           label="No timestamp claim", detail="", start=None, version="v1")
            db.add_all([n1, n2, n3, n4])
            db.commit()
            _NODE_IDS["n1"] = n1.id
            _NODE_IDS["n2"] = n2.id
            _NODE_IDS["n3"] = n3.id
            _NODE_IDS["n4"] = n4.id
        else:
            nodes = db.query(GraphNode).filter(GraphNode.video_id.in_(["testvid1", "testvid2"])).all()
            for n in nodes:
                if n.label == "Metal roofs are too noisy in rain":
                    _NODE_IDS["n1"] = n.id
                elif n.label == "How long does a roof installation take?":
                    _NODE_IDS["n2"] = n.id
                elif n.label == "Shingles vs metal cost comparison":
                    _NODE_IDS["n3"] = n.id
                elif n.label == "No timestamp claim":
                    _NODE_IDS["n4"] = n.id


def teardown_module(module):
    """Clean up FAQ entries after this module so other test modules start fresh."""
    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()


# ---------------------------------------------------------------------------
# LLM stubs
# ---------------------------------------------------------------------------

def _fake_rephrase(statements):
    """Returns 'Rephrased: <statement>?' for each item — same length as input."""
    return [f"Rephrased: {s}?" for s in statements]


def _failing_rephrase(statements):
    """Simulates LLM failure — triggers heuristic fallback."""
    return []


def _fake_ask(question):
    return {
        "answer": f"Answer for: {question}",
        "citations": ["https://youtu.be/testvid1?t=42"],
        "abstained": False,
    }


def test_answer_html_renders_link_citations():
    """`[link n](url)` markdown citations become anchors; other text is escaped."""
    from api.routes.faq import _answer_html, _answer_plain
    ans = "Two layers are required [1].\n\nSources: [link 1](https://youtu.be/abc?t=5)"
    html = _answer_html(ans)
    assert '<a href="https://youtu.be/abc?t=5"' in html
    assert ">link 1</a>" in html
    assert "[link 1]" not in html  # markdown consumed, not left raw
    # JSON-LD text drops the Sources citation line entirely
    assert _answer_plain(ans) == "Two layers are required [1]."


def _fake_answer_faq(question, k=6):
    return {
        "answer": f"Answer for: {question}\n\nSources: [link 1](https://youtu.be/testvid1?t=42)",
        "abstained": False,
        "confidence": 0.9,
        "sources": [{"n": 1, "video_id": "testvid1", "t": 42,
                     "title": "Roof Installation Guide",
                     "url": "https://youtu.be/testvid1?t=42"}],
    }


@pytest.fixture(autouse=True)
def _stub_answer_faq(monkeypatch):
    """Default: /faq/mine's coupled answering abstains (no network). Answer-specific
    tests override this with _fake_answer_faq to assert stored answers."""
    import app.answer as answer_mod
    monkeypatch.setattr(
        answer_mod, "answer_faq",
        lambda question, k=6: {"answer": "", "abstained": True, "sources": []},
        raising=False,
    )


# ---------------------------------------------------------------------------
# POST /faq/mine
# ---------------------------------------------------------------------------

def test_mine_creates_entries(monkeypatch):
    """Mining with 3 eligible nodes (start != None) should create 3 entries."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    # Ensure clean slate
    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()

    c = _admin_client()
    r = c.post("/faq/mine", json={"limit": 200}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mined"] == 3, f"Expected 3, got {data}"
    assert data["remaining_uncovered"] == 0

    with SessionLocal() as db:
        count = db.query(FaqEntry).count()
    assert count == 3


def test_mine_idempotent(monkeypatch):
    """Mining again when all nodes are covered returns mined=0, no duplicates."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    # Ensure entries exist from previous test (or re-mine)
    with SessionLocal() as db:
        count = db.query(FaqEntry).count()
    if count == 0:
        c = _admin_client()
        c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    c = _admin_client()
    r = c.post("/faq/mine", json={"limit": 200}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mined"] == 0, f"Expected 0 new on second mine, got {data['mined']}"

    with SessionLocal() as db:
        count = db.query(FaqEntry).count()
    assert count == 3, f"Expected exactly 3 entries (no duplicates), got {count}"


def test_mine_tags_source_node(monkeypatch):
    """Each FaqEntry links back to the correct source_node_id."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    with SessionLocal() as db:
        entries = db.query(FaqEntry).all()
        node_ids_in_entries = {e.source_node_id for e in entries}
    # n4 has start=None so it must NOT be tagged
    assert _NODE_IDS.get("n4") not in node_ids_in_entries
    # The three valid nodes must all be tagged
    for key in ("n1", "n2", "n3"):
        assert _NODE_IDS[key] in node_ids_in_entries, f"{key} not tagged"


def test_mine_questions_use_rephraser(monkeypatch):
    """Questions should come from the LLM rephraser (prefix 'Rephrased:')."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    with SessionLocal() as db:
        entries = db.query(FaqEntry).all()
    for e in entries:
        assert e.question.startswith("Rephrased: "), f"Unexpected: {e.question!r}"
        assert e.question.endswith("?")


def test_mine_fallback_heuristic(monkeypatch):
    """When LLM fails, heuristic produces questions ending with '?' without 'Rephrased:' prefix."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _failing_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    r = c.post("/faq/mine", json={"limit": 200}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["mined"] == 3

    with SessionLocal() as db:
        entries = db.query(FaqEntry).all()
    for e in entries:
        assert e.question.endswith("?")
        assert not e.question.startswith("Rephrased: ")


def test_mine_excludes_no_timestamp(monkeypatch):
    """Nodes with start=None are never mined."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    with SessionLocal() as db:
        entries = db.query(FaqEntry).all()
    questions = [e.question for e in entries]
    assert not any("No timestamp claim" in q for q in questions)


def test_mine_sales_forbidden(monkeypatch):
    """Sales role cannot call POST /faq/mine."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    c = _sales_client()
    r = c.post("/faq/mine", json={"limit": 10}, headers=AUTH)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# GET /faq
# ---------------------------------------------------------------------------

def _ensure_entries(monkeypatch):
    """Helper: ensure 3 mined entries exist."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)
    with SessionLocal() as db:
        if db.query(FaqEntry).count() == 0:
            c = _admin_client()
            c.post("/faq/mine", json={"limit": 200}, headers=AUTH)


def test_get_faq_returns_items(monkeypatch):
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r = c.get("/faq", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data
    assert "items" in data
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_get_faq_item_shape(monkeypatch):
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r = c.get("/faq", headers=AUTH)
    item = r.json()["items"][0]
    for key in ("id", "question", "answer", "status", "video_id", "video_title", "url", "start"):
        assert key in item, f"Missing key: {key}"
    assert item["url"].startswith("https://youtu.be/")
    assert "?t=" in item["url"]


def test_get_faq_video_title_not_raw_id(monkeypatch):
    """video_title must be the human title from the videos table, not the raw video_id."""
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r = c.get("/faq", headers=AUTH)
    items = r.json()["items"]
    for item in items:
        # Title must not equal video_id (it should be the actual title)
        assert item["video_title"] != item["video_id"], (
            f"video_title is raw id: {item['video_title']!r}"
        )


def test_get_faq_answered_filter_no(monkeypatch):
    """?answered=no returns only mined (unanswered) entries."""
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r = c.get("/faq?answered=no", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    for item in data["items"]:
        assert item["status"] == "mined"


def test_get_faq_answered_filter_yes(monkeypatch):
    """?answered=yes returns only answered entries (empty when none answered)."""
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r = c.get("/faq?answered=yes", headers=AUTH)
    assert r.status_code == 200, r.text
    # Initially none are answered
    assert r.json()["total"] == 0


def test_get_faq_search_q(monkeypatch):
    """?q= filters by substring in question text."""
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r = c.get("/faq?q=noisy", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 1
    for item in items:
        assert "noisy" in item["question"].lower()


def test_get_faq_pagination(monkeypatch):
    """limit + offset paginate correctly."""
    _ensure_entries(monkeypatch)
    c = _admin_client()
    r1 = c.get("/faq?limit=2&offset=0", headers=AUTH)
    r2 = c.get("/faq?limit=2&offset=2", headers=AUTH)
    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()
    d2 = r2.json()
    assert d1["total"] == 3
    assert len(d1["items"]) == 2
    assert len(d2["items"]) == 1
    # No overlap
    ids1 = {i["id"] for i in d1["items"]}
    ids2 = {i["id"] for i in d2["items"]}
    assert ids1.isdisjoint(ids2)


def test_get_faq_sales_allowed(monkeypatch):
    """Sales role can GET /faq."""
    _ensure_entries(monkeypatch)
    c = _sales_client()
    r = c.get("/faq", headers=AUTH)
    assert r.status_code == 200, r.text


def test_get_faq_401_without_token():
    c = _admin_client()
    r = c.get("/faq")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# POST /faq/{id}/answer
# ---------------------------------------------------------------------------

def test_answer_one_stores_answer(monkeypatch):
    """POST /faq/{id}/answer generates + stores the answer, sets status=answered."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    with SessionLocal() as db:
        entry_id = db.query(FaqEntry.id).first()[0]

    # Patch the concise FAQ answerer used by _answer_entry
    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "answer_faq", _fake_answer_faq)

    r = c.post(f"/faq/{entry_id}/answer", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert data["answer"].startswith("Answer for:")

    with SessionLocal() as db:
        entry = db.query(FaqEntry).filter(FaqEntry.id == entry_id).first()
    assert entry.status == "answered"
    assert entry.answer.startswith("Answer for:")


def test_answer_one_404_unknown(monkeypatch):
    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "ask", _fake_ask)
    c = _admin_client()
    r = c.post("/faq/999999/answer", headers=AUTH)
    assert r.status_code == 404, r.text


def test_answer_one_sales_forbidden():
    """Sales role cannot POST /faq/{id}/answer."""
    c = _sales_client()
    r = c.post("/faq/1/answer", headers=AUTH)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# POST /faq/answer-batch
# ---------------------------------------------------------------------------

def test_answer_batch(monkeypatch):
    """answer-batch answers up to limit unanswered entries."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "answer_faq", _fake_answer_faq)

    r = c.post("/faq/answer-batch", json={"limit": 25}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["answered"] == 3
    assert data["remaining"] == 0

    with SessionLocal() as db:
        answered = db.query(FaqEntry).filter(FaqEntry.status == "answered").count()
    assert answered == 3


def test_answer_batch_respects_limit(monkeypatch):
    """answer-batch with limit=1 answers only 1 entry."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "answer_faq", _fake_answer_faq)

    r = c.post("/faq/answer-batch", json={"limit": 1}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["answered"] == 1
    assert data["remaining"] == 2


def test_answer_batch_sales_forbidden():
    c = _sales_client()
    r = c.post("/faq/answer-batch", json={"limit": 5}, headers=AUTH)
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# GET /faq/coverage
# ---------------------------------------------------------------------------

def test_coverage_counts(monkeypatch):
    """Coverage reflects mined / answered / uncovered correctly."""
    import api.routes.faq as faq_mod
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()

    c = _admin_client()

    # Before mining
    r = c.get("/faq/coverage", headers=AUTH)
    assert r.status_code == 200, r.text
    before = r.json()
    assert before["mined"] == 0
    assert before["answered"] == 0
    assert before["uncovered_nodes"] == 3  # 3 nodes with start != None

    # After mining
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)
    r = c.get("/faq/coverage", headers=AUTH)
    mid = r.json()
    assert mid["mined"] == 3
    assert mid["answered"] == 0
    assert mid["uncovered_nodes"] == 0

    # After answering all
    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "answer_faq", _fake_answer_faq)
    c.post("/faq/answer-batch", json={"limit": 25}, headers=AUTH)
    r = c.get("/faq/coverage", headers=AUTH)
    after = r.json()
    assert after["mined"] == 3
    assert after["answered"] == 3
    assert after["uncovered_nodes"] == 0


def test_coverage_sales_allowed():
    """Sales role can GET /faq/coverage."""
    c = _sales_client()
    r = c.get("/faq/coverage", headers=AUTH)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# POST /faq/publish-wordpress
# ---------------------------------------------------------------------------

def _seed_answered_entries():
    """Insert two answered FaqEntry rows directly; return their IDs."""
    from datetime import datetime
    from app.models import GraphNode

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()

        # Reuse node IDs from setup_module (or grab any existing nodes)
        nodes = db.query(GraphNode).filter(
            GraphNode.kind.in_(("claims", "objections")),
            GraphNode.start.isnot(None),
        ).limit(2).all()
        assert nodes, "No eligible graph nodes found — run setup_module first"

        entries = []
        for i, node in enumerate(nodes):
            e = FaqEntry(
                question=f"Test question {i+1}?",
                answer=f"Test answer {i+1}.",
                source_kind="claim",
                source_node_id=node.id,
                video_id=node.video_id,
                start=node.start,
                status="answered",
                created_at=datetime.utcnow(),
            )
            db.add(e)
            entries.append(e)
        db.commit()
        ids = [e.id for e in entries]
    return ids


def test_publish_wordpress_no_creds(monkeypatch):
    """Returns 503 with a clear message when WP creds are absent."""
    monkeypatch.delenv("WP_URL", raising=False)
    monkeypatch.delenv("WP_USER", raising=False)
    monkeypatch.delenv("WP_APP_PWD", raising=False)

    _seed_answered_entries()
    c = _admin_client()
    r = c.post("/faq/publish-wordpress", headers=AUTH)
    assert r.status_code == 503, r.text
    assert "WordPress credentials" in r.json()["detail"]


def test_publish_wordpress_creates_page(monkeypatch):
    """When no existing FAQ page, calls wp.create_page and returns page_id + url."""
    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "admin")
    monkeypatch.setenv("WP_APP_PWD", "test-password")

    _seed_answered_entries()

    import adapters.wordpress as wp_mod
    created_ids = []

    def fake_find_page_by_title(title):
        return None  # no existing page

    def fake_create_page(*, title, html, meta_description, jsonld, status="publish"):
        created_ids.append(1)
        return 42  # fake page id

    monkeypatch.setattr(wp_mod, "find_page_by_title", fake_find_page_by_title)
    monkeypatch.setattr(wp_mod, "create_page", fake_create_page)

    c = _admin_client()
    r = c.post("/faq/publish-wordpress", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["page_id"] == 42
    assert data["action"] == "created"
    assert data["published"] == 2
    assert "example.com" in data["page_url"]
    assert created_ids == [1]


def test_publish_wordpress_updates_existing_page(monkeypatch):
    """When an existing FAQ page is found, calls wp.update_page instead."""
    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "admin")
    monkeypatch.setenv("WP_APP_PWD", "test-password")

    _seed_answered_entries()

    import adapters.wordpress as wp_mod
    updated_ids = []

    def fake_find_page_by_title(title):
        return 99  # existing page id

    def fake_update_page(page_id, *, title, html, meta_description, jsonld, status="publish"):
        updated_ids.append(page_id)

    monkeypatch.setattr(wp_mod, "find_page_by_title", fake_find_page_by_title)
    monkeypatch.setattr(wp_mod, "update_page", fake_update_page)

    c = _admin_client()
    r = c.post("/faq/publish-wordpress", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["page_id"] == 99
    assert data["action"] == "updated"
    assert data["published"] == 2
    assert updated_ids == [99]


def test_publish_wordpress_includes_faqpage_jsonld(monkeypatch):
    """The page is built with FAQPage JSON-LD containing all answered entries."""
    import json as _json

    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "admin")
    monkeypatch.setenv("WP_APP_PWD", "test-password")

    _seed_answered_entries()

    import adapters.wordpress as wp_mod
    captured = {}

    def fake_find_page_by_title(title):
        return None

    def fake_create_page(*, title, html, meta_description, jsonld, status="publish"):
        captured["jsonld"] = jsonld
        captured["html"] = html
        return 55

    monkeypatch.setattr(wp_mod, "find_page_by_title", fake_find_page_by_title)
    monkeypatch.setattr(wp_mod, "create_page", fake_create_page)

    c = _admin_client()
    r = c.post("/faq/publish-wordpress", headers=AUTH)
    assert r.status_code == 200, r.text

    # jsonld is a list with one FAQPage entry
    assert captured.get("jsonld"), "No JSON-LD captured"
    schema = captured["jsonld"][0]
    assert schema["@type"] == "FAQPage"
    entities = schema["mainEntity"]
    assert len(entities) == 2
    for entity in entities:
        assert entity["@type"] == "Question"
        assert entity["name"].endswith("?")
        assert entity["acceptedAnswer"]["@type"] == "Answer"
        assert entity["acceptedAnswer"]["text"]

    # HTML must contain h3 tags
    assert "<h3>" in captured["html"]
    assert "<p>" in captured["html"]


def test_publish_wordpress_admin_gated(monkeypatch):
    """Sales role cannot call POST /faq/publish-wordpress."""
    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "admin")
    monkeypatch.setenv("WP_APP_PWD", "test-password")

    c = _sales_client()
    r = c.post("/faq/publish-wordpress", headers=AUTH)
    assert r.status_code == 403, r.text


def test_publish_wordpress_no_answered_entries(monkeypatch):
    """Returns 422 when there are no answered FAQ entries."""
    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "admin")
    monkeypatch.setenv("WP_APP_PWD", "test-password")

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()

    c = _admin_client()
    r = c.post("/faq/publish-wordpress", headers=AUTH)
    assert r.status_code == 422, r.text
    assert "No answered" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Batch cap tests
# ---------------------------------------------------------------------------

def test_mine_clamps_to_max(monkeypatch):
    """POST /faq/mine with limit > MINE_MAX is silently clamped to MINE_MAX."""
    import api.routes.faq as faq_mod
    from api.routes.faq import MINE_MAX
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    # We only care that the server accepts the call (no 422) and clamps internally.
    # With only 3 nodes in the DB the response mined count will be <= 3 regardless,
    # but the important thing is the server doesn't raise on an oversized limit.
    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()

    c = _admin_client()
    r = c.post("/faq/mine", json={"limit": MINE_MAX + 9999}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    # mined is ≤ actual nodes in DB (3), not equal to the oversized limit
    assert data["mined"] <= 3


def test_answer_batch_clamps_to_max(monkeypatch):
    """POST /faq/answer-batch with limit > ANSWER_BATCH_MAX is silently clamped."""
    import api.routes.faq as faq_mod
    from api.routes.faq import ANSWER_BATCH_MAX
    monkeypatch.setattr(faq_mod, "_rephrase_via_llm", _fake_rephrase)

    with SessionLocal() as db:
        db.query(FaqEntry).delete()
        db.commit()
    c = _admin_client()
    c.post("/faq/mine", json={"limit": 200}, headers=AUTH)

    import app.answer as answer_mod
    monkeypatch.setattr(answer_mod, "ask", _fake_ask)

    r = c.post("/faq/answer-batch", json={"limit": ANSWER_BATCH_MAX + 9999}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["answered"] <= 3  # only 3 nodes in test DB


# ---------------------------------------------------------------------------
# GET /faq/estimate
# ---------------------------------------------------------------------------

def test_estimate_returns_cost_fields():
    """GET /faq/estimate?count=10 returns all expected fields with positive costs."""
    c = _admin_client()
    r = c.get("/faq/estimate?count=10", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 10
    assert "mine_cost_usd" in data
    assert "answer_cost_usd" in data
    assert "model" in data
    assert "note" in data
    assert "caps" in data
    assert data["mine_cost_usd"] > 0
    assert data["answer_cost_usd"] > 0
    assert data["caps"]["mine_max"] > 0
    assert data["caps"]["answer_batch_max"] > 0


def test_estimate_scales_with_count():
    """Cost for count=100 is proportionally higher than count=10 (linear scaling).

    We verify monotonicity and that the ratio is between 9x and 11x (accounts for
    round(n, 4) rounding artifacts at small values).
    """
    c = _admin_client()
    r10 = c.get("/faq/estimate?count=10", headers=AUTH).json()
    r100 = c.get("/faq/estimate?count=100", headers=AUTH).json()
    assert r100["mine_cost_usd"] > r10["mine_cost_usd"]
    assert r100["answer_cost_usd"] > r10["answer_cost_usd"]
    mine_ratio = r100["mine_cost_usd"] / r10["mine_cost_usd"]
    answer_ratio = r100["answer_cost_usd"] / r10["answer_cost_usd"]
    assert 9 <= mine_ratio <= 11, f"mine ratio {mine_ratio} not ~10x"
    assert 9 <= answer_ratio <= 11, f"answer ratio {answer_ratio} not ~10x"


def test_estimate_sales_allowed():
    """Sales role can GET /faq/estimate (article_read)."""
    c = _sales_client()
    r = c.get("/faq/estimate?count=5", headers=AUTH)
    assert r.status_code == 200, r.text


def test_estimate_requires_auth():
    """GET /faq/estimate without a token returns 401."""
    c = _admin_client()
    r = c.get("/faq/estimate?count=5")
    assert r.status_code == 401, r.text


def test_estimate_requires_count():
    """GET /faq/estimate without count param returns 422."""
    c = _admin_client()
    r = c.get("/faq/estimate", headers=AUTH)
    assert r.status_code == 422, r.text
