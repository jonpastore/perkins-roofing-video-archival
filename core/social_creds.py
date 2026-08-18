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
# A tuple means first-set wins (facebook page token, else the Meta system-user token).
_ENV_REQUIRED: dict[str, dict[str, str | tuple[str, ...]]] = {
    "instagram": {"ig_user_id": "IG_USER_ID", "access_token": "META_SYSTEM_USER_TOKEN"},
    "tiktok": {"access_token": "TIKTOK_ACCESS_TOKEN", "open_id": "TIKTOK_OPEN_ID"},
    "facebook": {
        "access_token": ("FACEBOOK_PAGE_TOKEN", "META_SYSTEM_USER_TOKEN"),
        "page_id": "FACEBOOK_PAGE_ID",
    },
    "linkedin": {"access_token": "LINKEDIN_ACCESS_TOKEN"},
    "x": {"access_token": "X_ACCESS_TOKEN"},
    "pinterest": {"access_token": "PINTEREST_ACCESS_TOKEN", "board_id": "PINTEREST_BOARD_ID"},
    "youtube_shorts": {"access_token": "YOUTUBE_ACCESS_TOKEN"},
}
# Optional env vars — included when set, never required.
_ENV_OPTIONAL: dict[str, dict[str, str]] = {
    "tiktok": {"refresh_token": "TIKTOK_REFRESH_TOKEN"},
    "linkedin": {"author_urn": "LINKEDIN_AUTHOR_URN"},
}
# Connect writes youtube tokens under platform "youtube"; the publish target is youtube_shorts.
_STORE_PLATFORM: dict[str, str] = {"youtube_shorts": "youtube"}


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
        from adapters.distribution.oauth_store import (  # noqa: PLC0415
            SINGLE_ACCOUNT,
            SecretManagerOAuthStore,
        )
        # The store's secret path IS account-scoped as of 2026-07-31 (it used to discard this
        # argument, which is why "" worked). Must match what the OAuth callback writes.
        store_platform = _STORE_PLATFORM.get(platform, platform)
        return SecretManagerOAuthStore(tenant_id=tenant_id).get(store_platform, SINGLE_ACCOUNT)
    except Exception as exc:  # noqa: BLE001 — resilient: fall back to env, don't leak values
        logger.warning("social_creds: store lookup failed for %s (%s); trying env", platform, type(exc).__name__)
        return None


def _env_get(env_name: str | tuple[str, ...]) -> str | None:
    names = env_name if isinstance(env_name, tuple) else (env_name,)
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _from_env(platform: str) -> dict:
    required = _ENV_REQUIRED.get(platform)
    if not required:
        return {}
    out: dict = {}
    for key, env_name in required.items():
        value = _env_get(env_name)
        if not value:
            return {}  # a required key is missing → not configured; never a partial dict
        out[key] = value
    for key, env_name in _ENV_OPTIONAL.get(platform, {}).items():
        value = os.environ.get(env_name)
        if value:
            out[key] = value
    return out
