"""OAuth token store — Secret Manager-backed production implementation.

TRD-F5 §4.2.

Classes:
  SecretManagerOAuthStore  — production; reads/writes GCP Secret Manager.
  MockOAuthStore           — in-memory; used in tests (renamed from OAuthStore).
  OAuthStore               — alias for MockOAuthStore for backward-compat import.

Secret naming convention (TRD-F5 §4.1):
  GCP secret name: tenants-{tenant_id}-{platform}-{key}
  (Hyphens replace slashes because GCP Secret Manager secret IDs cannot contain
  slashes. The logical path is tenants/{id}/{platform}/{key}.)

IAM note (TRD-F5 §4.3):
  The existing project-level roles/secretmanager.secretAccessor and
  roles/secretmanager.secretVersionAdder bindings on api-run-sa and jobs-sa
  already cover all secrets in the project. No new IAM bindings are needed for
  per-tenant secrets — they are runtime data, not Terraform-managed resources.
  Individual tenant secrets are created at provisioning time (F6 UI).
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MockOAuthStore (in-memory) — test double and local-dev scaffold
# ---------------------------------------------------------------------------

class MockOAuthStore:
    """In-memory token store keyed by (platform, account_id).

    Thread safety: not guaranteed (single-process / test use only).
    Retained from the original OAuthStore scaffold; renamed to Mock to make
    its role explicit. OAuthStore below is a backward-compat alias.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict] = {}

    def put(
        self,
        platform: str,
        account_id: str,
        access_token: str,
        refresh_token: str = "",
        ttl: int = 3600,
    ) -> None:
        self._store[(platform, account_id)] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + ttl,
        }

    def get(self, platform: str, account_id: str) -> dict | None:
        record = self._store.get((platform, account_id))
        if record is None:
            return None
        if record["expires_at"] < time.time():
            return None
        return record

    def access_token(self, platform: str, account_id: str) -> str:
        record = self.get(platform, account_id)
        if record is None:
            raise KeyError(f"No valid token for platform={platform!r} account={account_id!r}")
        return record["access_token"]

    def refresh(self, platform: str, account_id: str) -> str:
        record = self._store.get((platform, account_id))
        if record is None:
            raise KeyError(f"No token record for platform={platform!r} account={account_id!r}")
        record["expires_at"] = time.time() + 3600
        return record["access_token"]


# Backward-compat alias — existing callers using OAuthStore keep working.
OAuthStore = MockOAuthStore


# ---------------------------------------------------------------------------
# SecretManagerOAuthStore — production implementation
# ---------------------------------------------------------------------------

class SecretManagerOAuthStore:
    """Production OAuth token store backed by GCP Secret Manager.

    Secret paths (TRD-F5 §4.1):
      GCP secret name: tenants-{tenant_id}-{platform}-{key}
      e.g. tenants-1-youtube-access_token
           tenants-2-instagram-refresh_token

    Thread-safe: Secret Manager is the source of truth; no shared in-process state.

    Args:
        tenant_id:  Numeric tenant ID — scopes all secret paths.
        sm_client:  Optional pre-built SecretManagerServiceClient (injected in
                    tests to avoid live GCP calls). If None, a real client is
                    constructed on first use.
        project:    GCP project ID. Defaults to the GCP_PROJECT env var.
    """

    def __init__(self, tenant_id: int, sm_client=None, project: str = "") -> None:
        self._tenant_id = tenant_id
        self._client = sm_client
        self._project = project or _default_project()

    def _get_client(self):
        if self._client is None:
            from google.cloud import secretmanager  # noqa: PLC0415
            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    def _secret_name(self, platform: str, key: str) -> str:
        """Return the fully-qualified GCP secret version resource name."""
        secret_id = f"tenants-{self._tenant_id}-{platform}-{key}"
        return (
            f"projects/{self._project}/secrets/{secret_id}/versions/latest"
        )

    def _secret_parent(self) -> str:
        return f"projects/{self._project}"

    def _secret_resource(self, platform: str, key: str) -> str:
        secret_id = f"tenants-{self._tenant_id}-{platform}-{key}"
        return f"projects/{self._project}/secrets/{secret_id}"

    def get(self, platform: str, account_id: str) -> dict | None:
        """Return token record dict or None if the secret does not exist."""
        try:
            raw = self._access_secret(platform, "access_token")
        except KeyError:
            return None
        # Stored as JSON: {"access_token": ..., "refresh_token": ..., "expires_at": ...}
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            # Plain string stored (legacy put before JSON encoding was added)
            return {"access_token": raw, "refresh_token": "", "expires_at": float("inf")}
        except (json.JSONDecodeError, ValueError):
            return {"access_token": raw, "refresh_token": "", "expires_at": float("inf")}

    def access_token(self, platform: str, account_id: str) -> str:
        """Return the access token string.

        Raises:
            KeyError: if the secret is absent (mirrors MockOAuthStore interface).
        """
        return self._access_secret(platform, "access_token")

    def put(
        self,
        platform: str,
        account_id: str,
        access_token: str,
        refresh_token: str = "",
        ttl: int = 3600,
    ) -> None:
        """Store tokens as a new Secret Manager secret version.

        Creates the secret if it does not already exist.
        """
        client = self._get_client()
        secret_resource = self._secret_resource(platform, "access_token")
        secret_id = f"tenants-{self._tenant_id}-{platform}-access_token"

        payload = json.dumps({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + ttl,
        }).encode()

        # Ensure the secret exists
        try:
            client.get_secret(name=secret_resource)
        except Exception as exc:
            if _is_not_found(exc):
                client.create_secret(
                    request={
                        "parent": self._secret_parent(),
                        "secret_id": secret_id,
                        "secret": {"replication": {"automatic": {}}},
                    }
                )
            else:
                raise

        client.add_secret_version(
            request={
                "parent": secret_resource,
                "payload": {"data": payload},
            }
        )

    def refresh(self, platform: str, account_id: str) -> str:
        """Return the current access token (refresh is platform-specific; stub).

        Real platform-specific token refresh is implemented per-adapter when
        app-review credentials are available.
        """
        return self._access_secret(platform, "access_token")

    def _access_secret(self, platform: str, key: str) -> str:
        """Read a secret version value from Secret Manager.

        Raises:
            KeyError: if the secret does not exist (NotFound).
        """
        client = self._get_client()
        name = self._secret_name(platform, key)
        try:
            version = client.access_secret_version(name=name)
            return version.payload.data.decode()
        except Exception as exc:
            if _is_not_found(exc):
                raise KeyError(
                    f"No secret for tenant={self._tenant_id} platform={platform!r} key={key!r}"
                ) from exc
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_project() -> str:
    import os  # noqa: PLC0415
    return os.getenv("GCP_PROJECT", "")


def _is_not_found(exc: Exception) -> bool:
    """Return True if *exc* represents a GCP NotFound / 404 error."""
    name = type(exc).__name__
    if name == "NotFound":
        return True
    # google.api_core.exceptions.NotFound has status_code 404
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 404:
        return True
    return "NotFound" in str(type(exc).__mro__)


# ---------------------------------------------------------------------------
# Module-level singleton (production default)
# ---------------------------------------------------------------------------

_default_store: MockOAuthStore | None = None


def get_default_store() -> MockOAuthStore:
    """Return the process-level MockOAuthStore singleton (dev/test fallback)."""
    global _default_store
    if _default_store is None:
        _default_store = MockOAuthStore()
    return _default_store
