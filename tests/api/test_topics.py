"""Behavioral tests for api/routes/topics.py.

Uses an isolated FastAPI app (not the real api.app) so the router is tested in
isolation without coupling to the full app's middleware. The conftest.py sets
DB_URL to a temp SQLite file before any import, so SessionLocal() is already isolated.

LLM calls are monkeypatched via ``_FAKE_CONTENT`` so tests never hit Vertex AI.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.topics import router
from app.models import GraphNode, Article, ScheduledContent, SessionLocal, Video, init_db


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

# ---------------------------------------------------------------------------
# Fake content generator — injected via monkeypatch to avoid live LLM calls
# ---------------------------------------------------------------------------

def _fake_generate_article_content(keyword: str, ctx: dict, **kwargs) -> dict:
    """Return deterministic finished content without calling the LLM."""
    title = f"Real Content: {keyword.title()}"
    return {
        "title": title,
        "slug": keyword.lower().replace(" ", "-"),
        "meta": f"Expert roofing advice on {keyword} from Perkins Roofing.",
        "content_md": (
            f"# {title}\n\n"
            f"Perkins Roofing has extensive experience with {keyword}. "
            f"This article covers what you need to know about {keyword} — "
            f"costs, timelines, and when to call a professional.\n\n"
            f"## Overview\n\nThis is finished content about {keyword}.\n\n"
            f"## Key Considerations\n\n"
            f"- Factor 1 for {keyword}\n"
            f"- Factor 2 for {keyword}\n"
            f"- Factor 3 for {keyword}\n\n"
            f"## FAQ\n\nCommon questions about {keyword} are answered below."
        ),
        "faq_json": [
            {"q": f"How much does {keyword} cost?", "a": "Costs vary by scope and materials."},
            {"q": f"How long does {keyword} take?", "a": "Typically 1–3 days for most jobs."},
        ],
    }


def _fake_refine_article_content(fields: dict, keyword: str, **kwargs) -> dict:
    """Return fields unchanged — simulates a successful no-op refine pass."""
    return fields


def _fake_llm_subtopics(topic: str, existing: list, needed: int) -> list[str]:
    """Return deterministic LLM-generated subtopic titles without calling the real LLM."""
    base = [
        f"{topic} cost guide",
        f"{topic} installation tips",
        f"{topic} maintenance schedule",
        f"{topic} repair vs replace",
        f"{topic} materials comparison",
        f"{topic} contractor selection",
    ]
    results = []
    existing_lower = {e.lower() for e in existing}
    for t in base:
        if t.lower() not in existing_lower and len(results) < needed:
            results.append(t)
    return results


@pytest.fixture(autouse=True)
def patch_content_generator(monkeypatch):
    """Monkeypatch generate_article_content, refine_article_content, and _llm_subtopics so no test hits the live LLM."""
    import jobs.article_job as job_mod
    monkeypatch.setattr(job_mod, "generate_article_content", _fake_generate_article_content)
    monkeypatch.setattr(job_mod, "refine_article_content", _fake_refine_article_content)
    import api.routes.topics as topics_mod
    monkeypatch.setattr(topics_mod, "_llm_subtopics", _fake_llm_subtopics)


def setup_module(module):
    init_db()
    # Seed a couple of content_graph topic rows so GET /topics returns data
    with SessionLocal() as db:
        # Seed Video rows so /topics/videos can join to them
        db.add(Video(id="vid1", title="Flat Roof Basics", duration=620.0))
        db.add(Video(id="vid2", title="Advanced Flat Roofing Techniques", duration=940.0))

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

def _items(r):
    """Extract the items list from a GET /topics response (supports both shapes)."""
    body = r.json()
    if isinstance(body, dict) and "items" in body:
        return body["items"]
    return body  # fallback for any unexpected shape


def test_get_topics_returns_list_shape():
    """GET /topics returns {total, items} where items are {label, count, sample} dicts."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert "items" in body
    items = body["items"]
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
    items = _items(r)
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
    items = _items(r)
    labels = [i["label"].lower() for i in items]
    assert "should not appear" not in labels


def test_get_topics_ordered_by_count_desc():
    """Topics are ordered by count descending (flat roofing before shingle repair)."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    items = _items(r)
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
# POST /topics/generate-article  (cluster generation)
# ---------------------------------------------------------------------------

def test_generate_cluster_creates_pillar_and_clusters():
    """Admin generates a cluster: 1 pillar + >=4 cluster articles (5-7 total), all sharing pillar_slug."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "metal roof installation"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    # Response shape
    assert data["pillar_slug"] == "metal-roof-installation"
    assert data["pillar"]["slug"] == "metal-roof-installation"
    assert isinstance(data["clusters"], list)
    # Must produce at least 4 cluster articles (5-7 total including pillar)
    assert len(data["clusters"]) >= 4, (
        f"Expected >=4 cluster articles, got {len(data['clusters'])}: {[c['title'] for c in data['clusters']]}"
    )
    assert data["count"] == 1 + len(data["clusters"])
    assert 5 <= data["count"] <= 7, f"Expected 5-7 total articles, got {data['count']}"


def test_generate_cluster_pillar_row_in_db():
    """Pillar Article row has role='pillar', pillar_slug=its own slug, status='scheduled', real content_md (no TODO)."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "flat roof repair"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    pillar_slug = r.json()["pillar_slug"]
    with SessionLocal() as db:
        pillar = db.get(Article, pillar_slug)
    assert pillar is not None
    assert pillar.role == "pillar"
    assert pillar.pillar_slug == pillar_slug
    assert pillar.status == "scheduled"
    assert pillar.publish_at is not None, "pillar must have publish_at set"
    assert pillar.content_md is not None and len(pillar.content_md) > 0
    assert "TODO" not in pillar.content_md, "pillar content_md must not contain TODO placeholders"


def test_generate_cluster_cluster_rows_in_db():
    """All cluster Article rows have role='cluster', status='scheduled', correct pillar_slug, real content."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "shingle replacement"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    pillar_slug = data["pillar_slug"]
    cluster_slugs = {cl["slug"] for cl in data["clusters"]}
    assert len(cluster_slugs) >= 1

    assert len(cluster_slugs) >= 4, (
        f"Expected >=4 cluster articles (5-7 total), got {len(cluster_slugs)}"
    )

    with SessionLocal() as db:
        for slug in cluster_slugs:
            a = db.get(Article, slug)
            assert a is not None, f"cluster article {slug!r} not found in DB"
            assert a.role == "cluster"
            assert a.pillar_slug == pillar_slug
            assert a.status == "scheduled"
            assert a.publish_at is not None, f"cluster {slug!r} must have publish_at set"
            assert a.content_md is not None and len(a.content_md) > 0
            assert "TODO" not in a.content_md, f"cluster {slug!r} content_md must not contain TODO placeholders"


def test_generate_cluster_no_todo_placeholders():
    """content_md for both pillar and all clusters must contain NO HTML/markdown TODO comments."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "gutter cleaning"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    all_slugs = [data["pillar"]["slug"]] + [cl["slug"] for cl in data["clusters"]]

    with SessionLocal() as db:
        for slug in all_slugs:
            a = db.get(Article, slug)
            assert a is not None
            assert a.content_md is not None and len(a.content_md) > 10, \
                f"{slug!r} content_md is empty or near-empty"
            assert "TODO" not in a.content_md, \
                f"{slug!r} content_md contains a TODO placeholder"


def test_generate_cluster_idempotent():
    """POSTing the same topic twice returns the existing cluster (no duplicates, no 409)."""
    c = _admin_client()
    r1 = c.post("/topics/generate-article",
                json={"topic": "ice dam prevention"},
                headers=AUTH)
    assert r1.status_code == 201, r1.text
    r2 = c.post("/topics/generate-article",
                json={"topic": "ice dam prevention"},
                headers=AUTH)
    assert r2.status_code == 201, r2.text
    assert r1.json()["pillar_slug"] == r2.json()["pillar_slug"]


def test_generate_cluster_sales_gets_403():
    """sales role lacks manage_articles → 403."""
    c = _sales_client()
    r = c.post("/topics/generate-article",
               json={"topic": "sales forbidden topic"},
               headers=AUTH)
    assert r.status_code == 403, r.text


def test_generate_cluster_unauthenticated():
    """Missing bearer → 401."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "anon topic"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Auto-scheduling assertions
# ---------------------------------------------------------------------------

def test_generate_cluster_creates_scheduled_content_rows():
    """POST /topics/generate-article creates ScheduledContent rows for pillar + clusters."""
    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "ridge cap shingles"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    pillar_slug = data["pillar_slug"]
    cluster_slugs = [cl["slug"] for cl in data["clusters"]]
    all_slugs = [pillar_slug] + cluster_slugs

    with SessionLocal() as db:
        sched_rows = (
            db.query(ScheduledContent)
            .filter(ScheduledContent.ref_id.in_(all_slugs))
            .all()
        )
        sched_ref_ids = {r.ref_id for r in sched_rows}
        for slug in all_slugs:
            assert slug in sched_ref_ids, f"No ScheduledContent row for slug={slug!r}"
        for row in sched_rows:
            assert row.kind == "article"
            assert row.target == "wordpress"
            assert row.status == "scheduled"
            assert row.publish_at is not None


def test_generate_cluster_publish_dates_staggered():
    """Pillar gets base_date; each cluster article gets +1 day from the previous."""
    from datetime import date, timedelta

    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "soffit and fascia repair"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    pillar_slug = data["pillar_slug"]
    cluster_slugs = [cl["slug"] for cl in data["clusters"]]

    with SessionLocal() as db:
        pillar = db.get(Article, pillar_slug)
        assert pillar.publish_at is not None
        pillar_date = pillar.publish_at.date() if hasattr(pillar.publish_at, "date") else pillar.publish_at

        prev_date = pillar_date
        for slug in cluster_slugs:
            a = db.get(Article, slug)
            assert a is not None
            assert a.publish_at is not None
            a_date = a.publish_at.date() if hasattr(a.publish_at, "date") else a.publish_at
            assert a_date == prev_date + timedelta(days=1), (
                f"Expected cluster {slug!r} on {prev_date + timedelta(days=1)}, got {a_date}"
            )
            prev_date = a_date


def test_generate_cluster_base_date_after_existing_scheduled():
    """When a ScheduledContent row already exists, new cluster base = day after that max date."""
    from datetime import date, datetime, timedelta

    # Seed a scheduled content row with a known future date
    seed_date = datetime(2030, 6, 15, 0, 0, 0)
    with SessionLocal() as db:
        db.add(ScheduledContent(
            kind="article",
            ref_id="existing-article",
            publish_at=seed_date,
            status="scheduled",
            target="wordpress",
        ))
        db.commit()

    c = _admin_client()
    r = c.post("/topics/generate-article",
               json={"topic": "drip edge installation"},
               headers=AUTH)
    assert r.status_code == 201, r.text
    data = r.json()
    pillar_slug = data["pillar_slug"]

    expected_base = date(2030, 6, 16)  # day after 2030-06-15

    with SessionLocal() as db:
        pillar = db.get(Article, pillar_slug)
        assert pillar.publish_at is not None
        pillar_date = pillar.publish_at.date() if hasattr(pillar.publish_at, "date") else pillar.publish_at
        assert pillar_date == expected_base, (
            f"Expected pillar on {expected_base}, got {pillar_date}"
        )


# ---------------------------------------------------------------------------
# GET /topics/videos
# ---------------------------------------------------------------------------

def test_topics_videos_returns_shape():
    """GET /topics/videos?label=flat+roofing returns [{video_id, title, duration, start}]."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "flat roofing"}, headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    for item in items:
        assert "video_id" in item
        assert "title" in item
        assert "duration" in item
        assert "start" in item


def test_topics_videos_returns_titles_not_ids():
    """Titles come from the Video table — no raw IDs in the title field."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "flat roofing"}, headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2, f"Expected 2 distinct videos for 'flat roofing', got {len(items)}"
    titles = {i["title"] for i in items}
    assert "Flat Roof Basics" in titles
    assert "Advanced Flat Roofing Techniques" in titles
    # video_id values must not appear as title values
    video_ids = {i["video_id"] for i in items}
    assert not titles.intersection(video_ids), "title field must not expose raw video IDs"


def test_topics_videos_returns_duration():
    """Duration matches the seeded Video rows."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "flat roofing"}, headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    by_id = {i["video_id"]: i for i in items}
    assert abs(by_id["vid1"]["duration"] - 620.0) < 0.01
    assert abs(by_id["vid2"]["duration"] - 940.0) < 0.01


def test_topics_videos_earliest_start_per_video():
    """start is the earliest timecode for that video (vid2 has t=120 and t=200 → returns 120)."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "flat roofing"}, headers=AUTH)
    assert r.status_code == 200, r.text
    items = r.json()
    by_id = {i["video_id"]: i for i in items}
    assert by_id["vid2"]["start"] == 120.0


def test_topics_videos_case_insensitive_label():
    """Label matching is case-insensitive: 'Flat Roofing' resolves same as 'flat roofing'."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "Flat Roofing"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_topics_videos_unknown_label_returns_empty():
    """Unknown topic label returns an empty list, not a 404."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "nonexistent topic xyz"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_topics_videos_sales_allowed():
    """sales role has article_read → GET /topics/videos returns 200."""
    c = _sales_client()
    r = c.get("/topics/videos", params={"label": "flat roofing"}, headers=AUTH)
    assert r.status_code == 200, r.text


def test_topics_videos_unauthenticated():
    """Missing bearer token → 401."""
    c = _admin_client()
    r = c.get("/topics/videos", params={"label": "flat roofing"})
    assert r.status_code == 401
