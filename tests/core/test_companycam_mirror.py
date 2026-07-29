"""Behavioral validation for the CompanyCam mirror (no network).

Isolated in-memory SQLite engine per test (same pattern as tests/core/test_status.py) —
the suite-wide SessionLocal (conftest) shares one file across the whole run, which
would pollute the exact-count/idempotency assertions here.

SQLite doesn't enforce RLS or the migration's partial unique index — those are
Postgres-only guarantees validated by infra/migrations/0043_companycam.sql itself,
not by this fixture.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import adapters.companycam as companycam
from app.models import Base, CompanyCamPhoto
from core.companycam.mirror import content_hash, upsert_photo, upsert_video


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    session.info["tenant_id"] = 1
    try:
        yield session
    finally:
        session.close()


def _photo(**overrides) -> dict:
    base = {
        "companycam_photo_id": "photo_1",
        "project_id": "proj_1",
        "url": "https://example.com/photo_1.jpg",
        "captured_at": 1752700000,
        "lat": 25.77,
        "lon": -80.19,
        "tags": ["roof"],
        "raw": {"id": "photo_1", "project_id": "proj_1"},
    }
    base.update(overrides)
    return base


def test_content_hash_stable_and_changes_on_field_change():
    photo = _photo()
    h1 = content_hash(photo)
    h2 = content_hash(_photo())
    assert h1 == h2

    changed = content_hash(_photo(url="https://example.com/photo_1_v2.jpg"))
    assert changed != h1


def test_upsert_photo_inserts_then_idempotent_on_replay(db):
    photo = _photo()

    created = upsert_photo(db, photo)
    db.flush()
    assert created is True
    rows = db.query(CompanyCamPhoto).all()
    assert len(rows) == 1
    assert rows[0].companycam_photo_id == "photo_1"
    assert rows[0].content_hash == content_hash(photo)

    # Replay with the identical payload — same hash, no duplicate row, created=False.
    created_again = upsert_photo(db, photo)
    db.flush()
    assert created_again is False
    assert db.query(CompanyCamPhoto).count() == 1

    # A real field change flips the hash and updates the existing row in place.
    changed_photo = _photo(url="https://example.com/photo_1_v2.jpg")
    updated = upsert_photo(db, changed_photo)
    db.flush()
    assert updated is True
    assert db.query(CompanyCamPhoto).count() == 1
    assert db.query(CompanyCamPhoto).one().url == "https://example.com/photo_1_v2.jpg"


def test_configured_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("COMPANYCAM_PAT", raising=False)
    assert companycam.configured() is False


def test_configured_true_when_env_set(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PAT", "test-pat")
    assert companycam.configured() is True


# --- videos (migration 0047) -------------------------------------------------------

def _video(**overrides) -> dict:
    base = {
        "companycam_video_id": "video_1",
        "project_id": "proj_1",
        "url": "https://example.com/video_1.m3u8",
        "thumbnail_url": "https://example.com/video_1_large.jpg",
        "captured_at": 1752700000,
        "lat": 25.77,
        "lon": -80.19,
        "status": "ready",
        "internal": False,
        "raw": {"id": "video_1", "project_id": "proj_1"},
    }
    base.update(overrides)
    return base


def test_upsert_video_inserts_then_idempotent_on_replay(db):
    from app.models import CompanyCamVideo

    video = _video()
    assert upsert_video(db, video) is True
    db.flush()
    row = db.query(CompanyCamVideo).one()
    assert row.companycam_video_id == "video_1"
    assert row.thumbnail_url == "https://example.com/video_1_large.jpg"
    assert row.status == "ready"
    # Epoch seconds must land as a datetime, not an int — the payload's timestamps are unix
    # ints where a photo's are ISO strings.
    assert row.captured_at.year == 2025

    assert upsert_video(db, video) is False
    db.flush()
    assert db.query(CompanyCamVideo).count() == 1

    assert upsert_video(db, _video(url="https://example.com/video_1_v2.m3u8")) is True
    db.flush()
    assert db.query(CompanyCamVideo).count() == 1
    assert db.query(CompanyCamVideo).one().url == "https://example.com/video_1_v2.m3u8"


def test_video_internal_defaults_to_true_when_absent(db):
    """The safe default for media we could not classify is DO NOT PUBLISH.

    CompanyCam lets a crew mark media internal-only. A payload missing the flag must never
    be mirrored as publishable — that is the failure that puts a crew's internal clip on a
    public project page.
    """
    from app.models import CompanyCamVideo

    payload = _video()
    del payload["internal"]
    upsert_video(db, payload)
    db.flush()
    assert db.query(CompanyCamVideo).one().internal is True


def test_video_internal_flag_is_carried_through(db):
    from app.models import CompanyCamVideo

    upsert_video(db, _video(companycam_video_id="pub", internal=False))
    upsert_video(db, _video(companycam_video_id="priv", internal=True))
    db.flush()
    publishable = db.query(CompanyCamVideo).filter(CompanyCamVideo.internal.is_(False)).all()
    assert [v.companycam_video_id for v in publishable] == ["pub"]


def test_normalize_video_maps_the_live_payload_shape():
    """Videos are not photos: playback_url + thumbnail_urls{}, not uris[]."""
    raw = {
        "id": 987, "project_id": 12, "playback_url": "https://cdn.example/v.m3u8",
        "thumbnail_urls": {"large": "https://cdn.example/l.jpg", "small": "https://cdn.example/s.jpg"},
        "captured_at": 1752700000, "coordinates": {"lat": 26.0, "lon": -80.1},
        "status": "ready", "internal": True,
    }
    out = companycam.normalize_video(raw)
    assert out["companycam_video_id"] == "987"      # ints stringified
    assert out["project_id"] == "12"
    assert out["url"] == "https://cdn.example/v.m3u8"
    assert out["thumbnail_url"] == "https://cdn.example/l.jpg"   # prefers large
    assert out["internal"] is True
