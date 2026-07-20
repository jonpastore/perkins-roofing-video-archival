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
