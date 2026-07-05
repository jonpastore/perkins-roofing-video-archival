"""Tests for GET /video/series endpoint.

Uses a temp SQLite DB and a fake token verifier — no real Firebase or DB needed.
"""
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# --- set up temp DB before any app.models import ---
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

from api.auth import set_verifier  # noqa: E402
from api.routes.video import clean_label, router  # noqa: E402
from app.models import Base, MiniSeries, SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_db():
    """Wipe mini_series between tests."""
    with SessionLocal() as db:
        db.query(MiniSeries).delete()
        db.commit()
    yield


@pytest.fixture()
def two_series():
    """Seed one approved and one pending MiniSeries; return (pending_id, approved_id)."""
    with SessionLocal() as db:
        pending = MiniSeries(video_id="vid_p", title="Pending Series", parts_json=[], approved=0)
        approved = MiniSeries(video_id="vid_a", title="Approved Series", parts_json=[], approved=1)
        db.add(pending)
        db.add(approved)
        db.commit()
        db.refresh(pending)
        db.refresh(approved)
        return pending.id, approved.id


def _make_client(role: str | None) -> TestClient:
    if role is not None:
        set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    else:
        set_verifier(lambda token: (_ for _ in ()).throw(ValueError("no token")))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


AUTH = {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# GET /video/series — role gating
# ---------------------------------------------------------------------------

def test_series_401_no_token():
    client = _make_client("admin")
    resp = client.get("/video/series")
    assert resp.status_code == 401


def test_series_403_sales():
    client = _make_client("sales")
    resp = client.get("/video/series", headers=AUTH)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /video/series — returns all (approved + unapproved)
# ---------------------------------------------------------------------------

def test_series_empty_list():
    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == []


def test_series_returns_all(two_series):
    pending_id, approved_id = two_series
    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ids = {item["id"] for item in data}
    assert pending_id in ids
    assert approved_id in ids


def test_series_includes_approved_flag(two_series):
    pending_id, approved_id = two_series
    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    data = resp.json()
    by_id = {item["id"]: item for item in data}
    assert by_id[pending_id]["approved"] == 0
    assert by_id[approved_id]["approved"] == 1


def test_series_ordered_by_id_desc(two_series):
    pending_id, approved_id = two_series
    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    data = resp.json()
    # higher id should come first (desc order)
    assert data[0]["id"] > data[1]["id"]


def test_series_response_shape(two_series):
    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    item = resp.json()[0]
    assert set(item.keys()) == {"id", "video_id", "title", "approved", "label"}


# ---------------------------------------------------------------------------
# label field — cleaning rules
# ---------------------------------------------------------------------------

def test_series_label_strips_emoji():
    """A title that is only emojis yields a disambiguated label (not blank or emoji)."""
    with SessionLocal() as db:
        row = MiniSeries(video_id="vid_emoji", title="\U0001F525\U0001F525", parts_json=[], approved=0)
        db.add(row)
        db.commit()
        db.refresh(row)
        s_id = row.id

    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    data = resp.json()
    by_id = {item["id"]: item for item in data}
    label = by_id[s_id]["label"]
    # Must not contain raw emoji and must not be empty
    assert "\U0001F525" not in label
    assert label.strip() != ""


def test_series_label_strips_leading_hashtags():
    """A title starting with hashtags has them stripped in the label."""
    with SessionLocal() as db:
        row = MiniSeries(video_id="vid_hash", title="##RoofingTips", parts_json=[], approved=0)
        db.add(row)
        db.commit()
        db.refresh(row)
        s_id = row.id

    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    data = resp.json()
    by_id = {item["id"]: item for item in data}
    label = by_id[s_id]["label"]
    assert not label.startswith("#")
    assert "RoofingTips" in label


def test_series_label_deduplicates_identical_cleaned_titles():
    """Two series with identical cleaned titles get disambiguated labels."""
    with SessionLocal() as db:
        a = MiniSeries(video_id="vid_a1", title="Roof Repairs", parts_json=[], approved=0)
        b = MiniSeries(video_id="vid_b1", title="Roof Repairs", parts_json=[], approved=0)
        db.add(a)
        db.add(b)
        db.commit()
        db.refresh(a)
        db.refresh(b)
        a_id, b_id = a.id, b.id

    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    data = resp.json()
    by_id = {item["id"]: item for item in data}
    label_a = by_id[a_id]["label"]
    label_b = by_id[b_id]["label"]
    # Labels must differ
    assert label_a != label_b
    # Both must still reference the base title or an ID
    assert "Roof Repairs" in label_a or str(a_id) in label_a
    assert "Roof Repairs" in label_b or str(b_id) in label_b


def test_series_label_emoji_plus_hashtag_title():
    """A title with emoji AND leading hashtag is fully cleaned."""
    with SessionLocal() as db:
        row = MiniSeries(
            video_id="vid_mixed",
            title="\U0001F3E0 #BestRoofer",
            parts_json=[],
            approved=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        s_id = row.id

    client = _make_client("admin")
    resp = client.get("/video/series", headers=AUTH)
    data = resp.json()
    by_id = {item["id"]: item for item in data}
    label = by_id[s_id]["label"]
    assert "\U0001F3E0" not in label
    assert not label.startswith("#")
    assert label.strip() != ""


# ---------------------------------------------------------------------------
# clean_label unit tests (helper function directly)
# ---------------------------------------------------------------------------

def test_clean_label_strips_emoji():
    assert clean_label("\U0001F525 Fire sale") == "Fire sale"


def test_clean_label_strips_leading_hash():
    assert clean_label("#RoofingTips") == "RoofingTips"


def test_clean_label_strips_multiple_leading_hashes():
    assert clean_label("##BestRoofer") == "BestRoofer"


def test_clean_label_collapses_whitespace():
    assert clean_label("  Roof   Repair  ") == "Roof Repair"


def test_clean_label_empty_after_strip_returns_empty():
    assert clean_label("\U0001F525\U0001F525") == ""


def test_clean_label_leading_dash_stripped():
    assert clean_label("— Gutters") == "Gutters"


def test_clean_label_plain_title_unchanged():
    assert clean_label("Metal Roofing") == "Metal Roofing"
