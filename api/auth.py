"""FastAPI auth dependencies: verify the Firebase ID token, resolve GCIP tenant,
enforce the role→action matrix from core.authz.

F4b additions:
  - _resolve_tenant(): GCIP firebase.tenant claim → platform tenant_id
  - _platform_admin_emails(): DB lookup for platform_admins table
  - _verify_with_db(): full verify flow accepting a DB session (used by tests + session deps)
  - _apply_impersonation(): X-Tenant-ID invariants (TRD-F4 §4.4)
  - get_platform_db_session(): platform-scoped session dependency (no GUC, no tenant_id set)

Claim-mapping contract (consumed by f4-rls session dependency):
  claims["tenant_id"]  — int | None
      int  → resolved platform tenant (1 = Perkins project-level pool)
      None → platform_admin operating without impersonation (no tenant context)
  claims["role"]       — str: "admin"|"web_admin"|"sales"|"platform_admin"|""
  claims["impersonating"]    — bool (present and True only when X-Tenant-ID was honored)
  claims["impersonating_as"] — int  (present only when impersonating=True)
"""
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text

from app.config import settings
from core.authz import can, effective_role

log = logging.getLogger(__name__)

_verifier = None


def set_verifier(fn):
    """Override the token verifier (tests inject a fake; prod defaults to adapters.firebase)."""
    global _verifier
    _verifier = fn


def _get_verifier():
    global _verifier
    if _verifier is None:
        from adapters.firebase import verify_token
        _verifier = verify_token
    return _verifier


# ---------------------------------------------------------------------------
# GCIP claim mapping (TRD-F4 §4.2)
# ---------------------------------------------------------------------------

def _resolve_tenant(claims: dict, db_session) -> int:
    """Resolve GCIP token claims → platform tenant_id.

    Rules (in order):
      1. No firebase.tenant claim → tenant 1 (Perkins; project-level pool).
      2. firebase.tenant claim present → look up tenant_gcip_map.
         Row missing → 401 (unknown tenant; token is valid but not provisioned).

    The db_session must be a platform-level session (no RLS GUC set) because this
    lookup runs before tenant_id is known — it IS the lookup that determines tenant_id.
    """
    gcip_tenant = claims.get("firebase", {}).get("tenant")
    if gcip_tenant is None:
        return 1  # Perkins stays on project-level pool; zero disruption

    row = db_session.execute(
        text("SELECT tenant_id FROM tenant_gcip_map WHERE gcip_tenant = :g"),
        {"g": gcip_tenant},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="tenant not provisioned")
    return row[0]


def _platform_admin_emails(db_session) -> frozenset:
    """Return the set of platform_admin emails from the platform_admins table.

    Falls back to empty frozenset if the table doesn't exist yet (migrations pending).
    Result is NOT cached across requests — the table is small and rarely changes.
    """
    try:
        rows = db_session.execute(text("SELECT email FROM platform_admins")).fetchall()
        return frozenset(r[0].lower() for r in rows)
    except Exception:
        return frozenset()


# ---------------------------------------------------------------------------
# Impersonation invariants (TRD-F4 §4.4)
# ---------------------------------------------------------------------------

def _apply_impersonation(claims: dict, x_tenant_id: Optional[str], path: str) -> dict:
    """Apply X-Tenant-ID impersonation invariants and return updated claims dict.

    Invariants (all must hold):
      1. Auth gate: X-Tenant-ID is only read after a verified platform_admin claim.
      2. Route gate: X-Tenant-ID is ONLY honored on /internal/* routes.
      3. No side-effects for non-platform_admin or non-internal routes.

    Returns a shallow copy of claims with tenant_id (and impersonating flags) updated.
    """
    result = dict(claims)

    if not x_tenant_id:
        return result

    # Invariant 1: must be platform_admin
    if result.get("role") != "platform_admin":
        log.debug("X-Tenant-ID header ignored — not a platform_admin (role=%s)", result.get("role"))
        return result

    # Invariant 2: must be an /internal/* route
    if not path.startswith("/internal"):
        log.warning(
            "X-Tenant-ID header stripped — platform_admin on non-/internal route %s", path
        )
        return result

    # Parse the header value
    try:
        tenant_id_int = int(x_tenant_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be an integer")

    result["tenant_id"] = tenant_id_int
    result["impersonating"] = True
    result["impersonating_as"] = tenant_id_int
    return result


# ---------------------------------------------------------------------------
# Core verify logic
# ---------------------------------------------------------------------------

def _verify(authorization: str) -> dict:
    """Verify the bearer token → claims dict with the effective role.

    Legacy path used by existing endpoints that don't have a DB session.
    Uses the config DEFAULT_ADMINS frozenset for effective_role (backward compat).
    New F4+ endpoints should use _verify_with_db() via the session dependency.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = dict(_get_verifier()(authorization[7:]))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    email = claims.get("email")
    role = claims.get("role", "")
    email_verified = claims.get("email_verified", False)

    # Legacy path: pass DEFAULT_ADMINS frozenset as tenant_id arg (detected via isinstance)
    # email_verified must be a keyword arg so it doesn't fall into db_session position.
    claims["role"] = effective_role(
        email, role, settings.DEFAULT_ADMINS, email_verified=email_verified
    )
    if "tenant_id" not in claims:
        claims["tenant_id"] = 1
    return claims


def _verify_with_db(authorization: str, db_session) -> dict:
    """Full F4b verify: token → GCIP tenant resolution → platform_admin check → effective_role.

    Authoritative verify path for F4+ endpoints. Requires a platform-level DB session
    (no GUC set) for the tenant_gcip_map and platform_admins lookups.

    Returns claims dict with tenant_id, role, and all F4 fields populated.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = dict(_get_verifier()(authorization[7:]))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")

    email = claims.get("email", "")
    email_lower = email.lower() if email else ""
    email_verified = claims.get("email_verified", False)

    # Check platform_admins table first — short-circuits role resolution
    platform_emails = _platform_admin_emails(db_session)
    if email_lower and email_lower in platform_emails:
        claims["role"] = "platform_admin"
        claims["tenant_id"] = None  # platform_admin has no tenant context without impersonation
        return claims

    # Resolve GCIP tenant
    tenant_id = _resolve_tenant(claims, db_session)
    claims["tenant_id"] = tenant_id

    # Resolve effective role (DB path with tenant_id)
    claims["role"] = effective_role(
        email=email,
        role=claims.get("role", ""),
        tenant_id=tenant_id,
        db_session=db_session,
        email_verified=email_verified,
    )
    return claims


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def current_claims(authorization: str = Header(default="")):
    """Any authenticated user — no role gate. Returns claims + effective role. Use for /me."""
    return _verify(authorization)


def require_role(action):
    """FastAPI dependency factory — allow the request only if the caller's role `can(action)`."""
    def dep(authorization: str = Header(default="")):
        claims = _verify(authorization)
        if not can(claims["role"], action):
            raise HTTPException(status_code=403, detail="forbidden")
        return claims
    return dep


# ---------------------------------------------------------------------------
# Tenant-scoped session dependency (TRD-F4 §3.2) — the authoritative F4 path
# ---------------------------------------------------------------------------

def current_claims_with_db(authorization: str = Header(default="")):
    """Verify a token through the DB-backed F4 path (GCIP tenant resolution +
    platform_admins lookup + tenant_default_admins effective_role).

    Opens a short-lived PLATFORM-scoped session (no tenant GUC) solely for the
    pre-tenant lookups — this is the lookup that determines tenant_id, so it must
    run before any tenant GUC is set. Returns fully-populated F4 claims.
    """
    from app.models import PlatformSessionLocal

    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    try:
        return _verify_with_db(authorization, db)
    finally:
        db.close()


def get_db_session(claims: dict = Depends(current_claims_with_db)):
    """Yield a tenant-scoped DB session stamped with the caller's VERIFIED tenant.

    TRD-F4 §3.2: session.info["tenant_id"] is sourced ONLY from verified token
    claims (resolved by current_claims_with_db) — never from a header or body.
    The after_begin event in core/tenant.py issues the transaction-local GUC from
    this stamp before the first query, so RLS filters every statement.

    A platform_admin operating WITHOUT impersonation has claims["tenant_id"] is
    None (no tenant context). Such a caller must not use a tenant-scoped route;
    we 403 rather than default to a tenant, so platform_admins cannot read
    tenant-scoped data without an explicit, audited impersonation (TRD-F4 §3.2
    red test: platform_admin without X-Tenant-ID → 403 on tenant-scoped route).
    """
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(
            status_code=403,
            detail="no tenant context (platform_admin must impersonate via /internal)",
        )

    from adapters.gcp_logging import set_log_tenant
    from app.models import SessionLocal

    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    # Bind tenant_id for structured logging (TRD-F4 §5). We set/clear the value
    # directly rather than using a reset-token: FastAPI runs a sync dependency's
    # setup and teardown in DIFFERENT contexts (threadpool), and a Token cannot be
    # reset in a context other than the one it was created in.
    set_log_tenant(tenant_id)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        set_log_tenant(None)


# ---------------------------------------------------------------------------
# Platform-scoped session dependency (TRD-F4 §3.2 — no GUC, no tenant_id)
# ---------------------------------------------------------------------------

def require_platform_admin(authorization: str = Header(default="")):
    """Gate on EXACT role == "platform_admin" (H6 fix).

    NOT can(role, "view_all_tenants"): the admin role carries the "*" wildcard,
    so gating on the action would let ANY Perkins admin through and leak the
    cross-tenant tenant list. Only DeGenito platform_admins (verified via the
    platform_admins table in _verify_with_db) may reach /internal/* platform
    surfaces. We verify through the DB path so the platform_admins table is the
    source of truth (not a spoofable custom claim).
    """
    from app.models import PlatformSessionLocal

    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    try:
        claims = _verify_with_db(authorization, db)
    finally:
        db.close()
    if claims.get("role") != "platform_admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return claims


def get_platform_db_session(claims: dict = Depends(require_platform_admin)):
    """Yield a DB session with NO tenant GUC set.

    For use ONLY by endpoints that touch RLS-exempt platform-level tables:
    tenants, tenant_gcip_map, tenant_default_admins, platform_admins, platform_audit_log.

    Do NOT use for any endpoint that reads tenant-scoped data.
    Sets session.info['platform_scope'] = True as a seam for the f4-rls agent.
    Gated on EXACT platform_admin (H6) — the admin "*" wildcard does NOT satisfy it.
    """
    from app.models import PlatformSessionLocal
    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Internal-platform dependency: gates on view_all_tenants + writes audit row
# ---------------------------------------------------------------------------

def require_internal_tenants(
    request: Request,
    authorization: str = Header(default=""),
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Dependency for /internal/* platform-admin routes.

    1. Verifies the token through the DB path and gates on EXACT role ==
       "platform_admin" (H6 fix — NOT can(role, "view_all_tenants"), because the
       admin "*" wildcard would satisfy that action and leak the tenant list to
       any Perkins admin).
    2. Applies X-Tenant-ID impersonation invariants.
    3. Writes a platform_audit_log row when impersonation is active — in the SAME
       transaction as would carry the impersonated work, failing CLOSED (403) if
       the audit write fails (M4: an un-audited impersonation must not proceed).

    Returns updated claims dict with impersonation fields populated.
    """
    from app.models import PlatformSessionLocal

    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    try:
        claims = _verify_with_db(authorization, db)
    finally:
        db.close()

    if claims.get("role") != "platform_admin":
        raise HTTPException(status_code=403, detail="forbidden")

    claims = _apply_impersonation(claims, x_tenant_id, request.url.path)

    if claims.get("impersonating"):
        from app.models import PlatformAuditLog, PlatformSessionLocal
        db = PlatformSessionLocal()
        try:
            row = PlatformAuditLog(
                platform_admin_email=claims.get("email", ""),
                target_tenant_id=claims["impersonating_as"],
                route=request.url.path,
                method=request.method,
            )
            db.add(row)
            db.commit()
        except Exception as exc:
            db.rollback()
            # Fail CLOSED: an impersonated request that cannot be audited must not
            # proceed (M4 — audit durability). Better a 500 than a silent,
            # unlogged cross-tenant access by a platform_admin.
            raise HTTPException(
                status_code=500, detail="impersonation audit write failed"
            ) from exc
        finally:
            db.close()

    return claims
