"""Invoicing + payments API (JB4). Money path — stays on Claude.

Wires the pure core engines (core/invoicing.py, core/invoice_render.py) to persistence.
Invoice numbers are issued ATOMICALLY with a single UPDATE ... RETURNING so concurrent
draw creation can't read the same counter and collide on the UNIQUE(tenant,number)
constraint (R2 C2). Every state change appends to the immutable job_billing_events
ledger; invoice status is DERIVED from it, never overwritten by hand.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from adapters import gotenberg
from api.auth import get_db_session, require_role
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

# TODO(billing_manage): reuse estimating_manage until a dedicated billing role lands.
_ROLE = "estimating_manage"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    idempotency_key: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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
    engine_lines = build_invoice_lines(
        [s.model_dump() for s in body.scopes],
        body.milestone_pct,
        discounts=[d.model_dump() for d in body.discounts],
    )
    totals = aggregate_invoice(engine_lines)

    inv_date = (datetime.fromisoformat(body.invoice_date) if body.invoice_date else _utcnow())
    due = datetime.fromisoformat(body.due_date) if body.due_date else inv_date

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
        db.execute(
            update(MilestoneDraw).where(MilestoneDraw.id == body.milestone_draw_id)
            .values(status="invoiced", invoice_id=inv.id)
        )
    db.flush()
    return _invoice_dict(db, inv)


@router.get("")
def list_invoices(claims=Depends(require_role(_ROLE)), db: Session = Depends(get_db_session)):
    rows = db.execute(select(Invoice).order_by(Invoice.id.desc())).scalars().all()
    return [_invoice_dict(db, inv) for inv in rows]


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, claims=Depends(require_role(_ROLE)), db: Session = Depends(get_db_session)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    return _invoice_dict(db, inv)


@router.get("/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, claims=Depends(require_role(_ROLE)), db: Session = Depends(get_db_session)):
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
        tenant_name="Perkins Roofing", comments=inv.comments,
    )
    html = render_invoice_html(DEFAULT_INVOICE_TEMPLATE_HTML, ctx)
    pdf = gotenberg.html_to_pdf(html)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="invoice-{inv.invoice_number}.pdf"'})


@router.post("/{invoice_id}/payments")
def record_payment(
    invoice_id: int,
    body: PaymentRequest,
    claims=Depends(require_role(_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Record a payment, append the ledger event, and return the DERIVED status."""
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    db.add(Payment(invoice_id=inv.id, amount=body.amount, method=body.method,
                   reference=body.reference, notes=body.notes, payment_date=_utcnow()))
    db.add(JobBillingEvent(
        job_id=inv.job_id, invoice_id=inv.id, event_type="payment_recorded",
        payload={"amount": body.amount}, idempotency_key=body.idempotency_key, source="api",
    ))
    db.flush()
    status = derive_invoice_status(_events_for(db, inv.id), inv.total)
    db.execute(update(Invoice).where(Invoice.id == inv.id).values(status=status))
    db.flush()
    return {"invoice_id": inv.id, "status": status}
