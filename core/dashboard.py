"""Billing/analytics aggregates for the dashboard (read-only, no writes).

All functions are dialect-portable: bucketing is done in Python so they run on
SQLite (tests) and Postgres (prod) without any DB-engine-specific date functions.
Money values are returned as Decimal.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice, Payment, Proposal

# Open = money is still expected
_OPEN_STATUSES = ("sent", "viewed", "partially_paid")
_FUNNEL_STATUSES = ("draft", "sent", "viewed", "accepted", "declined", "revision_requested")

Bucket = Literal["day", "week", "month"]


def _bucket_key(dt: datetime, bucket: Bucket) -> str:
    """Return a sortable string period label for a datetime."""
    d = dt.date() if isinstance(dt, datetime) else dt
    if bucket == "day":
        return d.isoformat()
    if bucket == "week":
        # ISO week start (Monday)
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat()
    # month
    return f"{d.year}-{d.month:02d}"


# ---------------------------------------------------------------------------
# payments_over_time
# ---------------------------------------------------------------------------

def payments_over_time(
    session: Session,
    from_dt: datetime,
    to_dt: datetime,
    bucket: Bucket = "day",
) -> list[dict]:
    """Payments received in [from_dt, to_dt] (to_dt inclusive of the whole day).

    Returns [{period, total, count}] sorted by period.
    """
    to_exclusive = to_dt + timedelta(days=1)
    rows = session.execute(
        select(Payment.payment_date, Payment.amount)
        .where(Payment.payment_date >= from_dt, Payment.payment_date < to_exclusive)
    ).all()

    buckets: dict[str, dict] = {}
    for payment_date, amount in rows:
        key = _bucket_key(payment_date, bucket)
        if key not in buckets:
            buckets[key] = {"period": key, "total": Decimal("0"), "count": 0}
        buckets[key]["total"] += Decimal(str(amount))
        buckets[key]["count"] += 1

    return sorted(buckets.values(), key=lambda r: r["period"])


# ---------------------------------------------------------------------------
# invoices_issued_over_time
# ---------------------------------------------------------------------------

def invoices_issued_over_time(
    session: Session,
    from_dt: datetime,
    to_dt: datetime,
    bucket: Bucket = "day",
) -> list[dict]:
    """Invoices created in [from_dt, to_dt] (to_dt inclusive of the whole day).

    Returns [{period, total, count}] sorted by period.
    """
    to_exclusive = to_dt + timedelta(days=1)
    rows = session.execute(
        select(Invoice.created_at, Invoice.total)
        .where(Invoice.created_at >= from_dt, Invoice.created_at < to_exclusive)
    ).all()

    buckets: dict[str, dict] = {}
    for created_at, total in rows:
        key = _bucket_key(created_at, bucket)
        if key not in buckets:
            buckets[key] = {"period": key, "total": Decimal("0"), "count": 0}
        buckets[key]["total"] += Decimal(str(total))
        buckets[key]["count"] += 1

    return sorted(buckets.values(), key=lambda r: r["period"])


# ---------------------------------------------------------------------------
# open_ar_summary
# ---------------------------------------------------------------------------

def open_ar_summary(session: Session) -> dict:
    """Counts and dollar totals for open invoices.

    open_count   — number of invoices in sent/viewed/partially_paid
    open_total   — sum of invoice.total for those invoices
    outstanding_total — sum of (total - paid) for those invoices
    """
    open_invoices = session.execute(
        select(Invoice.id, Invoice.total)
        .where(Invoice.status.in_(_OPEN_STATUSES))
    ).all()

    if not open_invoices:
        return {"open_count": 0, "open_total": Decimal("0"), "outstanding_total": Decimal("0")}

    invoice_ids = [r[0] for r in open_invoices]

    paid_by_invoice: dict[int, Decimal] = {r[0]: Decimal("0") for r in open_invoices}
    payment_rows = session.execute(
        select(Payment.invoice_id, func.sum(Payment.amount))
        .where(Payment.invoice_id.in_(invoice_ids))
        .group_by(Payment.invoice_id)
    ).all()
    for inv_id, paid in payment_rows:
        paid_by_invoice[inv_id] = Decimal(str(paid))

    open_total = Decimal("0")
    outstanding_total = Decimal("0")
    for inv_id, total in open_invoices:
        t = Decimal(str(total))
        open_total += t
        outstanding_total += t - paid_by_invoice.get(inv_id, Decimal("0"))

    return {
        "open_count": len(open_invoices),
        "open_total": open_total,
        "outstanding_total": outstanding_total,
    }


# ---------------------------------------------------------------------------
# aging_buckets
# ---------------------------------------------------------------------------

def aging_buckets(session: Session, as_of: date) -> dict:
    """Outstanding $ for open invoices bucketed by days past due_date as of as_of.

    Buckets: current (not yet due), d1_30, d31_60, d61_90, d90_plus.
    """
    open_invoices = session.execute(
        select(Invoice.id, Invoice.total, Invoice.due_date)
        .where(Invoice.status.in_(_OPEN_STATUSES))
    ).all()

    if not open_invoices:
        return {"current": Decimal("0"), "d1_30": Decimal("0"),
                "d31_60": Decimal("0"), "d61_90": Decimal("0"), "d90_plus": Decimal("0")}

    invoice_ids = [r[0] for r in open_invoices]
    paid_by_invoice: dict[int, Decimal] = {r[0]: Decimal("0") for r in open_invoices}
    payment_rows = session.execute(
        select(Payment.invoice_id, func.sum(Payment.amount))
        .where(Payment.invoice_id.in_(invoice_ids))
        .group_by(Payment.invoice_id)
    ).all()
    for inv_id, paid in payment_rows:
        paid_by_invoice[inv_id] = Decimal(str(paid))

    result = {"current": Decimal("0"), "d1_30": Decimal("0"),
               "d31_60": Decimal("0"), "d61_90": Decimal("0"), "d90_plus": Decimal("0")}

    for inv_id, total, due_date in open_invoices:
        outstanding = Decimal(str(total)) - paid_by_invoice.get(inv_id, Decimal("0"))
        if outstanding <= 0:
            continue
        if due_date is None:
            result["current"] += outstanding
            continue
        due = due_date.date() if isinstance(due_date, datetime) else due_date
        days_past = (as_of - due).days
        if days_past <= 0:
            result["current"] += outstanding
        elif days_past <= 30:
            result["d1_30"] += outstanding
        elif days_past <= 60:
            result["d31_60"] += outstanding
        elif days_past <= 90:
            result["d61_90"] += outstanding
        else:
            result["d90_plus"] += outstanding

    return result


# ---------------------------------------------------------------------------
# receivables_due_next
# ---------------------------------------------------------------------------

def receivables_due_next(session: Session, as_of: date, days: int = 30) -> dict:
    """Open invoices with due_date in (as_of, as_of + days].

    Returns {count, total} — total is the OUTSTANDING balance (face value minus
    payments received) so a partially-paid invoice contributes only its unpaid
    portion, consistent with open_ar_summary.
    """
    cutoff = datetime.combine(as_of + timedelta(days=days), datetime.min.time())
    as_of_dt = datetime.combine(as_of, datetime.min.time())

    rows = session.execute(
        select(Invoice.id, Invoice.total)
        .where(
            Invoice.status.in_(_OPEN_STATUSES),
            Invoice.due_date > as_of_dt,
            Invoice.due_date <= cutoff,
        )
    ).all()

    if not rows:
        return {"count": 0, "total": Decimal("0")}

    invoice_ids = [r[0] for r in rows]
    paid_by_invoice: dict[int, Decimal] = {r[0]: Decimal("0") for r in rows}
    payment_rows = session.execute(
        select(Payment.invoice_id, func.sum(Payment.amount))
        .where(Payment.invoice_id.in_(invoice_ids))
        .group_by(Payment.invoice_id)
    ).all()
    for inv_id, paid in payment_rows:
        paid_by_invoice[inv_id] = Decimal(str(paid))

    outstanding = sum(
        (Decimal(str(r[1])) - paid_by_invoice[r[0]] for r in rows),
        Decimal("0"),
    )
    return {"count": len(rows), "total": outstanding}


# ---------------------------------------------------------------------------
# proposal_funnel
# ---------------------------------------------------------------------------

def proposal_funnel(session: Session, from_dt: datetime, to_dt: datetime) -> dict:
    """Proposal status distribution for proposals created in [from_dt, to_dt] (to_dt inclusive).

    Returns counts per status + win_rate (accepted / (accepted + declined), or 0).
    """
    to_exclusive = to_dt + timedelta(days=1)
    rows = session.execute(
        select(Proposal.status)
        .where(Proposal.created_at >= from_dt, Proposal.created_at < to_exclusive)
    ).all()

    counts: dict[str, int] = {s: 0 for s in _FUNNEL_STATUSES}
    for (status,) in rows:
        if status in counts:
            counts[status] += 1

    decided = counts["accepted"] + counts["declined"]
    win_rate = (counts["accepted"] / decided) if decided > 0 else 0.0

    return {**counts, "win_rate": win_rate}
