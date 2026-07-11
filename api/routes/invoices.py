"""Invoicing + payments API (JB4). Money path — stays on Claude.

Wires the pure core engines (core/invoicing.py, core/invoice_render.py) to persistence.
Invoice numbers are issued ATOMICALLY with a single UPDATE ... RETURNING so concurrent
draw creation can't read the same counter and collide on the UNIQUE(tenant,number)
constraint (R2 C2). Every state change appends to the immutable job_billing_events
ledger; invoice status is DERIVED from it, never overwritten by hand.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adapters import gotenberg
from api.auth import get_db_session, require_role
from app.config import settings
from app.models import (
    Customer,
    Invoice,
    InvoiceLine,
    JobBillingEvent,
    MilestoneDraw,
    Payment,
    TenantInvoiceCounter,
)
from core.invoice_render import (
    DEFAULT_INVOICE_TEMPLATE_HTML,
    invoice_context,
    render_invoice_html,
)
from core.invoicing import aggregate_invoice, build_invoice_lines, derive_invoice_status

router = APIRouter(prefix="/invoices", tags=["invoices"])

# Write/mutate gate — only admin (via "*"). Covers: POST (issue invoice), POST /{id}/payments.
_ROLE = "billing_manage"
# Read-only gate — admin + web_admin + sales (via billing_view added in Wave 2).
# Covers: GET list, GET /{id}, GET /{id}/pdf, GET /{id}/payments list.
_ROLE_VIEW = "billing_view"

# Sortable columns whitelist for invoice list
_INVOICE_SORT_COLS = {
    "invoice_number": "invoice_number",
    "invoice_date": "invoice_date",
    "due_date": "due_date",
    "total": "total",
    "status": "status",
    "created_at": "created_at",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _money(raw: str, *, allow_negative: bool = False) -> str:
    """Validate a client-supplied money string at the trust boundary (security review H2).

    Rejects non-numeric, NaN/Infinity (a poison-pill that later 500s every status
    derivation), negatives (unless allowed), and absurd magnitudes. Returns the value
    normalized to 2 decimals so the ledger never stores an unparseable amount."""
    try:
        d = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(422, "amount must be a decimal number")
    if not d.is_finite():
        raise HTTPException(422, "amount must be finite")
    if not allow_negative and d < 0:
        raise HTTPException(422, "amount must be non-negative")
    if abs(d) > Decimal("100000000"):
        raise HTTPException(422, "amount out of range")
    return str(d.quantize(Decimal("0.01")))


def _issue_number(db: Session, tenant_id: int) -> int:
    """Atomically allocate the next per-tenant invoice number (R2 C2).

    Single-statement UPDATE ... RETURNING — no read-modify-write race. Ensures a
    counter row exists first (idempotent insert; Perkins is seeded at 18732 by
    migration 0030). New tenants start their sequence at 1.
    """
    ins = pg_insert if db.bind.dialect.name == "postgresql" else insert
    stmt = ins(TenantInvoiceCounter).values(tenant_id=tenant_id, last_number=0)
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.on_conflict_do_nothing(index_elements=["tenant_id"])
    else:
        stmt = stmt.prefix_with("OR IGNORE")
    db.execute(stmt)
    n = db.execute(
        update(TenantInvoiceCounter)
        .where(TenantInvoiceCounter.tenant_id == tenant_id)
        .values(last_number=TenantInvoiceCounter.last_number + 1)
        .returning(TenantInvoiceCounter.last_number)
    ).scalar_one()
    return int(n)


def _events_for(db: Session, invoice_id: int) -> list[dict]:
    rows = db.execute(
        select(JobBillingEvent.event_type, JobBillingEvent.payload, JobBillingEvent.idempotency_key)
        .where(JobBillingEvent.invoice_id == invoice_id)
    ).all()
    return [{"event_type": r[0], "payload": r[1] or {}, "idempotency_key": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ScopeIn(BaseModel):
    description: str
    scope_value: str            # per-scope CONTRACT value (Decimal string)
    scope_id: int | None = None


class DiscountIn(BaseModel):
    description: str = "Discount"
    amount: str                 # positive; billed negative


class IssueInvoiceRequest(BaseModel):
    job_id: int
    customer_id: int
    milestone_pct: str          # fraction, e.g. "0.30"
    scopes: list[ScopeIn]
    discounts: list[DiscountIn] = Field(default_factory=list)
    proposal_id: int | None = None
    milestone_draw_id: int | None = None
    invoice_date: str | None = None   # ISO date; defaults to today
    due_date: str | None = None       # defaults to invoice_date (net-0)
    comments: str | None = None


class PaymentRequest(BaseModel):
    amount: str
    method: str = "check"       # check|ach|card|cash|other
    reference: str | None = None
    notes: str | None = None
    # REQUIRED: a null key defeats dedup (Postgres treats NULLs as distinct), so a
    # double-submit would double-count the payment (security review H1). The client sends
    # one stable key per payment attempt; a replay collides on UNIQUE(tenant, key) → no-op.
    idempotency_key: str = Field(min_length=8)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _payment_dict(p: Payment) -> dict:
    return {
        "id": p.id,
        "invoice_id": p.invoice_id,
        "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        "amount": str(p.amount),
        "method": p.method,
        "reference": p.reference,
        "notes": p.notes,
        "knowify_payment_id": p.knowify_payment_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _invoice_dict(db: Session, inv: Invoice) -> dict:
    lines = db.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.sort_order)
    ).scalars().all()
    status = derive_invoice_status(_events_for(db, inv.id), inv.total)
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "job_id": inv.job_id,
        "customer_id": inv.customer_id,
        "status": status,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "milestone_pct": str(inv.milestone_pct) if inv.milestone_pct is not None else None,
        "subtotal": str(inv.subtotal),
        "tax_amount": str(inv.tax_amount),
        "total": str(inv.total),
        "lines": [
            {"line_type": ln.line_type, "description": ln.description,
             "milestone_pct": str(ln.milestone_pct) if ln.milestone_pct is not None else None,
             "subtotal": str(ln.subtotal)}
            for ln in lines
        ],
    }


@router.post("")
def issue_invoice(
    body: IssueInvoiceRequest,
    claims=Depends(require_role(_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Issue a milestone-draw invoice: allocate a number atomically, build lines,
    persist, append the ledger event, and mark the draw invoiced."""
    tenant_id = db.info["tenant_id"]
    # Bad milestone_pct / scope_value / discount amount would otherwise raise deep in the
    # engine as an unhandled 500 — validate at the boundary and return 422 (H2/M6).
    try:
        engine_lines = build_invoice_lines(
            [s.model_dump() for s in body.scopes],
            body.milestone_pct,
            discounts=[d.model_dump() for d in body.discounts],
        )
        totals = aggregate_invoice(engine_lines)
    except (ValueError, InvalidOperation) as e:
        raise HTTPException(422, f"invalid invoice input: {e}")

    try:
        inv_date = (datetime.fromisoformat(body.invoice_date) if body.invoice_date else _utcnow())
        due = datetime.fromisoformat(body.due_date) if body.due_date else inv_date
    except ValueError:
        raise HTTPException(422, "invoice_date/due_date must be ISO-8601")

    number = _issue_number(db, tenant_id)
    inv = Invoice(
        invoice_number=number, job_id=body.job_id, customer_id=body.customer_id,
        proposal_id=body.proposal_id, milestone_draw_id=body.milestone_draw_id,
        status="sent", invoice_date=inv_date, due_date=due,
        milestone_pct=body.milestone_pct, subtotal=totals["subtotal"],
        tax_amount=totals["tax_amount"], credit_amount=totals["credit_amount"],
        total=totals["total"], comments=body.comments,
        created_by=claims.get("email") or "unknown",
    )
    db.add(inv)
    db.flush()
    for ln in engine_lines:
        db.add(InvoiceLine(invoice_id=inv.id, **ln))
    db.add(JobBillingEvent(
        job_id=body.job_id, invoice_id=inv.id, event_type="invoice_issued",
        payload={"invoice_number": number, "total": totals["total"]},
        idempotency_key=f"issue:{tenant_id}:{number}", source="api",
    ))
    if body.milestone_draw_id:
        # Only a still-pending draw may be invoiced. Guarding on status prevents a
        # double-issue from silently re-pointing the draw at the newer invoice and
        # orphaning the first (security review G4). RLS also scopes this to the tenant.
        res = db.execute(
            update(MilestoneDraw)
            .where(MilestoneDraw.id == body.milestone_draw_id, MilestoneDraw.status == "pending")
            .values(status="invoiced", invoice_id=inv.id)
        )
        if res.rowcount == 0:
            raise HTTPException(409, "milestone draw not found or already invoiced")
    db.flush()
    return _invoice_dict(db, inv)


def _invoice_list_dict(inv: Invoice, customer_display_name: str | None) -> dict:
    """Light serializer for the list view: uses stored status column, no per-row queries."""
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "customer_id": inv.customer_id,
        "customer_display_name": customer_display_name,
        "status": inv.status,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "subtotal": str(inv.subtotal),
        "tax_amount": str(inv.tax_amount),
        "total": str(inv.total),
        "source": inv.source,
        "knowify_invoice_number": inv.knowify_invoice_number,
    }


@router.get("")
def list_invoices(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    page: Optional[int] = Query(None, ge=1),
    status: Optional[str] = Query(None, description="Filter by invoice status"),
    customer_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None, description="'v2' or 'knowify_import'"),
    date_from: Optional[str] = Query(None, description="ISO date — invoice_date >= date_from"),
    date_to: Optional[str] = Query(None, description="ISO date — invoice_date <= date_to"),
    sort: str = Query("invoice_date", description="Column to sort by"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    claims=Depends(require_role(_ROLE_VIEW)),
    db: Session = Depends(get_db_session),
):
    """List invoices with pagination, filters, sort, and joined customer display_name.

    Returns {items: [...], total: N}. Each item uses the stored status column
    (no N+1 per-row derive_invoice_status). GET /{id} detail uses the full ledger path.
    Gated on billing_view (admin + web_admin + sales).
    """
    offset = (page - 1) * limit if page is not None else skip

    # Build WHERE filters on Invoice alone (no join yet) — used for the count.
    filters = []
    if status:
        filters.append(Invoice.status == status)
    if customer_id is not None:
        filters.append(Invoice.customer_id == customer_id)
    if source:
        filters.append(Invoice.source == source)
    if date_from:
        try:
            filters.append(Invoice.invoice_date >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(422, "date_from must be ISO-8601")
    if date_to:
        try:
            filters.append(Invoice.invoice_date <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(422, "date_to must be ISO-8601")

    # Count on the pre-join base (correct total; no customer join needed for count).
    count_base = select(func.count()).select_from(Invoice)
    if filters:
        count_base = count_base.where(*filters)
    total = db.execute(count_base).scalar_one()

    # Sort — use getattr so we operate on the mapped column
    sort_attr = _INVOICE_SORT_COLS.get(sort, "invoice_date")
    sort_col = getattr(Invoice, sort_attr)
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()

    # Paged rows query: add Customer join only here for display_name.
    rows_q = (
        select(Invoice, Customer.display_name.label("customer_display_name"))
        .outerjoin(Customer, Customer.id == Invoice.customer_id)
        .order_by(sort_expr)
        .offset(offset)
        .limit(limit)
    )
    if filters:
        rows_q = rows_q.where(*filters)
    rows = db.execute(rows_q).all()

    items = [_invoice_list_dict(row[0], row[1]) for row in rows]
    return {"items": items, "total": total}


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, claims=Depends(require_role(_ROLE_VIEW)), db: Session = Depends(get_db_session)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    d = _invoice_dict(db, inv)
    cust = db.get(Customer, inv.customer_id) if inv.customer_id else None
    d["customer_display_name"] = cust.display_name if cust else None
    d["source"] = inv.source
    d["knowify_invoice_number"] = inv.knowify_invoice_number
    return d


@router.get("/{invoice_id}/payments")
def list_invoice_payments(
    invoice_id: int,
    claims=Depends(require_role(_ROLE_VIEW)),
    db: Session = Depends(get_db_session),
):
    """Read-only list of payments recorded against an invoice (both v2 and Knowify-imported)."""
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    rows = db.execute(
        select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.payment_date.desc())
    ).scalars().all()
    return [_payment_dict(p) for p in rows]


@router.get("/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, claims=Depends(require_role(_ROLE_VIEW)), db: Session = Depends(get_db_session)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    cust = db.get(Customer, inv.customer_id)
    lines = db.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.sort_order)
    ).scalars().all()
    engine_lines = [{"description": ln.description, "milestone_pct": str(ln.milestone_pct)
                     if ln.milestone_pct is not None else None, "subtotal": str(ln.subtotal),
                     "line_type": ln.line_type} for ln in lines]
    ctx = invoice_context(
        invoice_number=inv.invoice_number, invoice_date=inv.invoice_date.date().isoformat() if inv.invoice_date else "",
        due_date=inv.due_date.date().isoformat() if inv.due_date else "",
        customer_name=cust.display_name if cust else "",
        bill_to_address="", job_name=f"Job #{inv.job_id}",
        engine_lines=engine_lines, totals={"subtotal": str(inv.subtotal), "tax_amount": str(inv.tax_amount),
                                            "credit_amount": str(inv.credit_amount), "total": str(inv.total)},
        tenant_name=settings.TENANT_NAME, tenant_license=settings.TENANT_LICENSE or None,
        comments=inv.comments,
    )
    html = render_invoice_html(DEFAULT_INVOICE_TEMPLATE_HTML, ctx)
    try:
        pdf = gotenberg.html_to_pdf(html)
    except RuntimeError as e:
        raise HTTPException(502, f"PDF service unavailable: {e}")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="invoice-{inv.invoice_number}.pdf"'})


@router.post("/{invoice_id}/payments")
def record_payment(
    invoice_id: int,
    body: PaymentRequest,
    claims=Depends(require_role(_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Record a payment, append the ledger event, and return the DERIVED status.

    A replayed request (same idempotency_key) collides on UNIQUE(tenant, key) and is
    returned as a no-op with the current status, so a double-submit can't double-count
    the payment (security review H1)."""
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    amount = _money(body.amount)  # reject negative/NaN/oversized before it hits the ledger (H2)

    # Payment row + ledger event share one transaction; the ledger's unique key is the
    # dedup guard. On replay the flush raises IntegrityError → return current state.
    try:
        db.add(Payment(invoice_id=inv.id, amount=amount, method=body.method,
                       reference=body.reference, notes=body.notes, payment_date=_utcnow()))
        db.add(JobBillingEvent(
            job_id=inv.job_id, invoice_id=inv.id, event_type="payment_recorded",
            payload={"amount": amount}, idempotency_key=body.idempotency_key, source="api",
        ))
        db.flush()
    except IntegrityError:
        db.rollback()
        inv = db.get(Invoice, invoice_id)
        if inv is None:
            raise HTTPException(404, "invoice not found")
        status = derive_invoice_status(_events_for(db, invoice_id), inv.total)
        return {"invoice_id": invoice_id, "status": status}

    status = derive_invoice_status(_events_for(db, inv.id), inv.total)
    db.execute(update(Invoice).where(Invoice.id == inv.id).values(status=status))
    db.flush()
    return {"invoice_id": inv.id, "status": status}
