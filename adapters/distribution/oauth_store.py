"""In-memory OAuth token store (I/O — coverage-omitted).

SCAFFOLD: mocked — real implementation will use GCP Secret Manager per-platform/account.

In production this interface will be backed by Secret Manager secrets named:
    oauth/{platform}/{account_id}/access_token
    oauth/{platform}/{account_id}/refresh_token
    oauth/{platform}/{account_id}/expires_at

Token refresh is platform-specific and will be wired per-adapter once app-review creds arrive.
"""
from __future__ import annotations

import time


class OAuthStore:
    """In-memory token store keyed by (platform, account_id).

    SCAFFOLD: mocked — real API wiring blocked on app-review/creds.

    Thread safety: not guaranteed (single-process scaffold only).
    """

    def __init__(self) -> None:
        # { (platform, account_id): {"access_token": str, "refresh_token": str, "expires_at": float} }
        self._store: dict[tuple[str, str], dict] = {}

    def put(self, platform: str, account_id: str, access_token: str, refresh_token: str = "", ttl: int = 3600) -> None:
        """Store tokens for *platform* / *account_id*.

        Args:
            platform:      Platform key, e.g. ``"youtube_shorts"``.
            account_id:    Opaque account identifier.
            access_token:  OAuth access token.
            refresh_token: Long-lived refresh token (optional for platforms that don't use one).
            ttl:           Seconds until the access token expires (default 3600).
        """
        self._store[(platform, account_id)] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + ttl,
        }

    def get(self, platform: str, account_id: str) -> dict | None:
        """Return the stored token record or *None* if not found / expired."""
        record = self._store.get((platform, account_id))
        if record is None:
            return None
        if record["expires_at"] < time.time():
            # Treat as absent — caller must refresh
            return None
        return record

    def access_token(self, platform: str, account_id: str) -> str:
        """Return the access token string.

        Raises:
            KeyError: if the token is absent or expired.
        """
        record = self.get(platform, account_id)
        if record is None:
            raise KeyError(f"No valid token for platform={platform!r} account={account_id!r}")
        return record["access_token"]

    def refresh(self, platform: str, account_id: str) -> str:
        """SCAFFOLD: mock refresh — returns the existing access token unchanged.

        Real implementation: call the platform token-refresh endpoint, update
        Secret Manager, and return the new access token.
        """
        record = self._store.get((platform, account_id))
        if record is None:
            raise KeyError(f"No token record for platform={platform!r} account={account_id!r}")
        # Mock: extend TTL and return same token
        record["expires_at"] = time.time() + 3600
        return record["access_token"]


# Module-level singleton used by the distribution driver
_default_store: OAuthStore | None = None


def get_default_store() -> OAuthStore:
    """Return the process-level OAuthStore singleton."""
    global _default_store
    if _default_store is None:
        _default_store = OAuthStore()
    return _default_store
