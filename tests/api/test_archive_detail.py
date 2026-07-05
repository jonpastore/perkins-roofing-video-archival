"""Tests for GET /archive/{video_id}/detail.

Hermetic: temp SQLite DB (DB_URL set by conftest.py before any import) + fake token verifier.
Seeds: one Video, two GraphNode topics, one MiniSeries + one SocialPost, one Article that
references the video_id in its content_md.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure isolated DB (conftest.py already sets DB_URL via env before collection, but guard here
# too so the file is usable standalone with `pytest tests/api/test_archive_detail.py`).
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("DB_URL", f"sqlite:///{_tmp.name}")

from api.auth import set_verifier  # noqa: E402
from api.routes.archive import router  # noqa: E402
from app.models import (  # noqa: E402
    Base, SessionLocal, Video, GraphNode, Article, MiniSeries, SocialPost, engine,
)

Base.metadata.create_all(engine)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_ID = "detail_test_vid"
OTHER_VIDEO_ID = "other_vid"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def seed_db():
    """Wipe relevant tables and insert known rows before each test."""
    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(MiniSeries).delete()
        db.query(Article).delete()
        db.query(GraphNode).delete()
        db.query(Video).delete()

        # The video under test
        db.add(Video(
            id=VIDEO_ID,
            title="Flat Roof Maintenance",
            duration=450.0,
            upload_date="2024-05-01",
            url=f"https://youtube.com/watch?v={VIDEO_ID}",
            archive_uri=f"gs://proj-media/videos/{VIDEO_ID}.mp4",
        ))
        # Another video (must not appear in results)
        db.add(Video(
            id=OTHER_VIDEO_ID,
            title="Gutters Deep Dive",
            duration=300.0,
            upload_date="2024-04-01",
            url=f"https://youtube.com/watch?v={OTHER_VIDEO_ID}",
            archive_uri=None,
        ))

        # Two topics for VIDEO_ID, one for OTHER_VIDEO_ID
        db.add(GraphNode(video_id=VIDEO_ID, kind="topics", label="Flat roof drainage", start=30.0, version="v1"))
        db.add(GraphNode(video_id=VIDEO_ID, kind="topics", label="TPO membrane overview", start=90.0, version="v1"))
        db.add(GraphNode(video_id=OTHER_VIDEO_ID, kind="topics", label="Gutter guards", start=10.0, version="v1"))

        # A non-topic node for VIDEO_ID (must not appear)
        db.add(GraphNode(video_id=VIDEO_ID, kind="claims", label="Flat roofs last 15+ years", start=60.0, version="v1"))

        # MiniSeries + SocialPost for VIDEO_ID
        series = MiniSeries(video_id=VIDEO_ID, title="Flat Roof Series", parts_json=[], approved=1)
        db.add(series)
        db.flush()  # get series.id
        db.add(SocialPost(
            series_id=series.id,
            part=1,
            platform="instagram",
            gcs_url=f"gs://proj-media/reels/{VIDEO_ID}-p1.mp4",
            external_id="IG_POST_123",
            status="published",
        ))

        # Article that references VIDEO_ID in its content_md
        db.add(Article(
            slug="flat-roof-guide",
            title="Complete Flat Roof Guide",
            content_md=f"Learn more at https://youtu.be/{VIDEO_ID}?t=30 and maintain your roof.",
            status="published",
            role="cluster",
        ))
        # Article that does NOT reference VIDEO_ID
        db.add(Article(
            slug="gutter-article",
            title="Gutter Maintenance",
            content_md="Keep gutters clean to avoid water damage.",
            status="draft",
            role="standalone",
        ))

        db.commit()

    yield

    with SessionLocal() as db:
        db.query(SocialPost).delete()
        db.query(MiniSeries).delete()
        db.query(Article).delete()
        db.query(GraphNode).delete()
        db.query(Video).delete()
        db.commit()


def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


AUTH = {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# 404 cases
# ---------------------------------------------------------------------------

def test_detail_404_unknown_video():
    client = _make_client("admin")
    resp = client.get("/archive/nonexistent/detail", headers=AUTH)
    assert resp.status_code == 404


def test_detail_401_no_token():
    client = _make_client("admin")
    resp = client.get(f"/archive/{VIDEO_ID}/detail")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def test_detail_topics_returned():
    client = _make_client("admin")
    resp = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "topics" in data
    topics = data["topics"]
    assert len(topics) == 2  # only kind='topics', not claims


def test_detail_topics_ordered_by_start():
    client = _make_client("admin")
    data = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH).json()
    starts = [t["t"] for t in data["topics"]]
    assert starts == sorted(starts)


def test_detail_topics_fields_and_url():
    client = _make_client("admin")
    data = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH).json()
    t = data["topics"][0]
    assert t["label"] == "Flat roof drainage"
    assert t["t"] == 30
    assert t["url"] == f"https://youtu.be/{VIDEO_ID}?t=30"


def test_detail_topics_only_for_this_video():
    """The OTHER_VIDEO_ID topic (Gutter guards) must not bleed in."""
    client = _make_client("admin")
    data = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH).json()
    labels = {t["label"] for t in data["topics"]}
    assert "Gutter guards" not in labels


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------

def test_detail_articles_returned():
    client = _make_client("admin")
    data = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH).json()
    articles = data["articles"]
    assert len(articles) == 1
    assert articles[0]["slug"] == "flat-roof-guide"
    assert articles[0]["title"] == "Complete Flat Roof Guide"
    assert articles[0]["status"] == "published"


def test_detail_articles_excludes_non_matching():
    """gutter-article does not contain VIDEO_ID — must be absent."""
    client = _make_client("admin")
    data = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH).json()
    slugs = {a["slug"] for a in data["articles"]}
    assert "gutter-article" not in slugs


# ---------------------------------------------------------------------------
# Social posts
# ---------------------------------------------------------------------------

def test_detail_social_posts_returned():
    client = _make_client("admin")
    data = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH).json()
    posts = data["social_posts"]
    assert len(posts) == 1
    p = posts[0]
    assert p["platform"] == "instagram"
    assert p["status"] == "published"
    # external_id known → derive Instagram URL
    assert p["url"] == "https://www.instagram.com/p/IG_POST_123/"


def test_detail_social_posts_empty_for_other_video():
    """OTHER_VIDEO_ID has no mini_series — social_posts must be empty."""
    client = _make_client("admin")
    data = client.get(f"/archive/{OTHER_VIDEO_ID}/detail", headers=AUTH).json()
    assert data["social_posts"] == []


# ---------------------------------------------------------------------------
# Sales role can access
# ---------------------------------------------------------------------------

def test_detail_accessible_by_sales():
    client = _make_client("sales")
    resp = client.get(f"/archive/{VIDEO_ID}/detail", headers=AUTH)
    assert resp.status_code == 200
