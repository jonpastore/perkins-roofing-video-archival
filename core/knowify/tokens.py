"""Knowify token lifecycle — Secret Manager-backed, single-writer, fail-loud (TRD §3/§4).

State machine (§3): valid -> (refresh-on-use / keep-warm) refresh(rotate-write) -> valid;
(revoked/lapsed) dead -> (human) Reconnect. This module owns the refresh(rotate-write) edge.

Contract:
- Tokens live in Secret Manager secret `knowify-tokens` as a JSON blob mirroring
  `~/.config/knowify/tokens.json` (client_id, access_token, refresh_token, scope, ...).
  `load_tokens()` reads the LATEST version; `save_tokens()` writes a NEW version.
- `refresh()` reuses `knowify_pull._refresh` semantics: RFC 8707 `resource=API` on the
  refresh_token grant, rotate the refresh_token, refresh AT MOST ONCE. Knowify refresh
  tokens are single-use, so a retry-loop would burn the token — one attempt, then surface.
- FAIL LOUD (Wave-0 reality: Knowify OAuth 500s on the `resource` param and 401s tokens
  minted without it): a 500, a 400 invalid_grant, or a persistent 401 -> raise `AuthError`.
  A dead/already-rotated token is NEVER written as `latest`.
- The refresh+rotate+write is wrapped in shared Postgres advisory lock 8274125
  (`with_token_lock`) so the hourly sync and a keep-warm writer can never publish a stale
  token concurrently (AC-9). Distinct from ingest 8274123 / sync 8274124.

SECURITY: this module NEVER logs a token value (access_token / refresh_token). Logs carry
HTTP status + entity only. Do not add a log line that formats a `tok` dict.

Entrypoint: `python -m core.knowify.tokens --refresh-only` (keep-warm) — load, refresh if
`/api/v2/valid` says the access token is dead, save under lock; exit non-zero on auth_error.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

# Endpoint constants live in core (scripts/ is .dockerignore'd — importing from
# scripts here would ImportError at container startup). MCP_URL is used by the MCP
# token path (mcp_access_token / refresh_mcp) added for the stopgap sync.
from core.knowify.rest import API, MCP_URL, TOKEN_URL, UA

log = logging.getLogger(__name__)

SECRET_ID = "knowify-tokens"
_LOCK_KEY = 8274125  # shared token refresh+rotate+write lock (distinct from ingest/sync)


class AuthError(Exception):
    """Refresh failed unrecoverably (500 / 400 invalid_grant / persistent 401).

    The token is dead and only a human Reconnect (re-login) can recover it. The caller
    must set sync_state to 'auth_error', exit non-zero, and stop — never retry-loop.
    """


# --------------------------------------------------------------------------- #
# Secret Manager
# --------------------------------------------------------------------------- #

def _project(project: str) -> str:
    if project:
        return project
    import os  # noqa: PLC0415
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT", "")


def _client(sm_client):
    if sm_client is not None:
        return sm_client
    from google.cloud import secretmanager  # noqa: PLC0415
    return secretmanager.SecretManagerServiceClient()


def load_tokens(sm_client=None, project: str = "") -> dict:
    """Read the LATEST version of the `knowify-tokens` secret as a JSON dict."""
    client = _client(sm_client)
    name = f"projects/{_project(project)}/secrets/{SECRET_ID}/versions/latest"
    version = client.access_secret_version(name=name)
    return json.loads(version.payload.data.decode())


def save_tokens(tok: dict, sm_client=None, project: str = "") -> None:
    """Write the token blob as a NEW version of `knowify-tokens` (old versions kept)."""
    client = _client(sm_client)
    parent = f"projects/{_project(project)}/secrets/{SECRET_ID}"
    client.add_secret_version(
        request={
            "parent": parent,
            "payload": {"data": json.dumps(tok).encode()},
        }
    )
    log.info("knowify-tokens: wrote new secret version")  # no token value


# --------------------------------------------------------------------------- #
# Liveness + refresh
# --------------------------------------------------------------------------- #

def is_valid(tok: dict) -> bool:
    """Preflight `GET /api/v2/valid` — True on 200 (live), False on 401 (dead)."""
    req = urllib.request.Request(API + "/valid", headers={
        "Authorization": "Bearer " + tok["access_token"],
        "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log.warning("knowify token invalid: HTTP 401 at /valid")
            return False
        raise


def refresh(tok: dict, sm_client=None, project: str = "") -> dict:
    """Refresh the access token ONCE, rotate the refresh token, save a new version.

    Fail loud: a 500 / 400 invalid_grant / persistent 401 raises `AuthError` and writes
    NOTHING (never publishes a dead token as latest). Knowify refresh tokens are single-use
    so we attempt exactly one grant — no retry-loop, no token burn.
    """
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        "client_id": tok["client_id"], "resource": API,  # RFC 8707 — bind to REST API
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json", "User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, timeout=30).read().decode()
    except urllib.error.HTTPError as e:
        # 500 (Knowify OAuth outage on the resource param), 400 invalid_grant, and 401
        # are all unrecoverable here — surface, do NOT retry (single-use refresh token).
        log.error("knowify refresh failed: HTTP %s (auth_error, token not written)", e.code)
        raise AuthError(f"refresh HTTP {e.code}") from e

    new = json.loads(raw)
    tok["access_token"] = new["access_token"]
    if new.get("refresh_token"):
        tok["refresh_token"] = new["refresh_token"]  # rotate (single-use)
    save_tokens(tok, sm_client=sm_client, project=project)
    log.info("knowify token refreshed + rotated (new secret version written)")
    return tok


# --------------------------------------------------------------------------- #
# MCP-token path (STOPGAP) — the sync job pulls via the /api/v2/mcp audience
# because REST /oauth 500s on the RFC 8707 `resource` binding (see module docstring).
# The token blob mirrors Claude Code's creds (camelCase: accessToken/refreshToken/
# clientId/expiresAt) and lives in its OWN secret, `knowify-mcp-tokens`, so it never
# collides with the REST `knowify-tokens` blob. Same fail-loud + single-writer-lock
# (8274125) contract as the REST path.
#
# CAVEAT (accepted by Jon): this token is shared with Jon's local Claude Code Knowify
# connector, and Knowify refresh tokens are single-use — a refresh here rotates it, so
# Jon's connector may need a one-click reconnect (and vice-versa). Collisions surface as
# an AuthError -> auth_error status -> alert, never a silent stale token.
# --------------------------------------------------------------------------- #

MCP_SECRET_ID = "knowify-mcp-tokens"
# Refresh when the access token is within this window of expiry. The keep-warm/sync
# jobs run hourly, so a small window (e.g. 5 min) is easy to miss between ticks and the
# refresh token could then lapse. 2h > the 1h scheduler cadence guarantees at least one
# run lands inside the window before expiry. (MCP access tokens observed ~8h TTL, so this
# refreshes roughly every ~6h — it does NOT burn a rotation on every run.)
_ACCESS_SKEW_MS = 2 * 60 * 60 * 1000  # 2 hours


def load_mcp_tokens(sm_client=None, project: str = "") -> dict:
    """Read the LATEST version of the `knowify-mcp-tokens` secret as a JSON dict."""
    client = _client(sm_client)
    name = f"projects/{_project(project)}/secrets/{MCP_SECRET_ID}/versions/latest"
    version = client.access_secret_version(name=name)
    return json.loads(version.payload.data.decode())


def save_mcp_tokens(tok: dict, sm_client=None, project: str = "") -> None:
    """Write the MCP token blob as a NEW version of `knowify-mcp-tokens`."""
    client = _client(sm_client)
    parent = f"projects/{_project(project)}/secrets/{MCP_SECRET_ID}"
    client.add_secret_version(
        request={"parent": parent, "payload": {"data": json.dumps(tok).encode()}}
    )
    log.info("knowify-mcp-tokens: wrote new secret version")  # no token value


def _mcp_expired(tok: dict) -> bool:
    """True if the MCP access token is within _ACCESS_SKEW_MS of `expiresAt` (ms epoch).
    A blob with no expiresAt is treated as expired so we refresh before using it."""
    exp = tok.get("expiresAt")
    if not exp:
        return True
    return time.time() * 1000 + _ACCESS_SKEW_MS >= exp


def refresh_mcp(tok: dict, sm_client=None, project: str = "") -> dict:
    """Refresh the MCP access token ONCE (resource=MCP audience), rotate, save a new version.

    Fail loud like the REST refresh: a 500 / 400 invalid_grant / 401 raises `AuthError` and
    writes NOTHING. Knowify refresh tokens are single-use, so exactly one grant attempt.
    NOTE: refresh with resource=MCP_URL is the stopgap's one unproven assumption — the REST
    resource value 500s; the MCP value is what Claude Code refreshes against, so it should
    work. The FIRST prod refresh is the live proof; a 500 here surfaces as auth_error.
    """
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": tok["refreshToken"],
        "client_id": tok["clientId"], "resource": MCP_URL,  # RFC 8707 — MCP audience
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json", "User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, timeout=30).read().decode()
    except urllib.error.HTTPError as e:
        log.error("knowify mcp refresh failed: HTTP %s (auth_error, token not written)", e.code)
        raise AuthError(f"mcp refresh HTTP {e.code}") from e

    new = json.loads(raw)
    tok["accessToken"] = new["access_token"]
    if new.get("refresh_token"):
        tok["refreshToken"] = new["refresh_token"]  # rotate (single-use)
    if new.get("expires_in"):
        tok["expiresAt"] = int(time.time() * 1000) + int(new["expires_in"]) * 1000
    save_mcp_tokens(tok, sm_client=sm_client, project=project)
    log.info("knowify mcp token refreshed + rotated (new secret version written)")
    return tok


def mcp_access_token() -> str:
    """Return a live MCP access-token string, refreshing under lock if near expiry.

    Raises `AuthError` if a needed refresh fails — the caller marks auth_error and exits.
    """
    from app.models import SessionLocal  # noqa: PLC0415
    tok = load_mcp_tokens()
    if not _mcp_expired(tok):
        return tok["accessToken"]
    session = SessionLocal()
    session.info["platform_scope"] = True  # platform-level lock; no tenant GUC
    try:
        with with_token_lock(session):
            tok = load_mcp_tokens()  # re-read the freshest token under the lock
            if _mcp_expired(tok):
                tok = refresh_mcp(tok)
        return tok["accessToken"]
    finally:
        session.close()


def mcp_refresh_only() -> int:
    """Keep-warm for the MCP token: refresh if near expiry, save under lock. 0 ok / 1 auth_error."""
    from app.models import SessionLocal  # noqa: PLC0415
    tok = load_mcp_tokens()
    if not _mcp_expired(tok):
        log.info("knowify mcp token still valid — keep-warm no-op")
        return 0
    session = SessionLocal()
    session.info["platform_scope"] = True
    try:
        with with_token_lock(session):
            tok = load_mcp_tokens()
            if _mcp_expired(tok):
                refresh_mcp(tok)
        return 0
    except AuthError:
        log.error("knowify mcp keep-warm: auth_error — human Reconnect required")
        return 1
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Advisory lock (AC-9) — shared 8274125, blocking so a concurrent writer waits
# --------------------------------------------------------------------------- #

@contextmanager
def with_token_lock(session):
    """Hold advisory lock 8274125 across a refresh+rotate+write.

    Blocking (`pg_advisory_lock`, not `try_`) — a second concurrent refresh WAITS for the
    first to finish and release, so no writer publishes a stale (already-rotated) token.
    Session-scoped: if the process dies the connection drops and the lock auto-releases.
    No-op on sqlite (dev).
    """
    from sqlalchemy import text  # noqa: PLC0415
    is_pg = session.bind.dialect.name == "postgresql"
    if is_pg:
        session.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
    try:
        yield
    finally:
        if is_pg:
            session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            session.commit()


# --------------------------------------------------------------------------- #
# --refresh-only entrypoint (keep-warm): load -> refresh-if-dead -> save, under lock
# --------------------------------------------------------------------------- #

def refresh_only() -> int:
    """Keep-warm: load tokens, refresh if the access token is dead, save under lock.

    Returns 0 on success (or already-valid), non-zero on auth_error so Cloud Run marks the
    execution failed and the §9a alert fires.
    """
    from app.models import SessionLocal  # noqa: PLC0415
    tok = load_tokens()
    if is_valid(tok):
        log.info("knowify token still valid — keep-warm no-op")
        return 0
    session = SessionLocal()
    session.info["platform_scope"] = True  # platform-level lock; no tenant GUC
    try:
        with with_token_lock(session):
            # Re-read under the lock so we refresh the freshest token another writer may
            # have just rotated (avoids burning a token we didn't observe).
            tok = load_tokens()
            if is_valid(tok):
                return 0
            refresh(tok)
        return 0
    except AuthError:
        log.error("knowify keep-warm: auth_error — human Reconnect required")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    if "--refresh-only" in sys.argv[1:]:
        logging.basicConfig(level=logging.INFO)
        sys.exit(refresh_only())
    sys.exit("usage: python -m core.knowify.tokens --refresh-only")
