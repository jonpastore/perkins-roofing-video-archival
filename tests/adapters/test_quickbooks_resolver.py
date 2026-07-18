"""Per-branch QuickBooks credential-resolution seam (B9 scaffold).

Live QBO OAuth client is HELD (no QB/Qvinci accounts exist yet) — pins that
the resolver never silently falls back to StubQuickBooksClient. It either
raises QuickBooksUnconfigured (no credentials) or NotImplementedError (creds
present, live client construction deferred).
"""
import pytest

from adapters.distribution.oauth_store import MockOAuthStore
from adapters.quickbooks import QuickBooksUnconfigured, qb_client_for_branch


def test_no_credentials_raises_unconfigured():
    store = MockOAuthStore()
    with pytest.raises(QuickBooksUnconfigured):
        qb_client_for_branch(1, "jupiter", store=store)


def test_credentials_present_raises_not_implemented():
    store = MockOAuthStore()
    store.put("quickbooks", "jupiter", access_token="tok", refresh_token="ref")
    with pytest.raises(NotImplementedError):
        qb_client_for_branch(1, "jupiter", store=store)
