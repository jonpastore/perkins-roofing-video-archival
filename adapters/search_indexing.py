"""Search-engine indexing adapter (I/O — coverage-omitted).

Submits URLs to:
  (a) IndexNow — POST https://api.indexnow.org/indexnow — one call reaches Bing,
      Yandex, Seznam, Naver (NOT Google). Requires env INDEXNOW_KEY. The exact
      same key MUST also be hosted, unauthenticated, as a static file at
      https://{WP_URL host}/{INDEXNOW_KEY}.txt containing ONLY the key string —
      that file is NOT built by this adapter (it lives on the WordPress site;
      provision it there, e.g. a plugin/static-file upload).
  (b) Google Indexing API — POST https://indexing.googleapis.com/v3/urlNotifications:publish
      — one URL_UPDATED notification per URL. Requires env
      GOOGLE_INDEXING_CREDENTIALS: a service-account JSON key (inline JSON or a
      file path). That service account must be added as an OWNER of the site in
      Google Search Console, and the Indexing API must be enabled on its GCP
      project. Quota: 200 publish calls/day (core.search_indexing.MAX_URLS_PER_RUN
      keeps every run well under that).

Both are best-effort notifications, not indexing guarantees. Every call is
wrapped so a bad response (or a missing credential) from one provider is
reported, never raised — a submission failure must never block publishing.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import requests

from core.search_indexing import IndexingStatus, indexnow_payload

_INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
_GOOGLE_INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
_GOOGLE_INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"


def _enabled() -> bool:
    """Admin on/off toggle. platform_config override (Admin Config → Platform
    Settings, key SEARCH_INDEXING_ENABLED) wins; else env; default "true"."""
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415
        with PlatformSessionLocal() as db:
            row = db.get(PlatformConfig, "SEARCH_INDEXING_ENABLED")
            if row and (row.value or "").strip():
                return row.value.strip().lower() == "true"
    except Exception:
        pass
    return os.getenv("SEARCH_INDEXING_ENABLED", "true").strip().lower() == "true"


def status() -> IndexingStatus:
    """Current on/off + per-provider configured state (used by the production
    readiness gate and by submit_urls to decide what to fire)."""
    return IndexingStatus(
        enabled=_enabled(),
        indexnow_configured=bool(os.getenv("INDEXNOW_KEY")),
        google_configured=bool(os.getenv("GOOGLE_INDEXING_CREDENTIALS")),
    )


def submit_indexnow(urls: list[str]) -> dict:
    """One IndexNow POST covering every url (they must share a host — callers
    pass URLs for a single site, which is always true here)."""
    key = os.getenv("INDEXNOW_KEY")
    if not key:
        return {"ok": False, "error": "INDEXNOW_KEY not configured"}
    if not urls:
        return {"ok": False, "error": "no urls"}
    host = urlparse(urls[0]).hostname or ""
    payload = indexnow_payload(host, key, urls)
    try:
        resp = requests.post(_INDEXNOW_ENDPOINT, json=payload, timeout=10)
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)}
    ok = resp.status_code in (200, 202)
    return {"ok": ok, "status": resp.status_code, "error": None if ok else resp.text[:300]}


def _google_access_token() -> str:
    import google.auth.transport.requests  # noqa: PLC0415
    from google.oauth2 import service_account  # noqa: PLC0415

    raw = os.environ["GOOGLE_INDEXING_CREDENTIALS"]
    info = json.loads(raw) if raw.strip().startswith("{") else json.loads(open(raw, encoding="utf-8").read())
    creds = service_account.Credentials.from_service_account_info(info, scopes=[_GOOGLE_INDEXING_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def submit_google_indexing(urls: list[str], notification_type: str = "URL_UPDATED") -> list[dict]:
    """One URL_UPDATED notification per url (the API has no batch endpoint)."""
    if not os.getenv("GOOGLE_INDEXING_CREDENTIALS"):
        return [{"ok": False, "url": u, "error": "GOOGLE_INDEXING_CREDENTIALS not configured"} for u in urls]
    try:
        token = _google_access_token()
    except Exception as e:  # noqa: BLE001
        return [{"ok": False, "url": u, "error": f"auth failed: {e}"} for u in urls]

    results = []
    for u in urls:
        try:
            resp = requests.post(
                _GOOGLE_INDEXING_ENDPOINT,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"url": u, "type": notification_type},
                timeout=10,
            )
            ok = resp.status_code == 200
            results.append({"ok": ok, "url": u, "status": resp.status_code, "error": None if ok else resp.text[:300]})
        except requests.RequestException as e:
            results.append({"ok": False, "url": u, "error": str(e)})
    return results


def submit_urls(urls: list[str]) -> dict:
    """Submit `urls` to every configured provider, respecting the admin on/off
    toggle. Idempotent + safe to call repeatedly: both APIs are notification
    endpoints (not queues), so re-submitting an already-known URL is a no-op on
    their side, not a duplicate action on ours."""
    st = status()
    if not st.enabled:
        return {"skipped": "disabled"}
    if not urls:
        return {"skipped": "no_urls"}
    return {
        "indexnow": submit_indexnow(urls) if st.indexnow_configured else {"ok": False, "error": "not configured"},
        "google": submit_google_indexing(urls) if st.google_configured else [{"ok": False, "error": "not configured"}],
    }
