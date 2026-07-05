"""Tests for jobs/aggregate_topics.py and the aggregated GET /topics endpoint.

embed() is monkeypatched to return deterministic vectors that force known
clusters — no live embedding backend is needed.

Vector layout (4-dim for simplicity):
  "roof leak"    → [1, 0, 0, 0]  ─┐ similar (dot=1.0 ≥ 0.82)
  "roof leaks"   → [1, 0, 0, 0]  ─┤ → cluster A: "roof leaks / roof leak"
  "leaking roof" → [0.9, 0.1, 0, 0] normalised ─┘ (dot≈0.99 ≥ 0.82)
  "metal roof"   → [0, 1, 0, 0]  ─┐ similar
  "metal roofing"→ [0, 1, 0, 0]  ─┘ → cluster B
  "flat roof"    → [0, 0, 1, 0]  ─── cluster C (alone)

After L2-normalisation by the job, cosine sims are dot products.
"leaking roof" after normalisation = [0.9/√0.82, 0.1/√0.82, 0, 0] ≈ [0.994, 0.110, 0, 0]
dot with [1,0,0,0] ≈ 0.994 ≥ 0.82 → merges with cluster A.
"""
import math
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.topics import router
from app.models import (
    AggregatedTopic,
    GraphNode,
    SessionLocal,
    Video,
    init_db,
)


# ---------------------------------------------------------------------------
# Deterministic fake embeddings
# ---------------------------------------------------------------------------

_LABEL_VECS = {
    "roof leak":     [1.0, 0.0, 0.0, 0.0],
    "roof leaks":    [1.0, 0.0, 0.0, 0.0],
    "leaking roof":  [0.9, 0.1, 0.0, 0.0],  # after normalisation ≈ [0.994, 0.110, …]
    "metal roof":    [0.0, 1.0, 0.0, 0.0],
    "metal roofing": [0.0, 1.0, 0.0, 0.0],
    "flat roof":     [0.0, 0.0, 1.0, 0.0],
}


def _fake_embed(texts):
    """Return deterministic 4-dim vectors for known labels; unit vector for unknowns."""
    vecs = []
    for t in texts:
        key = t.strip().lower()
        if key in _LABEL_VECS:
            vecs.append(_LABEL_VECS[key])
        else:
            vecs.append([1.0, 0.0, 0.0, 0.0])
    return vecs


# ---------------------------------------------------------------------------
# DB setup — isolated SQLite from conftest, seeded once per module
# ---------------------------------------------------------------------------

def setup_module(module):
    init_db()
    with SessionLocal() as db:
        # Wipe any leftovers from other test modules
        db.query(AggregatedTopic).delete()
        db.query(GraphNode).filter(GraphNode.kind == "topics").delete()
        db.query(Video).delete()

        # Videos
        db.add(Video(id="v1", title="Roof Leak Basics",       duration=300.0))
        db.add(Video(id="v2", title="Roof Leaks Explained",   duration=600.0))
        db.add(Video(id="v3", title="Metal Roof Guide",        duration=450.0))
        db.add(Video(id="v4", title="Flat Roof Essentials",    duration=900.0))
        db.add(Video(id="v5", title="Another Leak Video",      duration=200.0))

        # Graph nodes
        # Cluster A: "roof leak" family — 3 distinct labels across v1,v2,v5
        db.add(GraphNode(video_id="v1", kind="topics", label="roof leak",    start=10.0, version="1"))
        db.add(GraphNode(video_id="v2", kind="topics", label="roof leaks",   start=20.0, version="1"))
        db.add(GraphNode(video_id="v2", kind="topics", label="roof leaks",   start=30.0, version="1"))  # dup
        db.add(GraphNode(video_id="v5", kind="topics", label="leaking roof", start=5.0,  version="1"))
        # Cluster B: metal roof — 1 label, 1 video
        db.add(GraphNode(video_id="v3", kind="topics", label="metal roof",    start=0.0,  version="1"))
        db.add(GraphNode(video_id="v3", kind="topics", label="metal roofing", start=15.0, version="1"))
        # Cluster C: flat roof — 1 label, 1 video
        db.add(GraphNode(video_id="v4", kind="topics", label="flat roof",     start=60.0, version="1"))

        db.commit()


# ---------------------------------------------------------------------------
# Fixture: patch embed() for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_embed(monkeypatch):
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "embed", _fake_embed)
    # Also patch via jobs.aggregate_topics in case it imported embed directly
    import jobs.aggregate_topics as agg_mod
    # The job calls app.llm.embed through _embed_in_batches; patching the module
    # attribute is sufficient because _embed_in_batches does `from app.llm import embed`.
    # Patch the reference inside the job module too to be safe.
    monkeypatch.setattr(agg_mod, "_embed_in_batches",
                        lambda texts, **kw: __import__("numpy").array(
                            [_fake_embed([t])[0] for t in texts], dtype="float32"
                        ))


# ---------------------------------------------------------------------------
# run() unit tests
# ---------------------------------------------------------------------------

def test_run_aggregates_near_duplicate_labels():
    """roof leak / roof leaks / leaking roof → 1 cluster."""
    from jobs.aggregate_topics import run
    result = run()
    assert result["num_clusters"] <= result["num_raw_labels"]

    leak_clusters = [
        c for c in result["clusters"]
        if "leak" in c["canonical_label"].lower() or "leaking" in c["canonical_label"].lower()
    ]
    assert len(leak_clusters) == 1, (
        f"Expected 1 leak cluster, got {len(leak_clusters)}: "
        f"{[c['canonical_label'] for c in leak_clusters]}"
    )


def test_run_cluster_num_videos():
    """The leak cluster must span exactly 3 distinct videos (v1, v2, v5)."""
    from jobs.aggregate_topics import run
    result = run()
    leak_cluster = next(
        c for c in result["clusters"]
        if "leak" in c["canonical_label"].lower() or "leaking" in c["canonical_label"].lower()
    )
    assert leak_cluster["num_videos"] == 3, leak_cluster
    assert set(leak_cluster["video_ids"]) == {"v1", "v2", "v5"}


def test_run_cluster_total_seconds():
    """total_seconds for the leak cluster = 300+600+200 = 1100."""
    from jobs.aggregate_topics import run
    result = run()
    leak_cluster = next(
        c for c in result["clusters"]
        if "leak" in c["canonical_label"].lower() or "leaking" in c["canonical_label"].lower()
    )
    assert abs(leak_cluster["total_seconds"] - 1100.0) < 0.01, leak_cluster


def test_run_cluster_node_ids_populated():
    """node_ids list is non-empty for every cluster."""
    from jobs.aggregate_topics import run
    result = run()
    for cluster in result["clusters"]:
        assert len(cluster["node_ids"]) > 0, f"Empty node_ids on cluster {cluster['canonical_label']!r}"


def test_run_produces_correct_cluster_count():
    """3 semantic groups → 3 clusters total."""
    from jobs.aggregate_topics import run
    result = run()
    assert result["num_clusters"] == 3, (
        f"Expected 3 clusters, got {result['num_clusters']}: "
        f"{[c['canonical_label'] for c in result['clusters']]}"
    )


def test_run_writes_to_db():
    """After run(), aggregated_topics table has exactly 3 rows."""
    from jobs.aggregate_topics import run
    run()
    with SessionLocal() as db:
        count = db.query(AggregatedTopic).count()
    assert count == 3, f"Expected 3 aggregated_topics rows, got {count}"


def test_run_idempotent():
    """Running run() twice keeps exactly 3 rows (clear + rebuild, no duplicates)."""
    from jobs.aggregate_topics import run
    run()
    run()
    with SessionLocal() as db:
        count = db.query(AggregatedTopic).count()
    assert count == 3


def test_run_version_stamped():
    """Every aggregated_topics row has a non-empty version string."""
    from jobs.aggregate_topics import run
    run()
    with SessionLocal() as db:
        rows = db.query(AggregatedTopic).all()
    for row in rows:
        assert row.version and len(row.version) > 0


# ---------------------------------------------------------------------------
# API tests — GET /topics reads from aggregated_topics
# ---------------------------------------------------------------------------

def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(_make_app())


AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture(autouse=True)
def seed_aggregates(patch_embed):
    """Ensure aggregated_topics is populated before each API test."""
    from jobs.aggregate_topics import run
    run()


def test_get_topics_returns_total_and_items():
    """GET /topics returns {total, items} envelope."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert "items" in body
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_get_topics_item_shape():
    """Each item has label, count, num_videos, total_content_length, sample."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    for item in r.json()["items"]:
        assert "label" in item
        assert "count" in item
        assert "num_videos" in item
        assert "total_content_length" in item
        assert "sample" in item
        assert "video_id" in item["sample"]
        assert "t" in item["sample"]


def test_get_topics_sort_by_videos():
    """Default sort (sort=videos): items ordered by num_videos desc."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    items = r.json()["items"]
    counts = [i["num_videos"] for i in items]
    assert counts == sorted(counts, reverse=True)


def test_get_topics_sort_by_length():
    """sort=length: items ordered by total_content_length desc."""
    c = _admin_client()
    r = c.get("/topics", params={"sort": "length"}, headers=AUTH)
    items = r.json()["items"]
    lengths = [i["total_content_length"] for i in items]
    assert lengths == sorted(lengths, reverse=True)


def test_get_topics_sort_by_alpha():
    """sort=alpha: items ordered alphabetically by label."""
    c = _admin_client()
    r = c.get("/topics", params={"sort": "alpha"}, headers=AUTH)
    items = r.json()["items"]
    labels = [i["label"].lower() for i in items]
    assert labels == sorted(labels)


def test_get_topics_pagination_limit():
    """limit=1 returns 1 item, total still 3."""
    c = _admin_client()
    r = c.get("/topics", params={"limit": 1}, headers=AUTH)
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1


def test_get_topics_pagination_offset():
    """offset=1 skips the first item; limit=1 returns the second."""
    c = _admin_client()
    r_all = c.get("/topics", headers=AUTH)
    all_labels = [i["label"] for i in r_all.json()["items"]]

    r = c.get("/topics", params={"offset": 1, "limit": 1}, headers=AUTH)
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["items"][0]["label"] == all_labels[1]


def test_get_topics_no_cap():
    """All 3 topics are returned without an artificial 200-item cap."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 3


def test_get_topics_leak_cluster_correct_metrics():
    """The leak cluster shows num_videos=3 and total_content_length=1100."""
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    items = r.json()["items"]
    leak = next(
        (i for i in items
         if "leak" in i["label"].lower() or "leaking" in i["label"].lower()),
        None,
    )
    assert leak is not None, f"No leak cluster in {[i['label'] for i in items]}"
    assert leak["num_videos"] == 3
    assert abs(leak["total_content_length"] - 1100.0) < 0.01


def test_get_topics_videos_from_aggregate():
    """GET /topics/videos?label=<canonical> returns member videos from aggregate."""
    # First get canonical label for the leak cluster
    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    leak = next(
        i for i in r.json()["items"]
        if "leak" in i["label"].lower() or "leaking" in i["label"].lower()
    )
    canonical = leak["label"]

    r2 = c.get("/topics/videos", params={"label": canonical}, headers=AUTH)
    assert r2.status_code == 200, r2.text
    videos = r2.json()
    assert len(videos) == 3
    vid_ids = {v["video_id"] for v in videos}
    assert vid_ids == {"v1", "v2", "v5"}
    for v in videos:
        assert "title" in v
        assert "duration" in v
        assert "start" in v


def test_get_topics_fallback_when_table_empty():
    """When aggregated_topics is empty, GET /topics falls back to live grouping."""
    with SessionLocal() as db:
        db.query(AggregatedTopic).delete()
        db.commit()

    c = _admin_client()
    r = c.get("/topics", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert "items" in body
    # Should have the 3 distinct exact-match labels from the seeded data
    assert body["total"] >= 3
