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
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


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
    assert captured["put"] == ("tiktok", "oid", "new-at", "new-rt")  # rotated pair persisted
    assert captured["tenant_id"] == 7
