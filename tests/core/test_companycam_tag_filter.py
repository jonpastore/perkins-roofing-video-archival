"""Behavioral validation for CompanyCam publish-tag filtering (no network).

Two defects are covered here.

THE ORIGINAL: `adapters/companycam.py` read `raw.get("tags")` from photo payloads that have no
`tags` key, so `companycam_photos.tags` was `[]` for every one of ~156k mirrored rows and
nothing could tell a publishable photo from a tear-off frame. Building 77 offered 312 photos
and 22 videos to a gallery that should show 9 and 2.

THE ONE THE FIRST FIX INTRODUCED: stamping tags inside the per-project crawl put them behind
the incremental `needs_media` gate, which keys off the PROJECT's CompanyCam `updated_at`. A
finished roof's timestamp never moves again, so the backfill could never reach the completed
jobs the portfolio is built from — green job, permanently empty galleries. The tag pass is now
account-wide and gated by nothing; `test_the_tag_pass_runs_even_when_every_project_is_skipped`
is the regression test and fails against that design.

Each test asserts the thing that would CHANGE if the fix were wrong — the URL actually
requested, the rows actually written — not that a call merely succeeded.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import adapters.companycam as companycam
from app.models import Base, CompanyCamPhoto, CompanyCamVideo
from core.companycam.mirror import content_hash, set_publish_tags, upsert_photo, upsert_video


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


@pytest.fixture()
def captured_urls(monkeypatch):
    """Record every URL the adapter really builds, and serve one page then an empty one.

    Patched at ``urlopen`` — the HTTP boundary — deliberately. Faking ``_get`` instead would
    mean re-implementing the query-string assembly in the test, so the assertions would be
    checking the double rather than the code that talks to CompanyCam, and a wrong parameter
    spelling (the exact bug here) would still pass.
    """
    urls: list[str] = []

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        urls.append(req.full_url)
        # One populated page, then an empty one ends pagination. Keyed off the call count,
        # NOT a substring of the URL — "page=1" is also a substring of "per_page=100".
        body = ([{"id": "p1", "project_id": "proj_1", "uris": []}] if len(urls) == 1 else [])
        return _Resp(json.dumps(body).encode())

    monkeypatch.setenv("COMPANYCAM_PAT", "test-key")
    monkeypatch.setattr(companycam.urllib.request, "urlopen", fake_urlopen)
    return urls


# --- the query string CompanyCam actually honours ---------------------------

def test_tag_filter_uses_the_plural_bracketed_form(captured_urls):
    """`tag_ids[]=` is the ONLY form that filters. `tag_id=`, `tags[]=` and `tag=` are
    accepted and silently ignored — they return the unfiltered list, so a wrong spelling
    is invisible: every request still 200s and the gallery just shows everything."""
    companycam.list_tagged_photos(["26926152"])
    assert "tag_ids[]=26926152" in captured_urls[0]


def test_the_tag_pass_hits_the_ACCOUNT_endpoint_not_a_project_one(captured_urls):
    """The account-wide index is what makes the pass independent of the per-project
    `needs_media` gate. A per-project URL here would reintroduce the empty-gallery defect."""
    companycam.list_tagged_photos(["26926152"])
    companycam.list_tagged_videos(["26926154"])
    assert all("/v2/projects/" not in u for u in captured_urls), captured_urls
    assert any(u.startswith("https://api.companycam.com/v2/photos?") for u in captured_urls)
    assert any(u.startswith("https://api.companycam.com/v2/videos?") for u in captured_urls)


def test_multiple_tag_ids_repeat_the_key_rather_than_joining_with_commas(captured_urls):
    companycam.list_tagged_videos(["1", "2"])
    assert "tag_ids[]=1&tag_ids[]=2" in captured_urls[0]
    assert "tag_ids[]=1,2" not in captured_urls[0]


def test_no_tag_ids_means_no_filter_param_at_all(captured_urls):
    companycam.list_photos("proj_1")
    assert all("tag_ids" not in u for u in captured_urls)


def test_the_filter_is_carried_onto_every_page(captured_urls):
    """Pagination must not drop the filter on page 2 — that would silently mix the whole
    account back in behind a filtered first page."""
    companycam.list_tagged_photos(["26926152"])
    assert len(captured_urls) >= 2
    assert all("tag_ids[]=26926152" in u for u in captured_urls)


def test_a_config_value_cannot_inject_extra_query_parameters(captured_urls):
    """The tag id is operator-editable, so it reaches a URL from a writable surface."""
    companycam.list_tagged_photos(["26926152&per_page=999"])
    assert "per_page=999" not in captured_urls[0]
    assert "%26per_page%3D999" in captured_urls[0]


# --- tags never come from the payload ---------------------------------------

def test_normalize_photo_never_invents_tags_from_a_payload_that_has_none():
    """A live photo payload carries no `tags` key. Reading one produced [] for every photo
    ever mirrored."""
    assert "tags" not in companycam.normalize_photo({"id": "p1", "uris": []})


def test_normalize_video_carries_no_tags_either():
    assert "tags" not in companycam.normalize_video({"id": "v1"})


def test_the_webhook_and_the_sync_agree_on_content_hash(db):
    """Both writers normalize the SAME payload the same way, so an unchanged photo produces
    zero writes no matter which one saw it last. When the sync stamped tags into this dict
    and the webhook did not, the two hashed differently and rewrote each other forever."""
    raw = {"id": "p1", "project_id": "proj_1", "uris": []}
    assert content_hash(companycam.normalize_photo(raw)) == \
        content_hash(companycam.normalize_photo(raw))

    upsert_photo(db, companycam.normalize_photo(raw))
    assert upsert_photo(db, companycam.normalize_photo(raw)) is False, "replay must not write"


def test_mirroring_a_photo_never_clears_its_publish_tag(db):
    """upsert_* must not own `tags`. The webhook handles photo.updated and has no tag
    information; writing [] there would silently drop a photo out of a published gallery."""
    upsert_photo(db, companycam.normalize_photo({"id": "p1", "project_id": "proj_1", "uris": []}))
    set_publish_tags(db, "photo", {"p1"}, "26926152")

    upsert_photo(db, companycam.normalize_photo(
        {"id": "p1", "project_id": "proj_1", "uris": [], "description": "edited"}))

    assert db.query(CompanyCamPhoto).filter_by(companycam_photo_id="p1").one().tags \
        == ["26926152"]


# --- set_publish_tags: the single writer ------------------------------------

def test_set_publish_tags_stamps_only_the_tagged_rows(db):
    for pid in ("a", "b", "c"):
        upsert_photo(db, companycam.normalize_photo({"id": pid, "project_id": "p", "uris": []}))

    result = set_publish_tags(db, "photo", {"a", "c"}, "26926152")

    rows = {r.companycam_photo_id: r.tags for r in db.query(CompanyCamPhoto).all()}
    assert rows == {"a": ["26926152"], "b": [], "c": ["26926152"]}
    assert result == {"tagged": 2, "cleared": 0}


def test_untagging_in_companycam_reaches_the_gallery(db):
    """A photo the crew un-tags must stop being publishable — otherwise it stays on a public
    page forever and the only fix is manual SQL."""
    upsert_photo(db, companycam.normalize_photo({"id": "a", "project_id": "p", "uris": []}))
    set_publish_tags(db, "photo", {"a"}, "26926152")

    result = set_publish_tags(db, "photo", set(), "26926152")

    assert db.query(CompanyCamPhoto).one().tags == []
    assert result == {"tagged": 0, "cleared": 1}


def test_set_publish_tags_is_idempotent(db):
    upsert_photo(db, companycam.normalize_photo({"id": "a", "project_id": "p", "uris": []}))
    set_publish_tags(db, "photo", {"a"}, "26926152")
    assert set_publish_tags(db, "photo", {"a"}, "26926152") == {"tagged": 0, "cleared": 0}


def test_set_publish_tags_handles_videos_with_the_video_tag(db):
    upsert_video(db, companycam.normalize_video({"id": "v1", "project_id": "p"}))
    upsert_video(db, companycam.normalize_video({"id": "v2", "project_id": "p"}))

    set_publish_tags(db, "video", {"v1"}, "26926154")

    rows = {r.companycam_video_id: r.tags for r in db.query(CompanyCamVideo).all()}
    assert rows == {"v1": ["26926154"], "v2": []}


def test_an_unmirrored_tagged_id_is_simply_not_there_yet(db):
    """A tagged photo whose project has not synced yet must not crash the pass."""
    assert set_publish_tags(db, "photo", {"never_seen"}, "26926152") == \
        {"tagged": 0, "cleared": 0}


def test_set_publish_tags_rejects_an_unknown_kind(db):
    with pytest.raises(ValueError):
        set_publish_tags(db, "document", set(), "26926152")


# --- the regression test for the empty-gallery defect -----------------------

def test_the_tag_pass_runs_even_when_every_project_is_skipped(db, monkeypatch):
    """THE one that matters.

    The per-project crawl is incremental: `needs_media` is False for any project whose
    CompanyCam `updated_at` has not moved, and a finished roof's never moves again. Every one
    of the ~3,684 projects was synced in July, so a tag pass gated behind that check would
    never run — the galleries would read empty forever while the job exited 0.
    """
    import jobs.companycam_sync as sync
    from app.models import CompanyCamProject

    upsert_photo(db, companycam.normalize_photo({"id": "ph1", "project_id": "p1", "uris": []}))
    # Exactly prod's state: already crawled, remote timestamp unchanged since.
    db.add(CompanyCamProject(tenant_id=1, companycam_project_id="p1",
                             media_synced_at=_dt(2026, 7, 28),
                             remote_updated_at=_dt(2026, 7, 28)))
    db.commit()

    monkeypatch.setattr(sync.companycam, "list_projects",
                        lambda: [{"id": "p1", "updated_at": 1785000000}])
    monkeypatch.setattr(sync.companycam, "list_photos", _must_not_be_called)
    monkeypatch.setattr(sync.companycam, "list_videos", _must_not_be_called)
    monkeypatch.setattr(sync.companycam, "known_tag_ids",
                        lambda: {companycam.projects_tag_id(),
                                 companycam.projects_video_tag_id()})
    monkeypatch.setattr(sync.companycam, "list_tagged_photos",
                        lambda tag_ids: [companycam.normalize_photo(
                            {"id": "ph1", "project_id": "p1", "uris": []})])
    monkeypatch.setattr(sync.companycam, "list_tagged_videos", lambda tag_ids: [])

    counts = sync._sync_tenant(db, 1)

    assert counts["projects_skipped"] == 1, "the crawl must still skip the unchanged project"
    assert counts["photos_tagged"] == 1, "but the tag pass must have run anyway"
    assert db.query(CompanyCamPhoto).one().tags == [companycam.projects_tag_id()]


def test_a_tag_id_the_account_does_not_have_writes_no_tags_at_all(db, monkeypatch):
    """CompanyCam ignores an unrecognised tag id and returns the UNFILTERED list (measured:
    tag_ids[]=1 returns all 312 of Building 77's photos, not 0). So a tag deleted and
    recreated in the UI — which mints a new id — would mark EVERY photo publishable."""
    import jobs.companycam_sync as sync

    upsert_photo(db, companycam.normalize_photo({"id": "ph1", "project_id": "p1", "uris": []}))
    set_publish_tags(db, "photo", {"ph1"}, "26926152")

    monkeypatch.setattr(companycam, "projects_tag_id", lambda: "STALE")
    monkeypatch.setattr(sync.companycam, "known_tag_ids", lambda: {"26926152", "26926154"})
    monkeypatch.setattr(sync.companycam, "list_tagged_photos", _must_not_be_called_tags)
    monkeypatch.setattr(sync.companycam, "list_tagged_videos", _must_not_be_called_tags)

    counts = {"errors": 0}
    sync._sync_publish_tags(db, counts)

    assert counts["errors"] >= 1, "a stale tag id must make the job go red, not pass quietly"
    assert db.query(CompanyCamPhoto).one().tags == ["26926152"], \
        "the known-good tag must survive an untrusted run"


def test_a_failed_tag_listing_writes_nothing(db, monkeypatch):
    import jobs.companycam_sync as sync

    def boom():
        raise RuntimeError("companycam 500")

    upsert_photo(db, companycam.normalize_photo({"id": "ph1", "project_id": "p1", "uris": []}))
    set_publish_tags(db, "photo", {"ph1"}, companycam.projects_tag_id())
    monkeypatch.setattr(sync.companycam, "known_tag_ids", boom)
    monkeypatch.setattr(sync.companycam, "list_tagged_photos", _must_not_be_called_tags)

    counts = {"errors": 0}
    sync._sync_publish_tags(db, counts)

    assert counts["errors"] == 1
    assert db.query(CompanyCamPhoto).one().tags == [companycam.projects_tag_id()]


# --- the ids are configuration ---------------------------------------------

def test_tag_ids_are_overridable_without_a_deploy(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PROJECTS_TAG_ID", "999")
    monkeypatch.setenv("COMPANYCAM_PROJECTS_VIDEO_TAG_ID", "888")
    assert companycam.projects_tag_id() == "999"
    assert companycam.projects_video_tag_id() == "888"


def test_both_tag_ids_are_editable_in_admin_config():
    """The job's error message tells the operator to fix these in Admin Config -> Platform
    Settings. PUT /config rejects any key outside EDITABLE_KEYS, so without this the runbook
    points at a screen where the setting does not exist."""
    from api.routes.config import EDITABLE_KEYS

    assert "COMPANYCAM_PROJECTS_TAG_ID" in EDITABLE_KEYS
    assert "COMPANYCAM_PROJECTS_VIDEO_TAG_ID" in EDITABLE_KEYS


def test_tag_ids_fall_back_to_the_ids_in_use_today(monkeypatch):
    monkeypatch.delenv("COMPANYCAM_PROJECTS_TAG_ID", raising=False)
    monkeypatch.delenv("COMPANYCAM_PROJECTS_VIDEO_TAG_ID", raising=False)
    assert companycam.projects_tag_id() == "26926152"
    assert companycam.projects_video_tag_id() == "26926154"


def _dt(y, m, d):
    from datetime import datetime
    return datetime(y, m, d)


def _must_not_be_called(*a, **k):
    raise AssertionError("the per-project crawl must not run for a skipped project")


def _must_not_be_called_tags(*a, **k):
    raise AssertionError("no tagged media may be fetched once validation has failed")
