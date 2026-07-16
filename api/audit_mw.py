"""Audit middleware + the write seam every audit row goes through.

Records one row for EVERY mutating request. Not per-route: there are 86 mutating endpoints
across 25 route modules, and instrumenting them by hand covers 86 and misses the 87th on the
day someone adds it. Coverage that depends on remembering is not coverage.

Three properties this has to have, each learned the hard way:

1. **It records failures.** A 403 nobody can explain and a 500 mid-write are the whole reason
   this exists. So the row is written AFTER the response, with the status, in its OWN
   transaction — the request's session is rolled back on error and would take the evidence
   with it.
2. **It never breaks the request.** A logging failure must not turn a working POST into a 500.
   Every path here is fail-open, and a failure to audit is itself logged loudly.
3. **It never stores a secret.** Bodies are not read at all; only redacted, known-safe query
   params and path params are kept. See core.audit.redact.
"""
from __future__ import annotations

import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from core.audit import action_for, current_actor, entity_from, redact, template_path

log = logging.getLogger(__name__)

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths whose auditing would be noise or a hazard. Health checks fire constantly; the audit
# reader itself must not audit its own reads into an infinite mirror.
SKIP_PREFIXES = ("/healthz", "/readyz", "/metrics", "/static", "/docs", "/openapi")


def write(
    *,
    tenant_id: int,
    action: str,
    actor_email: str | None = None,
    actor_role: str | None = None,
    impersonating: bool = False,
    impersonating_as: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    method: str | None = None,
    route: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
    source: str = "api",
    detail: dict | None = None,
) -> bool:
    """Persist one audit row in its OWN transaction. Returns True when written.

    Its own session on purpose: the caller's transaction is rolled back when a request fails,
    and an audit trail that disappears exactly when something went wrong is worse than none —
    it would read as "nothing happened".
    """
    try:
        from app.config import settings  # noqa: PLC0415
        if not settings.AUDIT_ENABLED:
            return False
        from app.models import AuditLog, SessionLocal  # noqa: PLC0415

        # `changes` is the before/after payload from core.audit.diff(), which has ALREADY
        # applied secret redaction and revert-length limits. It must bypass redact(), whose
        # deny-by-default rules are for untrusted arbitrary payloads: they would replace the
        # whole thing with "[omitted]" (field names like content_md are not on SAFE_KEYS) and
        # silently turn a revert-capable trail into a decorative one.
        payload = dict(detail or {})
        changes = payload.pop("changes", None)
        safe_detail = redact(payload)
        if changes is not None:
            safe_detail["changes"] = changes

        with SessionLocal() as s:
            s.info["tenant_id"] = tenant_id          # RLS: rows are tenant-scoped
            s.add(AuditLog(
                tenant_id=tenant_id,
                action=action,
                actor_email=(actor_email or None),
                actor_role=(actor_role or None),
                impersonating=bool(impersonating),
                impersonating_as=impersonating_as,
                entity_type=entity_type,
                entity_id=(str(entity_id)[:255] if entity_id is not None else None),
                method=method,
                route=(route or "")[:255] or None,
                path=(path or "")[:1024] or None,
                status_code=status_code,
                request_id=request_id,
                source=source,
                detail=safe_detail,
            ))
            s.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — auditing must never break the caller
        log.error("AUDIT WRITE FAILED action=%r tenant=%s: %s", action, tenant_id, exc)
        return False


def write_platform(
    *,
    actor_email: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    target_tenant_id: int | None = None,
    method: str | None = None,
    route: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
    source: str = "api",
    detail: dict | None = None,
) -> bool:
    """Persist a PLATFORM-level audit row (no tenant context).

    Its own table and its own PLATFORM-scoped session: platform_audit_log is RLS-exempt, so it
    must not go through the tenant session factory (which stamps app.tenant_id and would fail
    the strict unstamped-session guard here). Same fail-open contract as write().
    """
    try:
        from app.config import settings  # noqa: PLC0415
        if not settings.AUDIT_ENABLED:
            return False
        from app.models import PlatformAuditLog, PlatformSessionLocal  # noqa: PLC0415

        with PlatformSessionLocal() as s:
            s.info["platform_scope"] = True
            s.add(PlatformAuditLog(
                platform_admin_email=(actor_email or "anonymous"),
                target_tenant_id=target_tenant_id,
                route=(route or path or "")[:255] or "/",
                method=(method or "")[:10] or "?",
                action=action,
                entity_type=entity_type,
                entity_id=(str(entity_id)[:255] if entity_id is not None else None),
                status_code=status_code,
                request_id=request_id,
                source=source,
                path=(path or "")[:1024] or None,
                detail=redact(detail or {}),
            ))
            s.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — auditing must never break the caller
        log.error("PLATFORM AUDIT WRITE FAILED action=%r: %s", action, exc)
        return False


class AuditMiddleware(BaseHTTPMiddleware):
    """Write an audit row for every mutating request, success or failure."""

    async def dispatch(self, request, call_next):
        method = request.method.upper()
        path = request.url.path
        if method not in MUTATING or path.startswith(SKIP_PREFIXES):
            return await call_next(request)

        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:32]
        request.state.request_id = request_id

        # Publish the request id up-front so ORM-captured rows (core/audit_orm.py) can be tied
        # back to the HTTP request that caused them. The actor is filled in below, once the
        # auth dependency has actually run and produced claims.
        token = current_actor.set({"request_id": request_id, "source": "api"})

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # In `finally` so an exception mid-handler is still recorded — an unexplained 500
            # is precisely what someone will come here looking for.
            try:
                self._record(request, method, path, status_code, request_id)
            except Exception as exc:  # noqa: BLE001
                log.error("AUDIT middleware failed for %s %s: %s", method, path, exc)
            finally:
                # Never let one request's actor leak into the next on a reused worker.
                current_actor.reset(token)

    @staticmethod
    def _record(request, method: str, path: str, status_code: int, request_id: str) -> None:
        claims = getattr(request.state, "claims", None) or {}
        tenant_id = claims.get("tenant_id")
        route_obj = request.scope.get("route")
        route = getattr(route_obj, "path", None) or template_path(path)
        params = request.scope.get("path_params") or {}

        if tenant_id is None:
            # No tenant context: a platform admin acting on the platform itself (provisioning,
            # admin grants, SSO, billing), or an unauthenticated/rejected request. audit_log is
            # RLS tenant-scoped and has nowhere to put these, so they go to the platform trail
            # — a separate table on purpose (see PlatformAuditLog). Correlates back on
            # request_id.
            write_platform(
                actor_email=claims.get("email"),
                action=action_for(method, route),
                entity_type=entity_from(route, params)[0],
                entity_id=entity_from(route, params)[1],
                target_tenant_id=claims.get("impersonating_as"),
                method=method, route=route, path=path,
                status_code=status_code, request_id=request_id,
                detail={"query": dict(request.query_params)} if request.query_params else {},
            )
            return

        etype, eid = entity_from(route, params)
        write(
            tenant_id=int(tenant_id),
            action=action_for(method, route),
            actor_email=claims.get("email"),
            actor_role=claims.get("role"),
            impersonating=bool(claims.get("impersonating")),
            impersonating_as=claims.get("impersonating_as"),
            entity_type=etype,
            entity_id=eid,
            method=method,
            route=route,
            path=path,
            status_code=status_code,
            request_id=request_id,
            source="api",
            # Query params only — request bodies are never read here. Redaction still applies.
            detail={"query": dict(request.query_params)} if request.query_params else {},
        )
