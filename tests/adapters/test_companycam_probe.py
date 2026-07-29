"""Regression tests for probe_companycam (integration health).

Guards the signature mismatch a review caught: the probe called list_projects(per_page=1) after
list_projects() was changed to take no args (pagination refactor) — a TypeError that would fire the
instant the CompanyCam PAT is issued. These exercise the REAL ping() path (only _get is mocked), so a
signature drift between the probe and the adapter fails here instead of at activation.
"""
import pytest

import adapters.companycam as companycam
from adapters.integration_probes import probe_companycam


def test_probe_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("COMPANYCAM_PAT", raising=False)
    assert probe_companycam() is None


def test_probe_ok_when_ping_succeeds(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PAT", "tok")
    monkeypatch.setattr(companycam, "_get", lambda url, params=None: [])  # no network
    result = probe_companycam()
    assert result is not None and result.ok is True


def test_probe_hard_auth_failure_on_401(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PAT", "tok")

    def _boom(url, params=None):
        raise RuntimeError("CompanyCam API error 401: invalid token")

    monkeypatch.setattr(companycam, "_get", _boom)
    result = probe_companycam()
    assert result is not None and result.ok is False and result.hard_auth_failure is True


# --- video pull (live shape captured 2026-07-28) --------------------------------

_LIVE_VIDEO = {
    "id": "20914302", "company_id": "766295", "project_id": "109944476",
    "creator_name": "Josh  Kaufman", "status": "processed", "internal": False,
    "captured_at": 1784203045, "created_at": 1784203064,
    "coordinates": {"lat": 25.8074076646624, "lon": -80.32583199918818},
    "playback_url": "https://companycam-video.s3.amazonaws.com/43f526ff.mov",
    "format": "m3u8",
    "thumbnail_urls": {"large": "https://img.companycam.com/L/x", "medium": "https://img.companycam.com/M/x",
                       "small": "https://img.companycam.com/S/x"},
}


def test_normalize_video_maps_the_live_payload():
    from adapters.companycam import normalize_video
    v = normalize_video(_LIVE_VIDEO)
    assert v["companycam_video_id"] == "20914302"
    assert v["project_id"] == "109944476"
    # playback_url, NOT the photo-style uris[] list.
    assert v["url"] == "https://companycam-video.s3.amazonaws.com/43f526ff.mov"
    assert v["thumbnail_url"] == "https://img.companycam.com/L/x"
    assert v["lat"] and v["lon"]
    assert v["internal"] is False


def test_normalize_video_prefers_large_then_falls_back():
    from adapters.companycam import normalize_video
    only_small = {**_LIVE_VIDEO, "thumbnail_urls": {"small": "https://img/S"}}
    assert normalize_video(only_small)["thumbnail_url"] == "https://img/S"
    none_at_all = {**_LIVE_VIDEO, "thumbnail_urls": {}}
    assert normalize_video(none_at_all)["thumbnail_url"] is None


def test_normalize_video_flags_internal_media():
    """Internal media must never reach a proposal or a public project page."""
    from adapters.companycam import normalize_video
    assert normalize_video({**_LIVE_VIDEO, "internal": True})["internal"] is True


def test_videos_url_is_a_separate_resource_from_photos():
    from core.companycam.rest import photos_url, videos_url
    assert videos_url("123").endswith("/projects/123/videos")
    assert videos_url("123") != photos_url("123")


# --- pagination ------------------------------------------------------------
# /v2/projects silently caps per_page at 50. Asking for 100 and treating the 50 that come
# back as "the last page" mirrored only the first 50 projects of the account and looked
# entirely successful — 11 of 13 portfolio candidates were missing because of it.

def test_get_all_does_not_stop_on_a_short_page(monkeypatch):
    """The server may cap per_page below what we asked for. Only an EMPTY page ends it."""
    pages = {1: [{"id": f"a{i}"} for i in range(50)],
             2: [{"id": f"b{i}"} for i in range(50)],
             3: [{"id": "c0"}],
             4: []}
    monkeypatch.setattr(companycam, "_get", lambda url, params: pages[params["page"]])
    assert len(companycam._get_all("http://x", per_page=100)) == 101


def test_get_all_stops_on_the_first_empty_page(monkeypatch):
    calls = []

    def fake_get(url, params):
        calls.append(params["page"])
        return [{"id": "only"}] if params["page"] == 1 else []

    monkeypatch.setattr(companycam, "_get", fake_get)
    assert len(companycam._get_all("http://x")) == 1
    assert calls == [1, 2], "one extra request confirms the end; it must not keep going"


def test_get_all_raises_when_the_endpoint_ignores_the_page_param(monkeypatch):
    """Returning page 1 forever would otherwise loop until _MAX_PAGES, duplicating rows."""
    monkeypatch.setattr(companycam, "_get", lambda url, params: [{"id": "same"}])
    with pytest.raises(RuntimeError, match="ignoring the page param"):
        companycam._get_all("http://x")


def test_get_all_raises_rather_than_truncating_at_the_page_cap(monkeypatch):
    monkeypatch.setattr(companycam, "_MAX_PAGES", 3)
    monkeypatch.setattr(companycam, "_get",
                        lambda url, params: [{"id": f"p{params['page']}-{i}"} for i in range(50)])
    with pytest.raises(RuntimeError, match="exceeded 3 pages"):
        companycam._get_all("http://x")


def test_a_404_on_a_project_sub_resource_is_empty_not_an_error(monkeypatch):
    """4 of 3,684 real projects 404 on /videos while appearing in the project list. Counting
    that as an error made the job exit 1, retry to the cap, and never stamp those projects —
    so they re-failed on every run, forever."""
    def not_found(url, params=None):
        raise companycam.CompanyCamNotFound("CompanyCam API error 404: not found")

    monkeypatch.setattr(companycam, "_get", not_found)
    assert companycam.list_videos("38534163") == []
    assert companycam.list_photos("38534163") == []


def test_other_http_errors_still_raise(monkeypatch):
    """A 500 is a real failure — swallowing it would silently shrink the mirror."""
    def boom(url, params=None):
        raise RuntimeError("CompanyCam API error 500: server error")

    monkeypatch.setattr(companycam, "_get", boom)
    with pytest.raises(RuntimeError, match="500"):
        companycam.list_videos("1")
