"""Regression tests for probe_companycam (integration health).

Guards the signature mismatch a review caught: the probe called list_projects(per_page=1) after
list_projects() was changed to take no args (pagination refactor) — a TypeError that would fire the
instant the CompanyCam PAT is issued. These exercise the REAL ping() path (only _get is mocked), so a
signature drift between the probe and the adapter fails here instead of at activation.
"""
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
