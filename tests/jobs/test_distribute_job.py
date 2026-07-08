"""Behavioral tests for the distribute_job flag-gate wiring (jobs/ are coverage-omitted)."""
from adapters.distribution.oauth_store import OAuthStore
from jobs import distribute_job

_BLOCKED_RAW = """FLAGS: MISSING_LICENSE
CAPTION:
Great roof work in South Florida.
HASHTAGS: #roofing"""

_CLEAN_RAW = """FLAGS: NONE
CAPTION:
Your roof fails at the fasteners first.
HASHTAGS: #roofing #southflorida"""


def test_missing_license_blocks_all_destinations():
    # require_license=True + MISSING_LICENSE flag → every destination FAILED, no publish attempted.
    results = distribute_job.distribute(
        video_url="https://x/clip.mp4",
        destinations=["youtube_shorts", "facebook"],
        raw_caption_output=_BLOCKED_RAW,
        require_license=True,
    )
    assert [r.status for r in results] == ["FAILED", "FAILED"]
    assert all("blocked" in r.error for r in results)


def test_clean_raw_caption_publishes(monkeypatch):
    # Clean flags → the parsed caption is used and the post publishes (Track E gate stubbed to pass).
    class _Pass:
        passed = True
        reason = ""
    monkeypatch.setattr("adapters.safety.run_gate", lambda text, kind: _Pass())

    store = OAuthStore()
    store.put("youtube_shorts", "default", access_token="tok", ttl=3600)
    results = distribute_job.distribute(
        video_url="https://x/clip.mp4",
        destinations=["youtube_shorts"],
        raw_caption_output=_CLEAN_RAW,
        oauth_store=store,
    )
    assert results[0].status == "PUBLISHED"
    assert results[0].post_id


def test_missing_license_ignored_when_not_required(monkeypatch):
    class _Pass:
        passed = True
        reason = ""
    monkeypatch.setattr("adapters.safety.run_gate", lambda text, kind: _Pass())
    store = OAuthStore()
    store.put("youtube_shorts", "default", access_token="tok", ttl=3600)
    results = distribute_job.distribute(
        video_url="https://x/clip.mp4",
        destinations=["youtube_shorts"],
        raw_caption_output=_BLOCKED_RAW,   # has MISSING_LICENSE but require_license defaults False
        oauth_store=store,
    )
    assert results[0].status == "PUBLISHED"
