"""creds_for resolves store-first, env-second, {} when neither."""
from __future__ import annotations

import core.social_creds as SC


class _FakeStore:
    def __init__(self, rec):
        self._rec = rec

    def __call__(self, tenant_id):  # constructed as SecretManagerOAuthStore(tenant_id=...)
        return self

    def get(self, platform, account_id):
        return self._rec


def _patch_store(monkeypatch, rec):
    fake = _FakeStore(rec)
    monkeypatch.setattr(
        "adapters.distribution.oauth_store.SecretManagerOAuthStore",
        lambda tenant_id: fake,
    )


def test_store_hit_wins_over_env(monkeypatch):
    _patch_store(monkeypatch, {"access_token": "from-store"})
    monkeypatch.setenv("IG_USER_ID", "envid")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "envtok")
    assert SC.creds_for("instagram", 1) == {"access_token": "from-store"}


def test_env_fallback_when_store_empty(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("IG_USER_ID", "envid")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "envtok")
    assert SC.creds_for("instagram", 1) == {"ig_user_id": "envid", "access_token": "envtok"}


def test_tiktok_optional_refresh_included_when_set(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "at")
    monkeypatch.setenv("TIKTOK_OPEN_ID", "oid")
    monkeypatch.setenv("TIKTOK_REFRESH_TOKEN", "rt")
    assert SC.creds_for("tiktok", 2) == {"access_token": "at", "open_id": "oid", "refresh_token": "rt"}


def test_partial_env_yields_empty(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("IG_USER_ID", "envid")  # META_SYSTEM_USER_TOKEN missing
    monkeypatch.delenv("META_SYSTEM_USER_TOKEN", raising=False)
    assert SC.creds_for("instagram", 1) == {}


def test_nothing_configured_returns_empty(monkeypatch):
    _patch_store(monkeypatch, None)
    for v in ("IG_USER_ID", "META_SYSTEM_USER_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    assert SC.creds_for("instagram", 1) == {}


def test_facebook_env_prefers_page_token_over_meta(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "page-1")
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "page-tok")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "meta-tok")
    assert SC.creds_for("facebook", 1) == {
        "access_token": "page-tok",
        "page_id": "page-1",
    }


def test_facebook_env_falls_back_to_meta_token(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "page-1")
    monkeypatch.delenv("FACEBOOK_PAGE_TOKEN", raising=False)
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "meta-tok")
    assert SC.creds_for("facebook", 1) == {
        "access_token": "meta-tok",
        "page_id": "page-1",
    }


def test_facebook_missing_page_id_is_unconfigured(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.delenv("FACEBOOK_PAGE_ID", raising=False)
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "page-tok")
    assert SC.creds_for("facebook", 1) == {}


def test_linkedin_optional_author_urn(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "li-at")
    monkeypatch.delenv("LINKEDIN_AUTHOR_URN", raising=False)
    assert SC.creds_for("linkedin", 1) == {"access_token": "li-at"}
    monkeypatch.setenv("LINKEDIN_AUTHOR_URN", "urn:li:person:9")
    assert SC.creds_for("linkedin", 1) == {
        "access_token": "li-at",
        "author_urn": "urn:li:person:9",
    }


def test_x_and_pinterest_env(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("X_ACCESS_TOKEN", "x-at")
    assert SC.creds_for("x", 1) == {"access_token": "x-at"}
    monkeypatch.setenv("PINTEREST_ACCESS_TOKEN", "pin-at")
    monkeypatch.delenv("PINTEREST_BOARD_ID", raising=False)
    assert SC.creds_for("pinterest", 1) == {}
    monkeypatch.setenv("PINTEREST_BOARD_ID", "board-1")
    assert SC.creds_for("pinterest", 1) == {
        "access_token": "pin-at",
        "board_id": "board-1",
    }


def test_youtube_shorts_reads_youtube_store(monkeypatch):
    seen = []

    class _Store:
        def get(self, platform, account_id):
            seen.append((platform, account_id))
            if platform == "youtube":
                return {"access_token": "yt-at"}
            return None

    monkeypatch.setattr(
        "adapters.distribution.oauth_store.SecretManagerOAuthStore",
        lambda tenant_id: _Store(),
    )
    assert SC.creds_for("youtube_shorts", 3) == {"access_token": "yt-at"}
    assert ("youtube", "default") in seen


def test_unconfigured_new_platform_is_empty(monkeypatch):
    _patch_store(monkeypatch, None)
    for v in (
        "FACEBOOK_PAGE_ID",
        "FACEBOOK_PAGE_TOKEN",
        "LINKEDIN_ACCESS_TOKEN",
        "X_ACCESS_TOKEN",
        "PINTEREST_ACCESS_TOKEN",
        "PINTEREST_BOARD_ID",
        "YOUTUBE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(v, raising=False)
    assert SC.creds_for("facebook", 1) == {}
    assert SC.creds_for("linkedin", 1) == {}
    assert SC.creds_for("x", 1) == {}
    assert SC.creds_for("pinterest", 1) == {}
    assert SC.creds_for("youtube_shorts", 1) == {}
    assert SC.creds_for("myspace", 1) == {}


def test_store_exception_falls_back_to_env(monkeypatch):
    def _boom(tenant_id):
        raise RuntimeError("gsm down")

    monkeypatch.setattr(
        "adapters.distribution.oauth_store.SecretManagerOAuthStore", _boom,
    )
    monkeypatch.setenv("IG_USER_ID", "envid")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "envtok")
    assert SC.creds_for("instagram", 1) == {"ig_user_id": "envid", "access_token": "envtok"}


def test_youtube_shorts_env_fallback(monkeypatch):
    _patch_store(monkeypatch, None)
    monkeypatch.setenv("YOUTUBE_ACCESS_TOKEN", "yt-env")
    assert SC.creds_for("youtube_shorts", 1) == {"access_token": "yt-env"}
