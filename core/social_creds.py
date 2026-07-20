"""Single credential resolver for the social publisher.

The OAuth connect flow (api/routes/connections.py) writes tokens to
SecretManagerOAuthStore. Historically social_job read creds from env vars only, so a
connected account never actually fed the publisher. This resolver closes that gap:
**store first, env second**. Env stays as the fallback for Instagram's permanent
System-User token model (not per-user OAuth).

Security: never log secret values; a store lookup error falls back to env rather than
raising, and a missing required key yields {} ("not configured"), never a partial dict.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Required env vars per platform — env fallback is used only when ALL are present.
_ENV_REQUIRED: dict[str, dict[str, str]] = {
    "instagram": {"ig_user_id": "IG_USER_ID", "access_token": "META_SYSTEM_USER_TOKEN"},
    "tiktok": {"access_token": "TIKTOK_ACCESS_TOKEN", "open_id": "TIKTOK_OPEN_ID"},
}
# Optional env vars — included when set, never required.
_ENV_OPTIONAL: dict[str, dict[str, str]] = {
    "tiktok": {"refresh_token": "TIKTOK_REFRESH_TOKEN"},
}


def creds_for(platform: str, tenant_id: int) -> dict:
    """Resolve publishing creds for a platform+tenant.

    Returns the OAuth-store token record (what the connect flow persists) when present,
    otherwise the env fallback, otherwise {} (caller treats {} as "not configured").
    """
    rec = _from_store(platform, tenant_id)
    if rec and rec.get("access_token"):
        return rec
    return _from_env(platform)


def _from_store(platform: str, tenant_id: int) -> dict | None:
    try:
        from adapters.distribution.oauth_store import SecretManagerOAuthStore  # noqa: PLC0415
        # account_id is unused by the store's secret path (tenant+platform keyed).
        return SecretManagerOAuthStore(tenant_id=tenant_id).get(platform, "")
    except Exception as exc:  # noqa: BLE001 — resilient: fall back to env, don't leak values
        logger.warning("social_creds: store lookup failed for %s (%s); trying env", platform, type(exc).__name__)
        return None


def _from_env(platform: str) -> dict:
    required = _ENV_REQUIRED.get(platform)
    if not required:
        return {}
    out: dict = {}
    for key, env_name in required.items():
        value = os.environ.get(env_name)
        if not value:
            return {}  # a required key is missing → not configured; never a partial dict
        out[key] = value
    for key, env_name in _ENV_OPTIONAL.get(platform, {}).items():
        value = os.environ.get(env_name)
        if value:
            out[key] = value
    return out
