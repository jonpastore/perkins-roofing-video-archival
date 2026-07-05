"""Hermetic tests for api/routes/suggestions.py.

Uses a temp SQLite DB (set via DB_URL env before importing app.models) and a fake
token verifier (set via api.auth.set_verifier) — no real Firebase or DB needed.

Seeds a small dataset:
  - 3 videos (vid_a, vid_b, vid_c)
  - Topics: "roof repair" appears for vid_a + vid_b; "gutters" for vid_c
  - One Article referencing vid_a (title "Roof Repair") — so "roof repair" topic is covered
  - One approved MiniSeries for vid_b with no ScheduledContent/SocialPost
  - One objection GraphNode for vid_c (no article)
  - One objection GraphNode for vid_a (video already covered by article -> excluded from faqs)
  - vid_b has a Segment (transcript) but is NOT in any article and NOT in any MiniSeries -> unused
    (vid_b IS in a MiniSeries, so it must not appear in unused_videos)
  - vid_c has a Segment and no article, no MiniSeries -> unused
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set up isolated temp DB before any app.models import
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from api.routes.suggestions import router  # noqa: E402
from app.models import (  # noqa: E402
    Article,
    Base,
    GraphNode,
    MiniSeries,
    Segment,
    ScheduledContent,
    SessionLocal,
    SocialPost,
    Video,
    engine,
)

Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "admin@test.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


ADMIN_HDR = {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all relevant tables between tests."""
    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(ScheduledContent).delete()
        db.query(MiniSeries).delete()
        db.query(GraphNode).delete()
        db.query(Segment).delete()
        db.query(Article).delete()
        db.query(Video).delete()
        db.commit()
    yield


@pytest.fixture()
def seeded():
    """Insert a representative small dataset. Returns a dict of created IDs."""
    with SessionLocal() as db:
        # Videos
        vid_a = Video(id="vid_a", title="Roof Repair Basics")
        vid_b = Video(id="vid_b", title="Gutter Installation")
        vid_c = Video(id="vid_c", title="Shingle Selection")
        db.add_all([vid_a, vid_b, vid_c])

        # Topics: "roof repair" seen in vid_a + vid_b -> count 2
        #         "gutters" seen in vid_c -> count 1
        db.add(GraphNode(video_id="vid_a", kind="topics", label="Roof Repair", start=10.0, version="v1"))
        db.add(GraphNode(video_id="vid_b", kind="topics", label="Roof Repair", start=5.0, version="v1"))
        db.add(GraphNode(video_id="vid_c", kind="topics", label="Gutters", start=20.0, version="v1"))

        # Article covering "Roof Repair" — title matches topic -> topic excluded from article_topics
        # content_md contains vid_a's ID -> vid_a excluded from faqs + unused
        db.add(Article(
            slug="roof-repair",
            title="Roof Repair",
            content_md=f"See video vid_a for details.",
            role="pillar",
            status="published",
        ))

        # Approved MiniSeries for vid_b, no ScheduledContent or SocialPost yet
        ms = MiniSeries(
            video_id="vid_b",
            title="Gutter Install Series",
            parts_json=[{"title": "Part 1", "start": 0.0, "end": 60.0}],
            approved=1,
        )
        db.add(ms)
        db.flush()
        series_id = ms.id

        # Objection for vid_a (covered by article -> should NOT appear in faqs)
        db.add(GraphNode(
            video_id="vid_a", kind="objections",
            label="Isn't roof repair expensive?", detail="", start=30.0, version="v1",
        ))

        # Objection for vid_c (no article -> SHOULD appear in faqs)
        db.add(GraphNode(
            video_id="vid_c", kind="objections",
            label="Do I need a professional?", detail="", start=15.0, version="v1",
        ))

        # Segments: vid_b and vid_c have transcripts
        db.add(Segment(video_id="vid_b", text="Hello", start=0.0, end=5.0, source="youtube_caption"))
        db.add(Segment(video_id="vid_c", text="World", start=0.0, end=5.0, source="youtube_caption"))

        db.commit()
        return {"series_id": series_id}


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

def test_suggestions_401_no_token():
    client = _make_client("admin")
    resp = client.get("/suggestions")
    assert resp.status_code == 401


def test_suggestions_403_sales():
    client = _make_client("sales")
    resp = client.get("/suggestions", headers=ADMIN_HDR)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# article_topics bucket
# ---------------------------------------------------------------------------

def test_article_topics_excludes_covered(seeded):
    """Topics already matching an article title must be excluded."""
    client = _make_client("admin")
    resp = client.get("/suggestions", headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()

    labels = [t["label"].lower() for t in data["article_topics"]]
    assert "roof repair" not in labels   # covered by article


def test_article_topics_includes_uncovered(seeded):
    """Topics without a matching article appear in the bucket."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    labels = [t["label"].lower() for t in data["article_topics"]]
    assert "gutters" in labels


def test_article_topics_has_count_and_sample(seeded):
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    gutters = next(t for t in data["article_topics"] if t["label"].lower() == "gutters")
    assert gutters["count"] >= 1
    assert "video_id" in gutters["sample"]
    assert "t" in gutters["sample"]


def test_article_topics_has_num_videos_and_content_length(seeded):
    """Each article_topics item must include num_videos and total_content_length."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    gutters = next(t for t in data["article_topics"] if t["label"].lower() == "gutters")
    assert "num_videos" in gutters
    assert isinstance(gutters["num_videos"], int)
    assert gutters["num_videos"] >= 1
    assert "total_content_length" in gutters
    assert isinstance(gutters["total_content_length"], int)
    assert gutters["total_content_length"] >= 0


def test_article_topics_sort_by_videos(seeded):
    """?sort=videos should return topics sorted by num_videos descending."""
    client = _make_client("admin")
    data = client.get("/suggestions?sort=videos", headers=ADMIN_HDR).json()
    topics = data["article_topics"]
    # All returned items must have num_videos field
    for t in topics:
        assert "num_videos" in t
    # Check ordering: each item's num_videos >= next item's
    for i in range(len(topics) - 1):
        assert topics[i]["num_videos"] >= topics[i + 1]["num_videos"]


def test_article_topics_sort_by_length(seeded):
    """?sort=length (default) should return topics sorted by total_content_length descending."""
    client = _make_client("admin")
    data = client.get("/suggestions?sort=length", headers=ADMIN_HDR).json()
    topics = data["article_topics"]
    for t in topics:
        assert "total_content_length" in t
    for i in range(len(topics) - 1):
        assert topics[i]["total_content_length"] >= topics[i + 1]["total_content_length"]


def test_article_topics_default_sort_is_length(seeded):
    """No sort param should behave the same as sort=length."""
    client = _make_client("admin")
    default_data = client.get("/suggestions", headers=ADMIN_HDR).json()
    length_data = client.get("/suggestions?sort=length", headers=ADMIN_HDR).json()
    default_labels = [t["label"] for t in default_data["article_topics"]]
    length_labels = [t["label"] for t in length_data["article_topics"]]
    assert default_labels == length_labels


# ---------------------------------------------------------------------------
# reels bucket
# ---------------------------------------------------------------------------

def test_reels_includes_approved_without_schedule(seeded):
    """Approved MiniSeries with no ScheduledContent must appear in reels."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    assert len(data["reels"]) == 1
    r = data["reels"][0]
    assert r["video_id"] == "vid_b"
    assert r["parts_count"] == 1


def test_reels_excludes_already_scheduled(seeded):
    """Once a ScheduledContent (kind=reel) exists for a series, exclude it."""
    series_id = seeded["series_id"]
    with SessionLocal() as db:
        db.add(ScheduledContent(
            kind="reel",
            ref_id=str(series_id),
            status="scheduled",
            target="instagram",
        ))
        db.commit()

    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()
    reel_ids = [r["series_id"] for r in data["reels"]]
    assert series_id not in reel_ids


def test_reels_excludes_already_posted(seeded):
    """Once a SocialPost exists for the series, exclude it."""
    series_id = seeded["series_id"]
    with SessionLocal() as db:
        db.add(SocialPost(
            series_id=series_id,
            part=1,
            platform="instagram",
            gcs_url="gs://bucket/reel.mp4",
            status="pending",
        ))
        db.commit()

    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()
    reel_ids = [r["series_id"] for r in data["reels"]]
    assert series_id not in reel_ids


# ---------------------------------------------------------------------------
# faqs bucket
# ---------------------------------------------------------------------------

def test_faqs_excludes_video_covered_by_article(seeded):
    """Objections for videos already cited in an article must be excluded."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    video_ids = [f["video_id"] for f in data["faqs"]]
    assert "vid_a" not in video_ids


def test_faqs_includes_uncovered_video(seeded):
    """Objections for videos with no article coverage appear in faqs."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    video_ids = [f["video_id"] for f in data["faqs"]]
    assert "vid_c" in video_ids


def test_faqs_have_question_and_timecode(seeded):
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    faq = next(f for f in data["faqs"] if f["video_id"] == "vid_c")
    assert faq["question"].endswith("?")
    assert isinstance(faq["t"], int)


def test_faqs_have_title(seeded):
    """Each faq item must include the video title (not raw ID)."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    faq = next(f for f in data["faqs"] if f["video_id"] == "vid_c")
    assert faq["title"] == "Shingle Selection"


# ---------------------------------------------------------------------------
# unused_videos bucket
# ---------------------------------------------------------------------------

def test_unused_videos_excludes_article_covered(seeded):
    """Videos referenced in an article must not appear in unused_videos."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    ids = [v["video_id"] for v in data["unused_videos"]]
    assert "vid_a" not in ids


def test_unused_videos_excludes_series_video(seeded):
    """Videos in a MiniSeries must not appear in unused_videos."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    ids = [v["video_id"] for v in data["unused_videos"]]
    assert "vid_b" not in ids


def test_unused_videos_includes_unlinked(seeded):
    """vid_c has a transcript, no article, no MiniSeries -> must appear."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    ids = [v["video_id"] for v in data["unused_videos"]]
    assert "vid_c" in ids


def test_unused_videos_has_title(seeded):
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    vid_c = next(v for v in data["unused_videos"] if v["video_id"] == "vid_c")
    assert vid_c["title"] == "Shingle Selection"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_response_has_all_buckets(seeded):
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    assert "article_topics" in data
    assert "article_topics_total" in data
    assert "reels" in data
    assert "faqs" in data
    assert "faqs_total" in data
    assert "unused_videos" in data
    assert "unused_videos_total" in data


def test_totals_match_or_exceed_returned(seeded):
    """*_total counts must be >= length of the returned slice."""
    client = _make_client("admin")
    data = client.get("/suggestions", headers=ADMIN_HDR).json()

    assert data["article_topics_total"] >= len(data["article_topics"])
    assert data["faqs_total"] >= len(data["faqs"])
    assert data["unused_videos_total"] >= len(data["unused_videos"])


def test_limit_param_respected(seeded):
    """?limit=1 should return at most 1 item per bucket."""
    client = _make_client("admin")
    data = client.get("/suggestions?limit=1", headers=ADMIN_HDR).json()

    assert len(data["article_topics"]) <= 1
    assert len(data["faqs"]) <= 1
    assert len(data["unused_videos"]) <= 1
    # totals should still reflect full counts
    assert data["faqs_total"] >= len(data["faqs"])


# ---------------------------------------------------------------------------
# /counts endpoint
# ---------------------------------------------------------------------------

def test_counts_401_no_token():
    client = _make_client("admin")
    resp = client.get("/suggestions/counts")
    assert resp.status_code == 401


def test_counts_403_sales():
    client = _make_client("sales")
    resp = client.get("/suggestions/counts", headers=ADMIN_HDR)
    assert resp.status_code == 403


def test_counts_shape(seeded):
    """GET /suggestions/counts must return all four bucket keys as integers."""
    client = _make_client("admin")
    resp = client.get("/suggestions/counts", headers=ADMIN_HDR)
    assert resp.status_code == 200
    data = resp.json()
    for key in ("article_topics", "reels", "faqs", "unused_videos"):
        assert key in data, f"missing key: {key}"
        assert isinstance(data[key], int), f"{key} must be int"


def test_counts_match_suggestions_totals(seeded):
    """counts values must match the *_total fields from GET /suggestions."""
    client = _make_client("admin")
    counts = client.get("/suggestions/counts", headers=ADMIN_HDR).json()
    suggestions = client.get("/suggestions", headers=ADMIN_HDR).json()

    assert counts["article_topics"] == suggestions["article_topics_total"]
    assert counts["faqs"] == suggestions["faqs_total"]
    assert counts["unused_videos"] == suggestions["unused_videos_total"]
    # reels has no *_total — compare length (seeded has 1 reel)
    assert counts["reels"] == len(suggestions["reels"])


def test_counts_empty_db():
    """With no data, all counts must be zero."""
    client = _make_client("admin")
    # clean_db autouse fixture has already wiped the DB
    data = client.get("/suggestions/counts", headers=ADMIN_HDR).json()
    assert data["article_topics"] == 0
    assert data["reels"] == 0
    assert data["faqs"] == 0
    assert data["unused_videos"] == 0
