"""Connections + self-service OAuth capture routes (plan 2026-07-17 Phase 1.5).

Three surfaces:
  GET  /connections                       — integration status list for the Connections page.
  POST /connections/{integration}/secret  — re-enter a non-OAuth secret (new SM version).
  GET  /oauth/{platform}/start            — mint signed state + nonce, return provider auth_url.
  GET  /oauth/{platform}/callback         — UNAUTHENTICATED provider redirect: validate
                                            signature → exp → burn nonce (atomic) → registry →
                                            exchange code server-side → SecretManagerOAuthStore.

Security model (consensus plan, Architect H3): the callback carries no bearer token —
the signed state (core/oauth_state) plus the single-use persisted nonce ARE the tenant
binding. Tokens never reach the browser; the exchange happens server-side and lands in
per-tenant Secret Manager. /start is gated require_role_db (tenant-scoped claims — the
legacy require_role would default tenant_id=1 and mis-bind).

HMAC keys arrive as env (deploy.sh --set-secrets, `oauth-state-hmac`):
OAUTH_STATE_HMAC_KEY (current) + optional OAUTH_STATE_HMAC_KEY_PREV (rotation window).
"""
from __future__ import annotations

import logging
import os
import secrets as pysecrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import text as sqltext

from api.auth import require_role_db
from core.integration_health import STATUSES  # noqa: F401 — documents the status vocabulary
from core.oauth_state import DEFAULT_STATE_TTL_SECONDS, sign_state, verify_state

log = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Fixed provider registry — {platform} path segments MUST match a key here.
# client env names follow the repo's secret-injection pattern (scripts/deploy.sh).
# Platforms without registered apps (#319) stay listed but unconfigured until
# their client creds exist; /start answers 503 for them, never a broken redirect.
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict] = {
    "youtube": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": "https://www.googleapis.com/auth/youtube.force-ssl",
        "client_id_env": "OAUTH_CLIENT_ID",
        "client_secret_env": "OAUTH_CLIENT_SECRET",
        "extra_auth_params": {"access_type": "offline", "prompt": "consent"},
    },
    "tiktok": {
        "auth_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "scopes": "video.publish",
        "client_id_env": "TIKTOK_CLIENT_KEY",
        "client_secret_env": "TIKTOK_CLIENT_SECRET",
        "extra_auth_params": {},
    },
    "instagram": {
        "auth_url": "https://www.facebook.com/v21.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v21.0/oauth/access_token",
        "scopes": "instagram_business_basic,instagram_business_content_publish",
        "client_id_env": "META_APP_ID",
        "client_secret_env": "META_APP_SECRET",
        "extra_auth_params": {},
    },
    "facebook": {
        "auth_url": "https://www.facebook.com/v21.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v21.0/oauth/access_token",
        "scopes": "pages_manage_posts,pages_read_engagement",
        "client_id_env": "META_APP_ID",
        "client_secret_env": "META_APP_SECRET",
        "extra_auth_params": {},
    },
    "linkedin": {
        "auth_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "scopes": "w_member_social",
        "client_id_env": "LINKEDIN_CLIENT_ID",
        "client_secret_env": "LINKEDIN_CLIENT_SECRET",
        "extra_auth_params": {},
    },
    "x": {
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scopes": "tweet.read tweet.write users.read offline.access",
        "client_id_env": "X_CLIENT_ID",
        "client_secret_env": "X_CLIENT_SECRET",
        "extra_auth_params": {},
    },
}

# Non-OAuth secrets the re-enter form may rotate (integration → SM secret id).
# Deliberate allowlist — an arbitrary secret_id from the client would be a
# privilege hole (rotating internal-secret, db-password, ...).
SECRET_TARGETS: dict[str, str] = {
    "wordpress": "wordpress-app-password",
    "resend": "resend-api-key",
    "pexels": "pexels-api-key",
    "serper": "serper-api-key",
    "youtube_api_key": "youtube-api-key",
}


def _hmac_keys() -> list[bytes]:
    """Current + optional previous HMAC key from env (two-key rotation window)."""
    keys = []
    cur = os.getenv("OAUTH_STATE_HMAC_KEY", "")
    prev = os.getenv("OAUTH_STATE_HMAC_KEY_PREV", "")
    if cur:
        keys.append(cur.encode("utf-8"))
    if prev:
        keys.append(prev.encode("utf-8"))
    return keys


def _redirect_base() -> str:
    """Exact-match redirect base (e.g. https://api-....run.app). Unset = flow off."""
    return os.getenv("OAUTH_REDIRECT_BASE", "").rstrip("/")


def _platform_db():
    """Short-lived platform-scoped session for the no-RLS tables (0039)."""
    from app.models import PlatformSessionLocal  # noqa: PLC0415
    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    return db


# ---------------------------------------------------------------------------
# GET /connections — status list for the Connections page
# ---------------------------------------------------------------------------

@router.get("/connections")
def list_connections(claims: dict = Depends(require_role_db("manage_config"))):
    """Every known integration with its live status (shared rows + caller's tenant rows).

    Registry platforms with no status row yet appear as 'unconfigured' so the UI
    always renders the full set with Connect buttons.
    """
    from app.models import IntegrationStatus  # noqa: PLC0415

    tenant_id = claims.get("tenant_id")
    db = _platform_db()
    try:
        q = db.query(IntegrationStatus)
        rows = [
            r for r in q.all()
            if r.tenant_id is None or r.tenant_id == tenant_id
        ]
    finally:
        db.close()

    by_key = {r.integration: r for r in rows}
    out = []
    known = set(PROVIDERS) | set(SECRET_TARGETS) | {r.integration for r in rows}
    for integration in sorted(known):
        r = by_key.get(integration)
        provider = PROVIDERS.get(integration)
        out.append({
            "integration": integration,
            "status": r.status if r else "unconfigured",
            "shared": bool(r and r.tenant_id is None),
            "last_checked": r.last_checked.isoformat() if r and r.last_checked else None,
            "last_ok": r.last_ok.isoformat() if r and r.last_ok else None,
            "last_error": r.last_error if r else None,
            "oauth": provider is not None,
            "oauth_configured": bool(
                provider and os.getenv(provider["client_id_env"]) and _redirect_base()
            ),
            "secret_reenter": integration in SECRET_TARGETS,
        })
    return {"connections": out}


# ---------------------------------------------------------------------------
# POST /connections/{integration}/secret — re-enter a non-OAuth secret
# ---------------------------------------------------------------------------

class SecretBody(BaseModel):
    value: str


@router.post("/connections/{integration}/secret")
def reenter_secret(
    integration: str,
    body: SecretBody,
    _claims: dict = Depends(require_role_db("manage_config")),
):
    """Write a new Secret Manager version for an allowlisted non-OAuth secret.

    Mirrors the Config-UI precedent: new revisions read ':latest', so no redeploy.
    The status row's last_checked is cleared so the next health cycle re-probes.
    """
    secret_id = SECRET_TARGETS.get(integration)
    if secret_id is None:
        raise HTTPException(status_code=404, detail=f"unknown re-enterable secret {integration!r}")
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="empty secret value")

    from api.routes.config import _gcp_project, _secret_manager_client  # noqa: PLC0415
    try:
        client = _secret_manager_client()
        project = _gcp_project()
        client.add_secret_version(
            request={
                "parent": f"projects/{project}/secrets/{secret_id}",
                "payload": {"data": value.encode("utf-8")},
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.error("reenter_secret: SM write failed for %s: %s", secret_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="secret write failed") from exc

    from app.models import IntegrationStatus  # noqa: PLC0415
    db = _platform_db()
    try:
        row = (
            db.query(IntegrationStatus)
            .filter(IntegrationStatus.integration == integration,
                    IntegrationStatus.tenant_id.is_(None))
            .first()
        )
        if row is not None:
            row.last_checked = None  # force re-probe next cycle
            db.commit()
    finally:
        db.close()
    return {"ok": True, "secret_id": secret_id}


# ---------------------------------------------------------------------------
# GET /oauth/{platform}/start — mint state, return provider auth_url
# ---------------------------------------------------------------------------

@router.get("/oauth/{platform}/start")
def oauth_start(
    platform: str,
    claims: dict = Depends(require_role_db("manage_config")),
):
    """Begin the capture flow: persist a single-use nonce, mint signed state, and
    return the provider consent URL for the SPA to navigate to.

    Returns JSON (not a redirect): the SPA calls this with its bearer token via
    fetch — a top-level browser navigation could not carry the Authorization
    header — then sets window.location to auth_url.
    """
    provider = PROVIDERS.get(platform)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"unknown platform {platform!r}")
    client_id = os.getenv(provider["client_id_env"], "")
    base = _redirect_base()
    if not client_id or not base or not _hmac_keys():
        raise HTTPException(
            status_code=503,
            detail=f"{platform} OAuth not configured (client credentials / redirect base / state key)",
        )
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="no tenant context")

    from app.models import OAuthStateNonce  # noqa: PLC0415

    nonce = pysecrets.token_urlsafe(32)
    exp = int(time.time()) + DEFAULT_STATE_TTL_SECONDS
    db = _platform_db()
    try:
        db.add(OAuthStateNonce(
            nonce=nonce, tenant_id=tenant_id, platform=platform,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(seconds=DEFAULT_STATE_TTL_SECONDS),
        ))
        db.commit()
    finally:
        db.close()

    state = sign_state(
        tenant_id=tenant_id, platform=platform, nonce=nonce, exp=exp,
        key=_hmac_keys()[0],
    )
    redirect_uri = f"{base}/oauth/{platform}/callback"
    from urllib.parse import urlencode  # noqa: PLC0415
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider["scopes"],
        "state": state,
        **provider["extra_auth_params"],
    }
    return {"auth_url": f"{provider['auth_url']}?{urlencode(params)}"}


# ---------------------------------------------------------------------------
# GET /oauth/{platform}/callback — UNAUTHENTICATED provider redirect
# ---------------------------------------------------------------------------

@router.get("/oauth/{platform}/callback")
def oauth_callback(platform: str, code: str = "", state: str = "", error: str = ""):
    """Validate (signature → exp → atomic nonce burn → registry) then exchange the
    code server-side and store tokens in the caller-tenant's Secret Manager slot.

    Validation order per the consensus plan (N2). Every failure is 4xx with no
    detail leakage; hostile input never raises.
    """
    if error:
        # Provider-reported denial (user clicked cancel). Nothing to validate.
        return HTMLResponse(
            "<h3>Connection cancelled.</h3><p>You can close this tab.</p>", status_code=200
        )

    parsed = verify_state(state, _hmac_keys(), now=int(time.time()))
    if parsed is None or parsed["platform"] != platform:
        raise HTTPException(status_code=403, detail="invalid state")

    provider = PROVIDERS.get(platform)
    if provider is None:
        raise HTTPException(status_code=404, detail="unknown platform")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    # Atomic single-use nonce burn: DELETE ... RETURNING — a replayed callback
    # (or two concurrent ones) finds no row and dies here.
    db = _platform_db()
    try:
        burned = db.execute(
            sqltext(
                "DELETE FROM oauth_state_nonces WHERE nonce = :n AND platform = :p "
                "RETURNING tenant_id"
            ),
            {"n": parsed["nonce"], "p": platform},
        ).fetchone()
        db.commit()
    finally:
        db.close()
    if burned is None:
        raise HTTPException(status_code=403, detail="invalid state")
    if burned[0] != parsed["tenant_id"]:
        # Signed state and persisted nonce disagree on tenant — treat as hostile.
        log.warning("oauth_callback: state/nonce tenant mismatch for %s", platform)
        raise HTTPException(status_code=403, detail="invalid state")

    # Server-side code exchange. Tokens never touch the browser.
    import requests  # noqa: PLC0415
    redirect_uri = f"{_redirect_base()}/oauth/{platform}/callback"
    try:
        resp = requests.post(
            provider["token_url"],
            data={
                "code": code,
                "client_id": os.getenv(provider["client_id_env"], ""),
                "client_secret": os.getenv(provider["client_secret_env"], ""),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        resp.raise_for_status()
        tokens = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.error("oauth_callback: token exchange failed for %s: %s", platform, exc)
        raise HTTPException(status_code=502, detail="token exchange failed") from exc

    access_token = tokens.get("access_token") or ""
    if not access_token:
        raise HTTPException(status_code=502, detail="token exchange failed")

    from adapters.distribution.oauth_store import SecretManagerOAuthStore  # noqa: PLC0415
    try:
        store = SecretManagerOAuthStore(tenant_id=parsed["tenant_id"])
        store.put(
            platform,
            "default",
            access_token=access_token,
            refresh_token=tokens.get("refresh_token") or "",
            ttl=int(tokens.get("expires_in") or 3600),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("oauth_callback: store write failed for %s: %s", platform, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="credential store write failed") from exc

    # Flip the tenant's status row healthy so the Connections page reflects it now.
    from app.models import IntegrationStatus  # noqa: PLC0415
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _platform_db()
    try:
        row = (
            db.query(IntegrationStatus)
            .filter(IntegrationStatus.integration == platform,
                    IntegrationStatus.tenant_id == parsed["tenant_id"])
            .first()
        )
        if row is None:
            row = IntegrationStatus(integration=platform, tenant_id=parsed["tenant_id"])
            db.add(row)
        row.status = "healthy"
        row.last_ok = now_dt
        row.last_checked = now_dt
        row.last_error = None
        row.consecutive_failures = 0
        db.commit()
    finally:
        db.close()

    log.info("oauth_callback: %s connected for tenant %d", platform, parsed["tenant_id"])
    return HTMLResponse(
        f"<h3>{platform} connected.</h3><p>You can close this tab and return to the dashboard.</p>"
    )
