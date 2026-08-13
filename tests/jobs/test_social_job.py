"""Concurrency guard: social_job atomically claims a row (awaiting_social ->
publishing) so overlapping cron runs can't double-post, and releases the claim
back to awaiting_social on any non-success so the next run retries — never
stranding a row in "publishing"."""
from datetime import datetime, timedelta, timezone

import pytest

import jobs.social_job as SJ
from app.models import Base, ScheduledContent, SessionLocal, engine


@pytest.fixture(autouse=True)
def _fresh_db():
    """Wipe only the rows we touch.

    Deliberately NOT Base.metadata.drop_all(): pytest imports every test module before
    running any test, so modules that create_all at import time and then only DELETE rows
    have their tables torn out from under them by a drop_all here, failing with
    "no such table". Row deletes are order-independent. Same reasoning as
    tests/jobs/test_backfill_metadata_watermark.py and tests/api/test_portfolio.py.
    """
    Base.metadata.create_all(engine)  # idempotent; heals if another module dropped
    def _wipe():
        with SessionLocal() as db:
            db.query(ScheduledContent).delete()
            db.commit()
    _wipe()
    yield
    _wipe()


def _seed_reel(s, ref_id, status="awaiting_social"):
    s.add(ScheduledContent(
        kind="reel", ref_id=ref_id, status=status, target="instagram",
        publish_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1),
    ))


def _creds(monkeypatch):
    # Satisfy the "any creds configured" gate so the row loop actually runs.
    monkeypatch.setenv("IG_USER_ID", "test-ig")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "test-token")


def test_missing_socialpost_releases_claim_not_stuck_publishing(monkeypatch):
    """A claimed row whose SocialPost is missing (terminal skip) must be released
    back to awaiting_social, not left stranded in the intermediate 'publishing'."""
    _creds(monkeypatch)
    s = SessionLocal()
    _seed_reel(s, "999999")  # no SocialPost with this pk exists
    s.commit()
    s.close()

    result = SJ.run()

    assert result["errored"] == 1
    s = SessionLocal()
    row = s.query(ScheduledContent).one()
    s.close()
    assert row.status == "awaiting_social"  # released, NOT stuck at "publishing"


def test_non_awaiting_row_is_not_claimed(monkeypatch):
    """A row already past awaiting_social (e.g. another worker took it) is not
    selected or re-claimed — the status filter is the double-publish guard."""
    _creds(monkeypatch)
    s = SessionLocal()
    _seed_reel(s, "1", status="publishing")  # already claimed by a peer
    _seed_reel(s, "2", status="published")   # already done
    s.commit()
    s.close()

    result = SJ.run()

    assert result == {"published": 0, "skipped": 0, "errored": 0}
    s = SessionLocal()
    by_ref = {r.ref_id: r.status for r in s.query(ScheduledContent).all()}
    s.close()
    assert by_ref == {"1": "publishing", "2": "published"}  # untouched


def test_tiktok_refresh_persists_rotated_token(monkeypatch):
    """A TikTok publish with a refresh token rotates the access token AND writes the
    new access+refresh pair back to the OAuth store (else the refresh token goes stale)."""
    import jobs.social_job as SJ

    captured = {}
    monkeypatch.setattr(
        "adapters.tiktok.refresh_access_token",
        lambda **kw: {"access_token": "new-at", "refresh_token": "new-rt"},
    )
    monkeypatch.setattr("adapters.tiktok.TikTokPublisher", lambda **kw: kw)

    class _FakeStore:
        def __init__(self, tenant_id):
            captured["tenant_id"] = tenant_id

        def put(self, platform, account_id, access_token, refresh_token, **kw):
            captured["put"] = (platform, account_id, access_token, refresh_token)

    monkeypatch.setattr("adapters.distribution.oauth_store.SecretManagerOAuthStore", _FakeStore)

    pub = SJ._publisher("tiktok", {"access_token": "old-at", "open_id": "oid", "refresh_token": "old-rt"}, tenant_id=7)

    assert pub["access_token"] == "new-at"                      # publisher uses the fresh token
    # SINGLE_ACCOUNT, not the open_id ("oid"). The store's secret path is account-scoped as of
    # 2026-07-31; it previously discarded this argument, which is the only reason writing the
    # open_id here while core.social_creds read "" ever worked. Writing "oid" now would rotate
    # the token into a secret nothing reads, and the next run would reuse a stale refresh_token.
    assert captured["put"] == ("tiktok", "default", "new-at", "new-rt")
    assert captured["tenant_id"] == 7


# ---------------------------------------------------------------------------
# Per-platform copy actually reaches the platform (Jon, 2026-08-12: "wire it up")
# ---------------------------------------------------------------------------
# core.clip_select.generate_titles was never called anywhere outside tests, while the comment in
# this job said per-part hashtags "are written by" it. Nothing wrote them, so every post shipped
# with the three fixed CORE_HASHTAGS and the per-platform copy was dead code.

def test_caption_uses_the_platform_copy_when_present():
    from jobs.social_job import _caption_for

    part = {"title": "Fallback", "copy": {
        "tiktok": {"title": "Valley done right", "hashtags": ["#a", "#b", "#c"]},
        "instagram": {"title": "IG version", "hashtags": ["#x"]},
    }}
    tt = _caption_for("tiktok", part, "series")
    ig = _caption_for("instagram", part, "series")

    assert "Valley done right" in tt and "#a #b #c" in tt
    assert "IG version" in ig and "#x" in ig
    assert tt != ig, "one caption reused across platforms is the bug this fixes"


def test_caption_is_capped_to_the_platform_hashtag_count():
    """TikTok is strict. generate_titles' prompt asks for 5; nothing in parse_title_output
    enforces it, so the ceiling has to live here too."""
    from jobs.social_job import _caption_for

    part = {"copy": {"tiktok": {"title": "T", "hashtags": [f"#t{i}" for i in range(9)]}}}
    assert _caption_for("tiktok", part, "s").count("#") == 5


def test_caption_falls_back_through_flat_tags_then_core_hashtags():
    from core.clip_select import CORE_HASHTAGS
    from jobs.social_job import _caption_for

    # no copy, but flat per-part hashtags (the pre-existing shape)
    flat = _caption_for("tiktok", {"title": "T", "hashtags": ["#flat"]}, "s")
    assert "#flat" in flat

    # nothing at all -> the channel's core tags, never an empty caption (bug #343)
    bare = _caption_for("tiktok", {}, "Series Title")
    assert "Series Title" in bare
    for tag in CORE_HASHTAGS:
        assert tag in bare


def test_youtube_shorts_target_reads_the_youtube_copy_key():
    """generate_titles emits "youtube"; the target and PLATFORM_PRESETS say "youtube_shorts".
    Without the alias the copy silently falls through to CORE_HASHTAGS."""
    from jobs.social_job import _caption_for

    part = {"copy": {"youtube": {"title": "YT", "hashtags": ["#one", "#two"]}}}
    assert "YT" in _caption_for("youtube_shorts", part, "s")


def test_copy_generation_grounds_on_the_part_and_returns_per_platform(monkeypatch):
    import app.llm as llm
    from jobs.social_job import _copy_for_part

    seen = []

    def fake_chat(prompt, want_json=False):
        seen.append(prompt)
        return '{"title": "T", "hashtags": ["#a", "#b"], "description": "d"}'

    monkeypatch.setattr(llm, "chat", fake_chat)
    out = _copy_for_part({"hook": "This valley was never hemmed"}, "Valley repair")

    assert set(out) == {"youtube", "tiktok", "instagram"}
    assert out["tiktok"]["hashtags"] == ["#a", "#b"]
    assert any("This valley was never hemmed" in p for p in seen), "the hook must ground the copy"
    assert any("Valley repair" in p for p in seen)


def test_the_publish_loop_generates_caches_and_uses_per_platform_copy(monkeypatch):
    """THE SEAM. Every test above passes with the wiring removed — I checked by mutation.

    Drives a real row through _run_for_tenant and asserts three things the helpers cannot:
    generate_titles is actually CALLED, its output is PERSISTED into parts_json, and the caption
    handed to the publisher is the per-platform one.
    """
    import app.llm as llm
    from app.models import MiniSeries, SocialPost

    _creds(monkeypatch)
    monkeypatch.setattr(
        llm, "chat",
        lambda *a, **k: ('{"title": "Hemmed valley", "hashtags": '
                         '["#v1","#v2","#v3","#v4","#v5","#v6"], "description": "d"}'),
    )
    monkeypatch.setattr(SJ, "signed_get_url", lambda *a, **k: "https://signed.invalid/v.mp4",
                        raising=False)
    monkeypatch.setattr("adapters.storage.signed_get_url", lambda *a, **k: "https://x.invalid/v.mp4")

    captions: list[str] = []

    class _Pub:
        def publish(self, video_url, caption, idempotency_key):
            captions.append(caption)
            return "ext-1"

    monkeypatch.setattr(SJ, "_publisher", lambda *a, **k: _Pub())

    s = SessionLocal()
    series = MiniSeries(video_id="vid-copy", title="Series",
                        parts_json=[{"title": "P1", "start": 0.0, "end": 30.0,
                                     "hook": "This valley was never hemmed"}],
                        approved=1)
    s.add(series)
    s.flush()
    post = SocialPost(series_id=series.id, part=0, platform="instagram",
                      gcs_url="gs://b/k.mp4", status="rendered")
    s.add(post)
    s.flush()
    _seed_reel(s, str(post.id))
    s.commit()
    series_id = series.id
    s.close()

    SJ.run()

    assert captions, "nothing was published — the seam never ran"
    assert "Hemmed valley" in captions[0], captions[0]
    assert captions[0].count("#") == 4, f"instagram's limit is 4: {captions[0]!r}"

    s = SessionLocal()
    cached = (s.get(MiniSeries, series_id).parts_json or [{}])[0].get("copy")
    s.close()
    assert cached, "copy was generated but never persisted — it regenerates every run"
    assert cached["instagram"]["title"] == "Hemmed valley"


# ---------------------------------------------------------------------------
# The caption content gate now has a caller (audit item 3, 2026-08-13)
# ---------------------------------------------------------------------------
# core/caption_output.py's gate had NO production caller while its docstring claimed it was
# "wired to the publish path". status="withheld", SUSPECT_TRANSCRIPT, UNUSABLE_TRANSCRIPT and
# MISSING_LICENSE blocked exactly zero publishes.

def test_a_withheld_caption_is_blocked():
    from core.caption_output import BLOCKED
    from jobs.social_job import _publish_verdict

    part = {"copy": {"tiktok": {"title": "T", "hashtags": ["#a"], "status": "withheld",
                                "flags": []}}}
    assert _publish_verdict(part, "tiktok")[0] == BLOCKED


def test_a_block_class_flag_is_blocked():
    from core.caption_output import BLOCKED
    from jobs.social_job import _publish_verdict

    for flag in ("SUSPECT_TRANSCRIPT", "UNUSABLE_TRANSCRIPT"):
        part = {"copy": {"tiktok": {"title": "T", "status": "ok", "flags": [flag]}}}
        assert _publish_verdict(part, "tiktok")[0] == BLOCKED, flag


def test_missing_license_does_NOT_block_by_default_and_that_is_a_live_question():
    """gate_caption_flags takes require_license=False by default, so MISSING_LICENSE currently
    passes. That is the module author's chosen default and this wiring does not override it.

    ⚠️ OPEN DECISION for Jon: these posts go to public Instagram/TikTok, and the render spec can
    pull third-party music and b-roll, so an unconfirmed licence is a real copyright-strike risk.
    Flipping require_license=True in jobs.social_job._publish_verdict is a ONE-WORD change — but
    it is a legal/content policy, not an engineering call, so it was not made unilaterally. This
    test documents the current behaviour so a future flip is deliberate and visible.
    """
    from core.caption_output import OK
    from jobs.social_job import _publish_verdict

    part = {"copy": {"tiktok": {"title": "T", "status": "ok", "flags": ["MISSING_LICENSE"]}}}
    assert _publish_verdict(part, "tiktok")[0] == OK


def test_a_review_flag_still_publishes_but_is_not_silent():
    from core.caption_output import REVIEW
    from jobs.social_job import _publish_verdict

    part = {"copy": {"tiktok": {"title": "T", "status": "ok", "flags": ["NO_TECH_FACT"]}}}
    verdict, why = _publish_verdict(part, "tiktok")
    assert verdict == REVIEW and why


def test_clean_copy_and_absent_copy_both_pass():
    from core.caption_output import OK
    from jobs.social_job import _publish_verdict

    clean = {"copy": {"tiktok": {"title": "T", "status": "ok", "flags": []}}}
    assert _publish_verdict(clean, "tiktok")[0] == OK
    # No copy at all -> the fallback chain publishes series title + CORE_HASHTAGS, which carries
    # no model-authored claim to screen. Must not be blocked or nothing would ever publish.
    assert _publish_verdict({}, "tiktok")[0] == OK


def test_the_publish_loop_actually_refuses_a_blocked_caption(monkeypatch):
    """THE SEAM. A gate nothing calls is exactly the defect this fixes, so assert the PUBLISHER
    is never reached — not merely that the verdict function returns BLOCKED."""
    import app.llm as llm
    from app.models import MiniSeries, SocialPost

    _creds(monkeypatch)
    monkeypatch.setattr(
        llm, "chat",
        lambda *a, **k: '{"title":"T","hashtags":["#a"],"description":"d",'
                        '"status":"withheld","flags":["UNUSABLE_TRANSCRIPT"]}',
    )
    monkeypatch.setattr("adapters.storage.signed_get_url", lambda *a, **k: "https://x.invalid/v.mp4")

    published = []

    class _Pub:
        def publish(self, video_url, caption, idempotency_key):
            published.append(caption)
            return "ext-1"

    monkeypatch.setattr(SJ, "_publisher", lambda *a, **k: _Pub())

    s = SessionLocal()
    series = MiniSeries(video_id="vid-blocked", title="S",
                        parts_json=[{"title": "P1", "start": 0.0, "end": 30.0, "hook": "h"}],
                        approved=1)
    s.add(series)
    s.flush()
    post = SocialPost(series_id=series.id, part=0, platform="instagram",
                      gcs_url="gs://b/k.mp4", status="rendered")
    s.add(post)
    s.flush()
    _seed_reel(s, str(post.id))
    s.commit()
    s.close()

    SJ.run()

    assert published == [], "a withheld caption reached the publisher"
