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
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

# Reuse the constants + refresh shape from the read-only importer (single source of truth).
from scripts.knowify.knowify_pull import API, TOKEN_URL, UA

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
