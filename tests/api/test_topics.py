"""Behavioral tests for api/routes/topics.py.

Uses an isolated FastAPI app (not the real api.app) so the router is tested in
isolation without coupling to the full app's middleware. The conftest.py sets
DB_URL to a temp SQLite file before any import, so SessionLocal() is already isolated.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.topics import router
from app.models import GraphNode, Article, SessionLocal, init_db


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
    # Seed a couple of content_graph topic rows so GET /topics returns data
    with SessionLocal() as db:
        # 3 rows for "flat roofing" across 2 distinct videos
        db.add(GraphNode(video_id="vid1", kind="topics", label="flat roofing",
                         detail="", start=30.0, version="1"))
        db.add(GraphNode(video_id="vid2", kind="topics", label="flat roofing",
                         detail="", start=120.0, version="1"))
        db.add(GraphNode(video_id="vid2", kind="topics", label="Flat Roofing",
                         detail="", start=200.0, version="1"))
        # 1 row for "shingle repair" in 1 video
        db.add(GraphNode(video_id="vid1", kind="topics", label="shingle repair",
                         detail="", start=60.0, version="1"))
        # A non-topic row that should NOT appear in results
        db.add(GraphNode(video_id="vid3", kind="claims", label="should not appear",
                         detail="", start=0.0, version="1"))
        db.commit()


# ---------------------------------------------------------------------------
# GET /topics
# ---------------------------------------------------------------------------

def test_get_topics_returns_list_shape():
    """GET /topics returns a list of {label, count, sample} dicts."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    # Each item must have the required keys
    for item in items:
        assert "label" in item
        assert "count" in item
        assert "sample" in item
        assert "video_id" in item["sample"]
        assert "t" in item["sample"]


def test_get_topics_groups_and_dedupes():
    """flat roofing spans 2 videos → count=2; shingle repair is 1 video → count=1."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    # Build a lookup by normalized label
    by_label = {item["label"].lower(): item for item in items}
    assert "flat roofing" in by_label
    assert by_label["flat roofing"]["count"] == 2
    assert "shingle repair" in by_label
    assert by_label["shingle repair"]["count"] == 1


def test_get_topics_excludes_non_topic_kinds():
    """kind='claims' rows must not appear in the topic list."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    items = r.json()
    labels = [i["label"].lower() for i in items]
    assert "should not appear" not in labels


def test_get_topics_ordered_by_count_desc():
    """Topics are ordered by count descending (flat roofing before shingle repair)."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    items = r.json()
    counts = [i["count"] for i in items]
    assert counts == sorted(counts, reverse=True)


def test_get_topics_sales_allowed():
    """sales role has article_read → 200."""
    c = _sales_client()
    r = c.get("/topics", headers=AUTH)
    assert r.status_code == 200, r.text


def test_get_topics_unauthenticated():
    """Missing bearer → 401."""
    c = _admin_client()
    r = c.get("/topics")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /topics/generate-article
# ---------------------------------------------------------------------------

def test_generate_article_admin_creates_draft():
    """Admin can generate a cluster article draft — returns slug, title, role, status."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "metal roof installation"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["slug"] == "metal-roof-installation"
    assert data["title"] == "Metal Roof Installation"
    assert data["role"] == "cluster"
    assert data["status"] == "draft"


def test_generate_article_persists_in_db():
    """Article row exists in DB after POST."""
    c = _admin_client()
    c.post("/topics/generate-article",
           json={"topic": "roof flashing repair"},
           headers=AUTH)
    with SessionLocal() as db:
        a = db.get(Article, "roof-flashing-repair")
    assert a is not None
    assert a.role == "cluster"
    assert a.status == "draft"
    assert a.content_md is not None and len(a.content_md) > 0


def test_generate_article_with_pillar_slug():
    """pillar_slug is stored on the created article."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "gutter replacement", "pillar_slug": "roofing-guide"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        a = db.get(Article, "gutter-replacement")
    assert a is not None
    assert a.pillar_slug == "roofing-guide"


def test_generate_article_idempotent():
    """POSTing the same topic twice returns the existing draft (no 409)."""
    c = _admin_client()
    r1 = c.post("/topics/generate-article",
                json={"topic": "ice dam prevention"},
                headers=AUTH)
    assert r1.status_code == 201, r1.text
    r2 = c.post("/topics/generate-article",
                json={"topic": "ice dam prevention"},
                headers=AUTH)
    # Second call returns the existing article — still 201
    assert r2.status_code == 201, r2.text
    assert r1.json()["slug"] == r2.json()["slug"]


def test_generate_article_sales_gets_403():
    """sales role lacks manage_articles → 403."""
    c = _sales_client()
    r = c.post("/topics/generate-article",
               json={"topic": "sales forbidden topic"},
               headers=AUTH)
    assert r.status_code == 403, r.text


def test_generate_article_unauthenticated():
    """Missing bearer → 401."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "anon topic"})
    assert r.status_code == 401
