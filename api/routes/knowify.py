"""Read-only Knowify mirror API routes (Wave 6).

All routes are tenant-scoped via the verified-claims session (RLS FORCED on every
mirror table, so even a role bug cannot leak another tenant's rows).

Role grants (§5 / §6 of TRD):
  - GET routes: billing_manage (admin holds "*", so admin always passes)
  - POST /sync-now, /reconnect: knowify_admin (admin-only via "*")

NOTE: POST /knowify/reconnect surfaces auth status and instructions.
Knowify's interactive OAuth is currently 500ing server-side (Wave-0 observation) —
the actual browser flow is Jon's CLI for now. reconnect() returns a clear payload
so the UI can surface the status and guide the operator.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Customer, Invoice, KnowifyRawRecord, KnowifySyncState, Payment

router = APIRouter(prefix="/knowify", tags=["knowify"])

_READ_ROLE = "billing_view"   # widened: sales + web_admin + admin can view legacy data
_ADMIN_ROLE = "knowify_admin"


# ---------------------------------------------------------------------------
# Sync trigger seam — real impl calls Cloud Run Job; mocked in tests.
# Import guard: GCP libs are optional (absent in SQLite dev/test env).
# ---------------------------------------------------------------------------

def trigger_sync() -> dict:
    """Trigger the knowify-sync Cloud Run Job.

    In tests, this function is patched at api.routes.knowify.trigger_sync.
    In prod, it calls the Cloud Run Jobs API via google-auth / requests.
    GCP import is deferred so SQLite test runs don't fail on missing deps.
    """
    try:
        import google.auth  # noqa: F401 — guard import
        import google.auth.transport.requests
        import requests as _requests

        creds, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)

        # Region for the Jobs API URL. deploy.sh sets GCP_REGION (us-central1, where the
        # jobs actually live); read it from the env directly since `settings` doesn't expose
        # it. The fallback matches the real deploy region — a us-east1 fallback pointed
        # sync-now at a region with no knowify-sync job (the "Sync now" 403/404 cause).
        import os  # noqa: PLC0415
        from app.config import settings
        region = os.getenv("GCP_REGION") or getattr(settings, "GCP_REGION", None) or "us-central1"
        job_url = (
            f"https://{region}-run.googleapis.com/apis/run.googleapis.com/v1"
            f"/namespaces/{project}/jobs/knowify-sync:run"
        )
        resp = _requests.post(
            job_url,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"triggered": True, "status": "accepted"}
    except Exception as exc:  # noqa: BLE001
        # ponytail: broad catch — Cloud Run trigger is best-effort; job health
        # is surfaced via /knowify/status, not this response. Narrow if needed.
        return {"triggered": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# GET /knowify/status
# ---------------------------------------------------------------------------

@router.get("/status")
def knowify_status(
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Per-entity sync health from knowify_sync_state for the caller's tenant."""
    rows = db.execute(
        select(KnowifySyncState).order_by(KnowifySyncState.entity)
    ).scalars().all()
    return [
        {
            "entity": r.entity,
            "last_status": r.last_status,
            "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            "last_high_water": r.last_high_water.isoformat() if r.last_high_water else None,
            "rows_seen": r.rows_seen,
            "last_error": r.last_error,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# GET /knowify/customers
# ---------------------------------------------------------------------------

@router.get("/customers")
def knowify_customers(
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Tenant-scoped customers with Knowify crosswalk fields."""
    rows = db.execute(
        select(Customer).order_by(Customer.id)
    ).scalars().all()
    return [
        {
            "id": c.id,
            "display_name": c.display_name,
            "company_name": c.company_name,
            "email": c.email,
            "phone": c.phone,
            "knowify_customer_id": c.knowify_customer_id,
        }
        for c in rows
    ]


# ---------------------------------------------------------------------------
# GET /knowify/invoices
# ---------------------------------------------------------------------------

@router.get("/invoices")
def knowify_invoices(
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Tenant-scoped invoices with Knowify crosswalk fields (source='knowify_import' and v2)."""
    rows = db.execute(
        select(Invoice).order_by(Invoice.id)
    ).scalars().all()
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "knowify_invoice_id": inv.knowify_invoice_id,
            "knowify_invoice_number": inv.knowify_invoice_number,
            "job_id": inv.job_id,
            "customer_id": inv.customer_id,
            "status": inv.status,
            "total": str(inv.total) if inv.total is not None else None,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
        }
        for inv in rows
    ]


# ---------------------------------------------------------------------------
# GET /knowify/payments
# ---------------------------------------------------------------------------

@router.get("/payments")
def knowify_payments(
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Tenant-scoped payments with Knowify crosswalk fields."""
    rows = db.execute(
        select(Payment).order_by(Payment.id)
    ).scalars().all()
    return [
        {
            "id": p.id,
            "invoice_id": p.invoice_id,
            "knowify_payment_id": p.knowify_payment_id,
            "amount": str(p.amount) if p.amount is not None else None,
            "method": p.method,
            "reference": p.reference,
            "notes": p.notes,
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        }
        for p in rows
    ]


# ---------------------------------------------------------------------------
# GET /knowify/raw/{entity}
# ---------------------------------------------------------------------------

@router.get("/raw/{entity}")
def knowify_raw(
    entity: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    is_present: Optional[bool] = Query(default=None),
    claims=Depends(require_role(_READ_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Paged raw mirror records for any entity.

    Tombstoned rows (is_present=False) are included by default so the caller can
    inspect deletions. Pass ?is_present=true to filter to live rows only.
    """
    stmt = select(KnowifyRawRecord).where(KnowifyRawRecord.entity == entity)
    if is_present is not None:
        stmt = stmt.where(KnowifyRawRecord.is_present == is_present)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    rows = db.execute(
        stmt.order_by(KnowifyRawRecord.id).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "entity": entity,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": r.id,
                "knowify_id": r.knowify_id,
                "content_hash": r.content_hash,
                "high_water": r.high_water.isoformat() if r.high_water else None,
                "is_present": r.is_present,
                "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                # payload intentionally omitted: contains customer PII; callers
                # that need raw JSON should query the DB directly (PII-safe path).
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# POST /knowify/sync-now (knowify_admin)
# ---------------------------------------------------------------------------

@router.post("/sync-now")
def knowify_sync_now(
    claims=Depends(require_role(_ADMIN_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Trigger an out-of-band Knowify sync run (admin-only).

    Calls trigger_sync() which is a seam: real impl fires the Cloud Run Job;
    tests patch it at api.routes.knowify.trigger_sync.
    """
    result = trigger_sync()
    return result


# ---------------------------------------------------------------------------
# POST /knowify/reconnect (knowify_admin)
# ---------------------------------------------------------------------------

@router.post("/reconnect")
def knowify_reconnect(
    claims=Depends(require_role(_ADMIN_ROLE)),
):
    """Surface Knowify OAuth reconnect status and instructions (admin-only).

    NOTE: Knowify's interactive OAuth is currently 500ing server-side (Wave-0).
    The actual browser re-login is Jon's CLI: python scripts/knowify/knowify_oauth.py
    This endpoint surfaces that status so the UI can guide the operator.

    When Knowify's device-code or redirect OAuth recovers, the real flow will:
      1. Generate the authorization URL from the DCR client.
      2. Return it here for the UI to open.
      3. Handle the callback at GET /knowify/oauth/callback.
    """
    return {
        "status": "manual_required",
        "instructions": (
            "The Knowify refresh token has lapsed. "
            "Run: python scripts/knowify/knowify_oauth.py "
            "on the operator workstation to mint fresh tokens, "
            "then bootstrap the knowify-tokens Secret Manager secret."
        ),
        "oauth_server_status": "known_issue_500",
    }
