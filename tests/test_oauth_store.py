"""Tests for adapters/distribution/oauth_store.py — SecretManagerOAuthStore.

Secret Manager calls are mocked throughout; no live GCP access.
The original in-memory OAuthStore is retained as MockOAuthStore and tested here too.
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# MockOAuthStore (in-memory) — retained for test isolation
# ---------------------------------------------------------------------------

def test_mock_store_put_and_get():
    """MockOAuthStore.put stores tokens; .get retrieves them."""
    from adapters.distribution.oauth_store import MockOAuthStore

    store = MockOAuthStore()
    store.put("youtube", "acc1", "tok_abc", refresh_token="ref_abc", ttl=3600)
    record = store.get("youtube", "acc1")
    assert record is not None
    assert record["access_token"] == "tok_abc"
    assert record["refresh_token"] == "ref_abc"


def test_mock_store_get_returns_none_for_missing():
    from adapters.distribution.oauth_store import MockOAuthStore

    store = MockOAuthStore()
    assert store.get("youtube", "missing") is None


def test_mock_store_get_returns_none_when_expired():
    from adapters.distribution.oauth_store import MockOAuthStore

    store = MockOAuthStore()
    store.put("youtube", "acc1", "tok", ttl=-1)  # already expired
    assert store.get("youtube", "acc1") is None


def test_mock_store_access_token_raises_on_missing():
    from adapters.distribution.oauth_store import MockOAuthStore

    store = MockOAuthStore()
    with pytest.raises(KeyError):
        store.access_token("youtube", "nonexistent")


def test_mock_store_refresh_extends_ttl():
    from adapters.distribution.oauth_store import MockOAuthStore

    store = MockOAuthStore()
    store.put("youtube", "acc1", "tok", ttl=3600)
    new_tok = store.refresh("youtube", "acc1")
    assert new_tok == "tok"
    record = store.get("youtube", "acc1")
    assert record is not None


# ---------------------------------------------------------------------------
# SecretManagerOAuthStore — mocked Secret Manager client
# ---------------------------------------------------------------------------

def _make_sm_client(secret_value: str = "tok_secret") -> MagicMock:
    """Return a mock Secret Manager client that returns *secret_value* on access."""
    client = MagicMock()
    version = MagicMock()
    version.payload.data = secret_value.encode()
    client.access_secret_version.return_value = version
    return client


def test_sm_store_access_token_calls_correct_secret_path():
    """access_token resolves to tenants/{id}/{platform}/access_token path."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = _make_sm_client("my_access_token")
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="my-proj")

    token = store.access_token("youtube", "acc1")

    assert token == "my_access_token"
    # Verify the secret name passed to access_secret_version contains the correct components,
    # INCLUDING the account segment — it used to be discarded.
    call_str = str(sm.access_secret_version.call_args)
    assert "tenants-1-youtube-acc1-access_token" in call_str


def test_sm_store_secret_name_format():
    """_secret_name produces the correct GCP secret resource path."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    store = SecretManagerOAuthStore(tenant_id=2, sm_client=sm, project="proj-123")

    name = store._secret_name("instagram", "acct7", "refresh_token")
    assert "proj-123" in name
    assert "tenants-2-instagram-acct7-refresh_token" in name
    assert "versions/latest" in name


class _FakeNotFound(Exception):
    """Local stand-in for google.api_core.exceptions.NotFound (not installed in CI)."""
    # _is_not_found() checks type name == "NotFound"
    pass

_FakeNotFound.__name__ = "NotFound"
_FakeNotFound.__qualname__ = "NotFound"


def test_sm_store_get_returns_none_on_not_found():
    """get() returns None when the Secret Manager secret does not exist."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    sm.access_secret_version.side_effect = _FakeNotFound("secret not found")

    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")
    result = store.get("tiktok", "acc2")
    assert result is None


def test_sm_store_access_token_raises_key_error_on_not_found():
    """access_token raises KeyError (same interface as MockOAuthStore) on missing secret."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    sm.access_secret_version.side_effect = _FakeNotFound("not found")

    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")
    with pytest.raises(KeyError):
        store.access_token("instagram", "acc1")


def test_sm_store_put_creates_or_updates_secret_version():
    """put() adds a new secret version via Secret Manager."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    # Secret exists (get_secret returns without raising)
    sm.get_secret.return_value = MagicMock()

    store = SecretManagerOAuthStore(tenant_id=3, sm_client=sm, project="proj")
    store.put("youtube", "acc1", access_token="new_tok", refresh_token="ref_tok")

    assert sm.add_secret_version.called


def test_sm_store_put_creates_secret_when_absent():
    """put() creates the secret first if it doesn't exist, then adds a version."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    sm.get_secret.side_effect = _FakeNotFound("no secret")

    store = SecretManagerOAuthStore(tenant_id=4, sm_client=sm, project="proj")
    store.put("facebook", "acc9", access_token="fb_tok")

    assert sm.create_secret.called
    assert sm.add_secret_version.called


def test_sm_store_tenant_id_isolation():
    """Two stores with different tenant_ids use different secret paths."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    store1 = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")
    store2 = SecretManagerOAuthStore(tenant_id=2, sm_client=sm, project="proj")

    name1 = store1._secret_name("youtube", "acc1", "access_token")
    name2 = store2._secret_name("youtube", "acc1", "access_token")

    assert "tenants-1-" in name1
    assert "tenants-2-" in name2
    assert name1 != name2


# ---------------------------------------------------------------------------
# Account scoping (2026-07-31) — the QuickBooks four-branch collision
# ---------------------------------------------------------------------------

def test_two_accounts_on_one_platform_do_not_share_a_secret():
    """The defect: account_id was accepted and discarded, so all 4 QB branches shared a token."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")

    jupiter = store._secret_name("quickbooks", "jupiter", "access_token")
    miami = store._secret_name("quickbooks", "miami", "access_token")

    assert jupiter != miami, "branch companies must not resolve to the same QuickBooks secret"
    assert "quickbooks-jupiter-access_token" in jupiter
    assert "quickbooks-miami-access_token" in miami


def test_put_writes_the_account_scoped_path():
    """A rotated token must land where the reader looks."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    sm.get_secret.return_value = MagicMock()
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")
    store.put("quickbooks", "naples", access_token="t")

    assert "tenants-1-quickbooks-naples-access_token" in str(sm.add_secret_version.call_args)


def test_legacy_unscoped_secret_is_still_readable():
    """Credentials stored before scoping must survive until that platform re-authenticates."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    legacy_value = MagicMock()
    legacy_value.payload.data = b"legacy_tok"

    def only_legacy_exists(name):
        if name.endswith("tenants-1-youtube-access_token/versions/latest"):
            return legacy_value
        raise _FakeNotFound("scoped secret not created yet")

    sm.access_secret_version.side_effect = lambda name: only_legacy_exists(name)
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")

    assert store.access_token("youtube", "default") == "legacy_tok"
    # The scoped path is tried FIRST, then the legacy one.
    assert sm.access_secret_version.call_count == 2


def test_missing_in_both_paths_raises_key_error():
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    sm.access_secret_version.side_effect = _FakeNotFound("nothing anywhere")
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")

    with pytest.raises(KeyError):
        store.access_token("youtube", "default")


def test_a_permission_error_is_not_reported_as_absent():
    """'I could not read it' must never be flattened into 'it is not configured'."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    class _Denied(Exception):
        pass

    sm = MagicMock()
    sm.access_secret_version.side_effect = _Denied("permission denied")
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")

    with pytest.raises(_Denied):
        store.access_token("youtube", "default")


def test_account_id_is_sanitised_for_gcp_secret_charset():
    """GCP secret ids allow only [A-Za-z0-9_-]; an email-ish account id must not produce one."""
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")

    name = store._secret_name("quickbooks", "books@perkins.net", "access_token")
    secret_id = name.split("/secrets/")[1].split("/versions")[0]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", secret_id), secret_id


def test_empty_account_id_normalises_rather_than_double_hyphen():
    from adapters.distribution.oauth_store import SecretManagerOAuthStore

    sm = MagicMock()
    store = SecretManagerOAuthStore(tenant_id=1, sm_client=sm, project="proj")

    assert "tenants-1-youtube-default-access_token" in store._secret_name("youtube", "", "access_token")
