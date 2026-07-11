"""Payments — read-only list + detail (Sales console, Wave 2).

Endpoints:
  GET /payments          list payments (tenant-scoped, paginated, search/filter/sort)
  GET /payments/{id}     get payment detail

Authz:
  billing_view → all endpoints here (admin + web_admin + sales)
  billing_manage is NOT required — this is read-only. Write paths (record payment)
  remain on POST /invoices/{id}/payments, gated on billing_manage.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Customer, Invoice, Payment

router = APIRouter(prefix="/payments", tags=["payments"])

_ROLE_VIEW = "billing_view"

# Sortable columns whitelist
_PAYMENT_SORT_COLS = {
    "payment_date": Payment.payment_date,
    "amount": Payment.amount,
    "method": Payment.method,
    "created_at": Payment.created_at,
}


def _payment_dict(
    p: Payment,
    invoice_number: int | None = None,
    knowify_invoice_number: str | None = None,
    customer_display_name: str | None = None,
) -> dict:
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
        "invoice_number": invoice_number,
        "knowify_invoice_number": knowify_invoice_number,
        "customer_display_name": customer_display_name,
    }


@router.get("")
def list_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    page: Optional[int] = Query(None, ge=1),
    invoice_id: Optional[int] = Query(None, description="Filter by invoice"),
    method: Optional[str] = Query(None, description="Filter by payment method"),
    search: Optional[str] = Query(None, description="Case-insensitive match on reference"),
    date_from: Optional[str] = Query(None, description="ISO date — payment_date >="),
    date_to: Optional[str] = Query(None, description="ISO date — payment_date <="),
    sort: str = Query("payment_date", description="Column to sort by"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    claims=Depends(require_role(_ROLE_VIEW)),
    db: Session = Depends(get_db_session),
):
    """List payments with pagination, filters, and sort.

    Covers both v2-recorded payments and Knowify-imported payments
    (distinguished by knowify_payment_id being non-null).
    Returns {items: [...], total: N}.
    """
    offset = (page - 1) * limit if page is not None else skip

    base = select(Payment)

    if invoice_id is not None:
        base = base.where(Payment.invoice_id == invoice_id)
    if method:
        base = base.where(Payment.method == method)
    if search:
        term = search.lower()
        base = base.where(func.lower(Payment.reference).contains(term))
    if date_from:
        try:
            base = base.where(Payment.payment_date >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(422, "date_from must be ISO-8601")
    if date_to:
        try:
            base = base.where(Payment.payment_date <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(422, "date_to must be ISO-8601")

    sort_col = _PAYMENT_SORT_COLS.get(sort, Payment.payment_date)
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    # JOIN Invoice + Customer so we can include invoice_number + customer_display_name.
    joined = (
        base
        .outerjoin(Invoice, Payment.invoice_id == Invoice.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .add_columns(Invoice.invoice_number, Invoice.knowify_invoice_number, Customer.display_name)
        .order_by(sort_expr)
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(joined).all()
    return {
        "items": [
            _payment_dict(
                p,
                invoice_number=inv_num,
                knowify_invoice_number=knowify_inv_num,
                customer_display_name=cust_name,
            )
            for p, inv_num, knowify_inv_num, cust_name in rows
        ],
        "total": total,
    }


@router.get("/{payment_id}")
def get_payment(
    payment_id: int,
    claims=Depends(require_role(_ROLE_VIEW)),
    db: Session = Depends(get_db_session),
):
    row = db.execute(
        select(Payment, Invoice.invoice_number, Invoice.knowify_invoice_number, Customer.display_name)
        .outerjoin(Invoice, Payment.invoice_id == Invoice.id)
        .outerjoin(Customer, Invoice.customer_id == Customer.id)
        .where(Payment.id == payment_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "payment not found")
    p, inv_num, knowify_inv_num, cust_name = row
    return _payment_dict(
        p,
        invoice_number=inv_num,
        knowify_invoice_number=knowify_inv_num,
        customer_display_name=cust_name,
    )
