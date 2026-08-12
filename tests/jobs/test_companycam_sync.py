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


@pytest.fixture(autouse=True)
def _tag_pass(monkeypatch):
    """Neutralise the account-wide publish-tag pass for the crawl tests below.

    The pass is real behaviour and is asserted directly in
    tests/core/test_companycam_tag_filter.py; here it would only add network doubles and an
    error count to tests that are about the per-project crawl.
    """
    monkeypatch.setattr(sync.companycam, "known_tag_ids",
                        lambda: {sync.companycam.projects_tag_id(),
                                 sync.companycam.projects_video_tag_id()})
    monkeypatch.setattr(sync.companycam, "list_tagged_photos", lambda tag_ids: [])
    monkeypatch.setattr(sync.companycam, "list_tagged_videos", lambda tag_ids: [])


def _photo(pid):
    return {"companycam_photo_id": pid, "project_id": "p1", "url": f"http://x/{pid}.jpg",
            "captured_at": None, "lat": None, "lon": None, "tags": [], "raw": {}}


def _video(vid, internal=False):
    return {"companycam_video_id": vid, "project_id": "p1", "url": f"http://x/{vid}.m3u8",
            "thumbnail_url": None, "captured_at": None, "lat": None, "lon": None,
            "status": "ready", "internal": internal, "raw": {}}


def test_sync_mirrors_photos_and_videos(db, monkeypatch):
    monkeypatch.setattr(sync.companycam, "list_projects", lambda: [{"id": "p1"}])
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid, tag_ids=None:
                        [_photo("ph1"), _photo("ph2")])
    monkeypatch.setattr(sync.companycam, "list_videos", lambda pid, tag_ids=None: [_video("v1")])

    counts = sync._sync_tenant(db, 1)
    db.flush()

    assert counts["photos_written"] == 2
    assert counts["videos_written"] == 1, "video pull is the whole point of 0047"
    assert counts["errors"] == 0
    assert db.query(CompanyCamPhoto).count() == 2
    assert db.query(CompanyCamVideo).count() == 1



def test_a_failing_video_endpoint_still_mirrors_that_project_s_photos(db, monkeypatch):
    """One resource failing must not cost us the other — they are independent endpoints."""
    def boom(_pid, tag_ids=None):
        raise RuntimeError("companycam 500")

    monkeypatch.setattr(sync.companycam, "list_projects", lambda: [{"id": "p1"}])
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid, tag_ids=None: [_photo("ph1")])
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
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid, tag_ids=None: [])
    monkeypatch.setattr(sync.companycam, "list_videos", lambda pid, tag_ids=None:
                        [_video("pub"), _video("priv", internal=True)])

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


# --- incremental sync (migration 0049) -------------------------------------
# 3,684 projects x 2 endpoints is ~7,400 paginated requests. The whole point of the project
# mirror is that a night with nothing new costs one project listing.

def _project(pid="p1", updated_at=1_700_000_000):
    return {"id": pid, "name": "Butterworth", "updated_at": updated_at,
            "status": "active", "archived": False, "photo_count": 2}


def _wire(monkeypatch, projects, photos=(), videos=(), calls=None):
    monkeypatch.setattr(sync.companycam, "list_projects", lambda: list(projects))

    def _photos(pid, tag_ids=None):
        if tag_ids:
            return []           # nothing tagged for publication in these fixtures
        if calls is not None:
            calls.append(("photos", pid))
        return list(photos)

    def _videos(pid, tag_ids=None):
        if tag_ids:
            return []
        if calls is not None:
            calls.append(("videos", pid))
        return list(videos)

    monkeypatch.setattr(sync.companycam, "list_photos", _photos)
    monkeypatch.setattr(sync.companycam, "list_videos", _videos)


def test_unchanged_project_is_skipped_on_the_second_run(db, monkeypatch):
    calls = []
    _wire(monkeypatch, [_project()], photos=[_photo("ph1")], videos=[_video("v1")], calls=calls)

    first = sync._sync_tenant(db, 1)
    assert first["projects_skipped"] == 0
    assert first["photos_written"] == 1
    assert len(calls) == 2, "first run must fetch both endpoints"

    calls.clear()
    second = sync._sync_tenant(db, 1)
    assert second["projects_skipped"] == 1
    assert calls == [], "an unchanged project must cost ZERO media requests"


def test_a_touched_project_is_refetched(db, monkeypatch):
    calls = []
    _wire(monkeypatch, [_project()], photos=[_photo("ph1")], calls=calls)
    sync._sync_tenant(db, 1)

    calls.clear()
    _wire(monkeypatch, [_project(updated_at=1_800_000_000)], photos=[_photo("ph1"), _photo("ph2")],
          calls=calls)
    result = sync._sync_tenant(db, 1)
    assert result["projects_skipped"] == 0
    assert ("photos", "p1") in calls, "a moved updated_at must re-fetch"
    assert result["photos_written"] == 1, "only the new photo is written; ph1 is unchanged"


def test_a_partial_pull_is_retried_rather_than_remembered_as_complete(db, monkeypatch):
    """If videos failed, the project must NOT be stamped synced — otherwise the missing half
    is invisible forever, since updated_at will not move just because our fetch failed."""
    def boom(_pid, tag_ids=None):
        raise RuntimeError("companycam 500")

    monkeypatch.setattr(sync.companycam, "list_projects", lambda: [_project()])
    monkeypatch.setattr(sync.companycam, "list_photos", lambda pid, tag_ids=None: [_photo("ph1")])
    monkeypatch.setattr(sync.companycam, "list_videos", boom)
    first = sync._sync_tenant(db, 1)
    assert first["errors"] == 1

    calls = []
    _wire(monkeypatch, [_project()], photos=[_photo("ph1")], videos=[_video("v1")], calls=calls)
    second = sync._sync_tenant(db, 1)
    assert second["projects_skipped"] == 0, "a failed half must force a retry"
    assert second["videos_written"] == 1


def test_project_row_carries_the_name_used_to_match_a_candidate(db, monkeypatch):
    from app.models import CompanyCamProject

    _wire(monkeypatch, [_project()])
    sync._sync_tenant(db, 1)
    row = db.query(CompanyCamProject).one()
    assert row.name == "Butterworth"
    assert row.remote_updated_at is not None
    assert row.media_synced_at is not None
