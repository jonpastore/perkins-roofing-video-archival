"""Billing/analytics dashboard endpoint (read-only).

GET /dashboard/billing?from=YYYY-MM-DD&to=YYYY-MM-DD&bucket=day|week|month

Gated by billing_view (admin + web_admin + sales). All aggregates are computed by
pure functions in core/dashboard.py; this module only handles HTTP plumbing.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from core.dashboard import (
    aging_buckets,
    invoices_issued_over_time,
    open_ar_summary,
    payments_over_time,
    proposal_funnel,
    receivables_due_next,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_ROLE = "billing_view"
_VALID_BUCKETS = {"day", "week", "month"}


def _parse_date(value: str | None, param: str) -> datetime:
    if not value:
        raise HTTPException(422, f"{param} is required (YYYY-MM-DD)")
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time())
    except ValueError:
        raise HTTPException(422, f"{param} must be YYYY-MM-DD")


@router.get("/billing")
def billing_dashboard(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    bucket: str = "day",
    claims=Depends(require_role(_ROLE)),
    db: Session = Depends(get_db_session),
):
    """Composite billing analytics snapshot.

    Query params:
      from   — start date inclusive (YYYY-MM-DD), required
      to     — end date inclusive (YYYY-MM-DD), required
      bucket — day | week | month (default: day)
    """
    if bucket not in _VALID_BUCKETS:
        raise HTTPException(422, f"bucket must be one of {sorted(_VALID_BUCKETS)}")

    from_dt = _parse_date(from_date, "from")
    to_dt = _parse_date(to_date, "to")
    if from_dt > to_dt:
        raise HTTPException(422, "from must be <= to")

    as_of = to_dt.date()

    return {
        "payments_over_time": payments_over_time(db, from_dt, to_dt, bucket),  # type: ignore[arg-type]
        "invoices_issued_over_time": invoices_issued_over_time(db, from_dt, to_dt, bucket),  # type: ignore[arg-type]
        "open_ar_summary": open_ar_summary(db),
        "aging_buckets": aging_buckets(db, as_of),
        "receivables_due_next_30": receivables_due_next(db, as_of, days=30),
        "proposal_funnel": proposal_funnel(db, from_dt, to_dt),
    }
