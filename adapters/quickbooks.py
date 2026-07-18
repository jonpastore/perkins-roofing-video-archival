"""Per-branch QuickBooks credential-resolution seam (B9 scaffold).

Tim runs 4 companies / 4 Knowify subs / 4 QuickBooks subs, mapped at the BRANCH
level. The live QBO OAuth client is HELD (no QB/Qvinci accounts exist yet) — this
module resolves per-branch OAuth credentials from the store but never constructs
a live client. Once accounts exist, the live QBO client (implementing the
QuickBooksSyncClient Protocol from adapters/quickbooks_stub.py) drops in behind
qb_client_for_branch() without changing any caller.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from adapters.quickbooks_stub import QuickBooksSyncClient
    from app.models import BranchAccounting


class QuickBooksUnconfigured(Exception):
    """Raised when a branch has no QuickBooks OAuth credentials stored yet."""


def qb_client_for_branch(tenant_id: int, branch: str, *, store=None) -> "QuickBooksSyncClient":
    """Resolve the per-branch QuickBooks client.

    Looks up OAuth credentials for (tenant, branch) in the token store (default
    SecretManagerOAuthStore, platform="quickbooks", account_id=branch). If no
    credentials are stored, raises QuickBooksUnconfigured — there is nothing to
    resolve yet. If credentials ARE present, the live QBO client is still HELD
    (no QB/Qvinci accounts exist), so this raises NotImplementedError rather than
    silently falling back to the hermetic StubQuickBooksClient — that stub is
    test-only and must never be returned from a production resolution path.
    """
    if store is None:
        from adapters.distribution.oauth_store import SecretManagerOAuthStore
        store = SecretManagerOAuthStore(tenant_id)

    creds = store.get("quickbooks", branch)
    if creds is None:
        raise QuickBooksUnconfigured(f"no QuickBooks credentials for branch {branch!r}")

    raise NotImplementedError(
        "live QuickBooks client is deferred (B10/account); credentials resolved for branch "
        + branch
    )


def branch_qb_mapping(db: "Session", branch: str) -> "BranchAccounting | None":
    """Fetch the BranchAccounting row for the current tenant + branch, or None."""
    from sqlalchemy import select

    from app.models import BranchAccounting

    return db.execute(
        select(BranchAccounting).where(BranchAccounting.branch == branch)
    ).scalar_one_or_none()
