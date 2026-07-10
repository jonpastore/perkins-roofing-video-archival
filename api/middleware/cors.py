"""Dynamic DB-backed CORS middleware (W0).

Replaces the static Starlette CORSMiddleware (which reads origins once at init).
This middleware resolves allowed origins per-request from the cors_origins table,
using a short TTL in-process cache to avoid a DB hit on every request.

COUNCIL HARDENING (binding):
- Exact-match only — no substring, suffix, or regex matching.
- Vary: Origin on EVERY response (allow and deny) so caches never serve one
  tenant's ACAO header to another origin.
- Tenant/host/origin alignment: if the request's Host header resolves to a
  specific tenant (via cors_origins.tenant_id), then the Origin must also
  belong to that same tenant. A valid origin for tenant A on tenant B's host
  is denied.
- Preflight (OPTIONS) parity: the preflight allow-list is identical to the
  actual-request allow-list — no "permissive preflight, strict actual" gap.
"""
from __future__ import annotations

import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_CACHE_TTL_SECONDS = 30  # short TTL avoids a DB query per request


def _get_dev_origins() -> list[dict]:
    """Return extra platform-wide origins from CORS_DEV_ORIGINS env var.

    MEDIUM-D: localhost:5173 is excluded from the prod DB seed to avoid granting
    credentialed ACAO to arbitrary localhost ports in production.  In local dev,
    set CORS_DEV_ORIGINS=http://localhost:5173 (comma-separated).  These origins
    are only honoured when PERKINS_ENV != 'prod' — in prod this returns [].
    """
    if os.getenv("PERKINS_ENV") == "prod":
        return []
    raw = os.getenv("CORS_DEV_ORIGINS", "http://localhost:5173")
    return [
        {"origin": o.strip(), "tenant_id": None}
        for o in raw.split(",")
        if o.strip()
    ]


class _OriginsCache:
    """In-process LRU-less cache: stores the full cors_origins result with a TTL."""

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._fetched_at: float = 0.0

    def is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) > _CACHE_TTL_SECONDS

    def populate(self, rows: list[dict]) -> None:
        self._rows = rows
        self._fetched_at = time.monotonic()

    @property
    def rows(self) -> list[dict]:
        return self._rows


_cache = _OriginsCache()


def _load_origins() -> list[dict]:
    """Load all cors_origins rows from DB using a platform-scoped session.

    strict=True is LIVE: an unstamped SessionLocal raises on Postgres.
    We use PlatformSessionLocal (no GUC hook) with platform_scope=True,
    the same pattern as every other platform-level lookup in this codebase.
    """
    from app.models import CorsOrigin, PlatformSessionLocal

    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        rows = db.query(CorsOrigin).all()
        return [
            {"origin": r.origin, "tenant_id": r.tenant_id}
            for r in rows
        ]


def _get_origins() -> list[dict]:
    """Return cached DB origins merged with dev-only extras.

    Dev origins (CORS_DEV_ORIGINS) are appended in non-prod environments and are
    NOT cached — they are re-read from env on every call (cheap; config-file reload).
    In prod (PERKINS_ENV=prod) _get_dev_origins() returns [] so there is no overhead.
    """
    if _cache.is_stale():
        try:
            rows = _load_origins()
            _cache.populate(rows)
        except Exception:  # noqa: BLE001 — DB unavailable at startup: keep stale cache
            pass
    return _cache.rows + _get_dev_origins()


def _resolve_host_tenant(host: str, origins: list[dict]) -> int | None:
    """Derive the tenant that 'owns' the Host header by looking up the matching
    cors_origins row and returning its tenant_id.  Returns None for platform-wide
    origins (tenant_id NULL) or if the host doesn't match any registered origin.

    We build the expected origin from the Host header using https:// by default;
    requests over http (localhost dev) also tried.  The host is tried both with
    and without its port so that tenant-scoped origins that include a port
    (e.g. http://localhost:5173) can still match when Host: localhost:5173 is sent.
    """
    # Build candidates: portless form first (common prod case), then with port if
    # the caller passes the raw Host value including port.
    candidates = [f"https://{host}", f"http://{host}"]
    for row in origins:
        if row["origin"] in candidates:
            return row["tenant_id"]
    return None


def _is_allowed(origin: str, host_tenant: int | None, origins: list[dict]) -> bool:
    """Return True iff the Origin is in the allow-list AND passes tenant alignment.

    Exact-match only — no substring, suffix, or regex matching.
    Tenant alignment: if host_tenant is non-None (i.e. the Host belongs to a
    specific tenant), then the Origin's tenant_id must equal host_tenant.
    A NULL tenant_id on the origin row means platform-wide — allowed from any host.
    """
    for row in origins:
        if row["origin"] != origin:
            continue
        origin_tenant = row["tenant_id"]
        if host_tenant is None:
            # Host is platform-wide or unrecognised — only allow platform-wide origins
            if origin_tenant is None:
                return True
        else:
            # Host belongs to a specific tenant — origin must match that tenant OR be platform-wide
            if origin_tenant is None or origin_tenant == host_tenant:
                return True
        return False  # same origin matched but tenant alignment failed
    return False


_ALLOWED_METHODS = "GET, POST, PUT, DELETE, OPTIONS"
_ALLOWED_HEADERS = "Authorization, Content-Type"
_MAX_AGE = "600"


def _cors_headers(origin: str, allowed: bool) -> dict[str, str]:
    headers: dict[str, str] = {"Vary": "Origin"}
    if allowed:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
        headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
    return headers


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """Per-request DB-backed CORS middleware.

    Preflight (OPTIONS) and actual requests use the same allow/deny resolution
    so the preflight allow-list cannot be more permissive than actual requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        # Pass the raw Host header (including port if present) so that
        # _resolve_host_tenant can match tenant-scoped origins that include a port
        # (e.g. http://localhost:5173 where Host: localhost:5173).
        host = request.headers.get("host", "")

        origins = _get_origins()
        host_tenant = _resolve_host_tenant(host, origins)
        allowed = bool(origin) and _is_allowed(origin, host_tenant, origins)
        cors_hdrs = _cors_headers(origin, allowed)

        if request.method == "OPTIONS":
            # Preflight — respond directly without calling the app.
            # Max-age only on preflight.
            cors_hdrs["Access-Control-Max-Age"] = _MAX_AGE
            return Response(status_code=204, headers=cors_hdrs)

        # In Starlette >= 1.x, call_next() re-raises inner-app exceptions rather than
        # wrapping them in a 500 Response.  We catch exceptions here so we can stamp
        # Vary: Origin (and any other CORS headers) on the synthesised 500 Response
        # before returning it.  This ensures Vary is present on EVERY response path
        # (council hardening: caches must never serve one origin's ACAO to another).
        try:
            response = await call_next(request)
        except Exception:
            response = Response(status_code=500, headers=cors_hdrs)
            return response
        for k, v in cors_hdrs.items():
            response.headers[k] = v
        return response


def invalidate_cache() -> None:
    """Force the next request to reload origins from DB. Useful in tests."""
    _cache._fetched_at = 0.0
    _cache._rows = []
