"""Behavioral tests for GET /topic-graph."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.topic_graph import router
from app.models import Article, FaqEntry, GraphNode, SessionLocal, Video, init_db


def _client(role: str = "admin") -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "a@x.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    init_db()
    return TestClient(app)


AUTH = {"Authorization": "Bearer tok"}


def _seed():
    init_db()
    with SessionLocal() as db:
        if not db.get(Video, "v-tile"):
            db.add(Video(id="v-tile", title="Tile how-to", duration=100,
                         views=1000, likes=20, comments=10))
        if not db.get(Video, "v-storm"):
            db.add(Video(id="v-storm", title="Storm", duration=40,
                         views=10, likes=0, comments=0))
        if not db.query(GraphNode).filter(GraphNode.video_id == "v-tile").first():
            db.add(GraphNode(video_id="v-tile", kind="topics",
                             label="Tile foam method", start=1.0, version="v1"))
            db.add(GraphNode(video_id="v-storm", kind="topics",
                             label="Hurricane prep", start=2.0, version="v1"))
            db.add(GraphNode(video_id="v-tile", kind="objections",
                             label="How do I walk on a tile roof", start=3.0, version="v1"))
        if not db.get(Article, "tile-foam-method"):
            db.add(Article(
                slug="tile-foam-method", title="Tile Foam Method",
                role="pillar", status="published",
                focus_keyword="tile foam method", tenant_id=1,
            ))
        if not db.query(FaqEntry).filter(FaqEntry.video_id == "v-tile").first():
            node = db.query(GraphNode).filter(
                GraphNode.label == "How do I walk on a tile roof").first()
            db.add(FaqEntry(
                question="How do I walk on a tile roof?",
                answer="Walk on the battens.",
                source_kind="objections",
                source_node_id=node.id if node else 9999,
                video_id="v-tile", start=3.0, status="answered", tenant_id=1,
            ))
        db.commit()


def test_sales_can_read_article_graph():
    _seed()
    c = _client("sales")
    r = c.get("/topic-graph?kind=articles&published=all", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "articles"
    ids = {g["id"] for g in body["genres"]}
    assert "tile" in ids
    tile = next(g for g in body["genres"] if g["id"] == "tile")
    assert tile["n_published"] >= 1
    assert "legend" in body
    assert "diversity" in body


def test_unpublished_filter_drops_covered_tile():
    _seed()
    c = _client("admin")
    r = c.get("/topic-graph?kind=articles&published=no", headers=AUTH)
    assert r.status_code == 200
    tile = next((g for g in r.json()["genres"] if g["id"] == "tile"), None)
    if tile:
        assert tile["n_published"] == 0


def test_faq_graph_includes_answered():
    _seed()
    c = _client("admin")
    r = c.get("/topic-graph?kind=faqs&published=all", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "faqs"
    assert body["totals"]["published"] >= 1


def test_social_brief_returns_cut_and_film_lists():
    _seed()
    c = _client("admin")
    r = c.get("/topic-graph/social-brief", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "cut_for_social" in body
    assert "film_next" in body
    assert "this_week" in body
    assert isinstance(body["cut_for_social"], list)
    assert isinstance(body["film_next"], list)
    assert isinstance(body["this_week"], list)
    assert len(body["this_week"]) <= 5


def test_genre_catalog_endpoint():
    c = _client("sales")
    r = c.get("/topic-graph/genres", headers=AUTH)
    assert r.status_code == 200
    ids = {g["id"] for g in r.json()}
    assert "tile" in ids and "weather" in ids


def test_unauthenticated_is_rejected():
    c = _client("admin")
    r = c.get("/topic-graph")
    assert r.status_code in (401, 403)


def test_competitor_scan_fails_soft_without_serper(monkeypatch):
    _seed()
    c = _client("admin")

    def _boom(_query: str):
        raise RuntimeError("SERPER_API_KEY env var is not set")

    monkeypatch.setattr("adapters.serper.fetch_serp", _boom)
    r = c.post("/topic-graph/competitor-scan", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["queries"] == []
    assert "SERPER" in (body.get("error") or "")


def test_competitor_scan_ranks_gaps_from_mocked_serp(monkeypatch):
    _seed()
    c = _client("admin")

    def _serp(query: str):
        if "hurricane" in query.lower():
            return {
                "organic": [{"title": "This Old House", "link": "https://thisoldhouse.com/hurricane"}],
                "peopleAlsoAsk": [{"question": "Does insurance cover a hurricane leak?"}],
            }
        return {
            "organic": [{"title": "Perkins", "link": "https://perkinsroofing.com/hoa-metal"}],
            "peopleAlsoAsk": [],
        }

    monkeypatch.setattr("adapters.serper.fetch_serp", _serp)
    r = c.post("/topic-graph/competitor-scan", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["queries"]) >= 1
    assert body["queries"][0]["action"] == "film"
    assert body["queries"][0]["we_rank"] is False
    assert body.get("inbox_added", 0) >= 1


def test_engagement_inbox_lists_captured_paa(monkeypatch):
    _seed()
    c = _client("admin")

    def _serp(query: str):
        return {
            "organic": [{"title": "Other", "link": "https://example.com/x"}],
            "peopleAlsoAsk": [{"question": "Does insurance cover a hurricane leak?"}],
        }

    monkeypatch.setattr("adapters.serper.fetch_serp", _serp)
    c.post("/topic-graph/competitor-scan", headers=AUTH)
    r = c.get("/topic-graph/engagement-inbox", headers=AUTH)
    assert r.status_code == 200
    texts = [i["text"] for i in r.json()["items"]]
    assert any("hurricane" in t.lower() for t in texts)
