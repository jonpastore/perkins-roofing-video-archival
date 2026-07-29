"""Behavioral validation for the CompanyCam sync job (no network).

The job is coverage-omitted (I/O orchestration), but the fan-out over two SEPARATE v2
resources is exactly the shape that fails silently: before 2026-07-29 it pulled photos
only, `list_videos` existed and was called by nothing, and the mirror table sat at 0 rows
while everything reported success.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import jobs.companycam_sync as sync
from app.models import Base, CompanyCamPhoto, CompanyCamVideo


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.info["tenant_id"] = 1
    try:
        yield session
    finally:
        session.close()


def _photo(pid):
    return {"companycam_photo_id": pid, "project_id": "p1", "url": f"http://x/{pid}.jpg",
            "captured_at": None, "lat": None, "lon": None, "tags": [], "raw": {}}


def _video(vid, internal=False):
    return {"companycam_video_id": vid, "project_id": "p1", "url": f"http://x/{vid}.m3u8",
            "thumbnail_url": None, "captured_at": None, "lat": None, "lon": None,
            "status": "ready", "internal": internal, "raw": {}}


def test_sync_mirrors_photos_and_videos(db, monkeypatch):
    monkeypatch.setattr(sync.companycam, "list_projects", lambda: [{"id": "p1"}])
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid: [_photo("ph1"), _photo("ph2")])
    monkeypatch.setattr(sync.companycam, "list_videos", lambda pid: [_video("v1")])

    counts = sync._sync_tenant(db, 1)
    db.flush()

    assert counts["photos_written"] == 2
    assert counts["videos_written"] == 1, "video pull is the whole point of 0047"
    assert counts["errors"] == 0
    assert db.query(CompanyCamPhoto).count() == 2
    assert db.query(CompanyCamVideo).count() == 1


def test_a_failing_video_endpoint_still_mirrors_that_project_s_photos(db, monkeypatch):
    """One resource failing must not cost us the other — they are independent endpoints."""
    def boom(_pid):
        raise RuntimeError("companycam 500")

    monkeypatch.setattr(sync.companycam, "list_projects", lambda: [{"id": "p1"}])
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid: [_photo("ph1")])
    monkeypatch.setattr(sync.companycam, "list_videos", boom)

    counts = sync._sync_tenant(db, 1)
    db.flush()

    assert counts["photos_written"] == 1
    assert counts["videos_seen"] == 0
    assert counts["errors"] == 1
    assert db.query(CompanyCamPhoto).count() == 1


def test_internal_video_is_mirrored_but_flagged(db, monkeypatch):
    """Internal media is stored (we need to know it exists) and marked unpublishable."""
    monkeypatch.setattr(sync.companycam, "list_projects", lambda: [{"id": "p1"}])
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid: [])
    monkeypatch.setattr(sync.companycam, "list_videos",
                        lambda pid: [_video("pub"), _video("priv", internal=True)])

    sync._sync_tenant(db, 1)
    db.flush()

    publishable = db.query(CompanyCamVideo).filter(CompanyCamVideo.internal.is_(False)).all()
    assert [v.companycam_video_id for v in publishable] == ["pub"]


def test_unconfigured_is_a_clean_skip_not_a_crash(monkeypatch):
    """The scheduler must never see a red job just because the key is absent."""
    monkeypatch.setattr(sync.companycam, "configured", lambda: False)
    result = sync.run()
    assert result["exit_code"] == 0
    assert "skipped" in result
