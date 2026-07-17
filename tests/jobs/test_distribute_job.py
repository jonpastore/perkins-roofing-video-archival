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


_V5_RAW = """{"prompt_version": "v5", "status": "ok", "flags": [],
"platform_used": "instagram", "hook_structure": "question", "tone": "expert",
"caption": "Your roof fails at the fasteners first.",
"hashtags": ["#MiamiRoofing", "#TileRoof"], "word_count": 7}"""


def test_published_caption_includes_v5_hashtags(monkeypatch):
    # Bug #343: parts.hashtags was discarded — the v5 contract keeps hashtags OUT of
    # the caption field, so publish must re-join them or posts ship with none.
    captured = {}

    class _Pass:
        passed = True
        reason = ""

    def _capture_gate(text, kind):
        captured["caption"] = text
        return _Pass()

    monkeypatch.setattr("adapters.safety.run_gate", _capture_gate)
    store = OAuthStore()
    store.put("youtube_shorts", "default", access_token="tok", ttl=3600)
    results = distribute_job.distribute(
        video_url="https://x/clip.mp4",
        destinations=["youtube_shorts"],
        raw_caption_output=_V5_RAW,
        oauth_store=store,
    )
    assert results[0].status == "PUBLISHED"
    assert captured["caption"].startswith("Your roof fails at the fasteners first.")
    assert "#MiamiRoofing #TileRoof" in captured["caption"]


def test_published_caption_includes_v3_line_hashtags(monkeypatch):
    # v3 line format carries hashtags as one string — must also survive to publish.
    captured = {}

    class _Pass:
        passed = True
        reason = ""

    def _capture_gate(text, kind):
        captured["caption"] = text
        return _Pass()

    monkeypatch.setattr("adapters.safety.run_gate", _capture_gate)
    store = OAuthStore()
    store.put("youtube_shorts", "default", access_token="tok", ttl=3600)
    results = distribute_job.distribute(
        video_url="https://x/clip.mp4",
        destinations=["youtube_shorts"],
        raw_caption_output=_CLEAN_RAW,   # HASHTAGS: #roofing #southflorida
        oauth_store=store,
    )
    assert results[0].status == "PUBLISHED"
    assert "#roofing #southflorida" in captured["caption"]
