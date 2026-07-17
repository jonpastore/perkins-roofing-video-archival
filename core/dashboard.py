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

from app.models import Branch, Customer, Invoice, Payment, Proposal

# Open = money is still expected
_OPEN_STATUSES = ("sent", "viewed", "partially_paid")
_FUNNEL_STATUSES = ("draft", "sent", "viewed", "accepted", "declined", "revision_requested")

Bucket = Literal["day", "week", "month"]

# AR aging bucket keys — shared by aging_buckets (totals) and aging_bucket_detail (drill-down).
AGING_BUCKETS = ("current", "d1_30", "d31_60", "d61_90", "d90_plus")


def branch_exists(session: Session, branch: str) -> bool:
    """True if `branch` is a valid branches.key (active or inactive — both report)."""
    return session.execute(select(Branch.id).where(Branch.key == branch)).first() is not None


def _aging_bucket_for(days_past: int) -> str:
    """Map days-past-due to an aging bucket key (matches aging_buckets thresholds)."""
    if days_past <= 0:
        return "current"
    if days_past <= 30:
        return "d1_30"
    if days_past <= 60:
        return "d31_60"
    if days_past <= 90:
        return "d61_90"
    return "d90_plus"


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


def _period_keys_between(from_dt: datetime, to_dt: datetime, bucket: Bucket) -> list[str]:
    """Return continuous period keys covering [from_dt, to_dt]."""
    cur = from_dt.date()
    end = to_dt.date()
    if bucket == "week":
        cur = cur - timedelta(days=cur.weekday())
    elif bucket == "month":
        cur = date(cur.year, cur.month, 1)

    out: list[str] = []
    while cur <= end:
        out.append(_bucket_key(cur, bucket))
        if bucket == "day":
            cur += timedelta(days=1)
        elif bucket == "week":
            cur += timedelta(days=7)
        else:
            year = cur.year + (1 if cur.month == 12 else 0)
            month = 1 if cur.month == 12 else cur.month + 1
            cur = date(year, month, 1)
    return out


# ---------------------------------------------------------------------------
# payments_over_time
# ---------------------------------------------------------------------------

def payments_over_time(
    session: Session,
    from_dt: datetime,
    to_dt: datetime,
    bucket: Bucket = "day",
    branch: str | None = None,
) -> list[dict]:
    """Payments received in [from_dt, to_dt] (to_dt inclusive of the whole day).

    branch — when given, only payments on invoices whose customer belongs to that
    branch (joined via Invoice.customer_id -> Customer.branch). Invoice.customer_id
    is NOT NULL, so this join never drops a payment for lack of a customer link.

    Returns [{period, total, count}] sorted by period.
    """
    to_exclusive = to_dt + timedelta(days=1)
    stmt = (
        select(Payment.payment_date, Payment.amount)
        .where(Payment.payment_date >= from_dt, Payment.payment_date < to_exclusive)
    )
    if branch is not None:
        stmt = (
            stmt.join(Invoice, Invoice.id == Payment.invoice_id)
            .join(Customer, Customer.id == Invoice.customer_id)
            .where(Customer.branch == branch)
        )
    rows = session.execute(stmt).all()

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
    branch: str | None = None,
) -> list[dict]:
    """Invoices issued in [from_dt, to_dt] (to_dt inclusive of the whole day).

    Bucketed by the real issue date: ``invoice_date`` when present (Knowify-imported
    invoices carry the true historical date; native v2 invoices set it at issue),
    falling back to ``created_at`` only when ``invoice_date`` is NULL. Using
    ``created_at`` alone would pile every back-filled Knowify invoice onto the import
    day, producing a single giant bar (the dashboard bug this fixes).

    branch — when given, only invoices whose customer belongs to that branch.
    Invoice.customer_id is NOT NULL, so no invoice is dropped for lack of a link.

    Returns [{period, total, count}] sorted by period.
    """
    to_exclusive = to_dt + timedelta(days=1)
    issued_at = func.coalesce(Invoice.invoice_date, Invoice.created_at)
    stmt = select(issued_at, Invoice.total).where(issued_at >= from_dt, issued_at < to_exclusive)
    if branch is not None:
        stmt = stmt.join(Customer, Customer.id == Invoice.customer_id).where(Customer.branch == branch)
    rows = session.execute(stmt).all()

    buckets: dict[str, dict] = {}
    for issued, total in rows:
        key = _bucket_key(issued, bucket)
        if key not in buckets:
            buckets[key] = {"period": key, "total": Decimal("0"), "count": 0}
        buckets[key]["total"] += Decimal(str(total))
        buckets[key]["count"] += 1

    return sorted(buckets.values(), key=lambda r: r["period"])


# ---------------------------------------------------------------------------
# open_ar_summary
# ---------------------------------------------------------------------------

def open_ar_summary(session: Session, branch: str | None = None) -> dict:
    """Counts and dollar totals for open invoices.

    open_count   — number of invoices in sent/viewed/partially_paid
    open_total   — sum of invoice.total for those invoices
    outstanding_total — sum of (total - paid) for those invoices

    branch — when given, only invoices whose customer belongs to that branch.
    Invoice.customer_id is NOT NULL, so no invoice is dropped for lack of a link.
    """
    stmt = select(Invoice.id, Invoice.total).where(Invoice.status.in_(_OPEN_STATUSES))
    if branch is not None:
        stmt = stmt.join(Customer, Customer.id == Invoice.customer_id).where(Customer.branch == branch)
    open_invoices = session.execute(stmt).all()

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

def aging_buckets(session: Session, as_of: date, branch: str | None = None) -> dict:
    """Outstanding $ for open invoices bucketed by days past due_date as of as_of.

    Buckets: current (not yet due), d1_30, d31_60, d61_90, d90_plus.

    branch — when given, only invoices whose customer belongs to that branch.
    Invoice.customer_id is NOT NULL, so no invoice is dropped for lack of a link.
    """
    stmt = select(Invoice.id, Invoice.total, Invoice.due_date).where(Invoice.status.in_(_OPEN_STATUSES))
    if branch is not None:
        stmt = stmt.join(Customer, Customer.id == Invoice.customer_id).where(Customer.branch == branch)
    open_invoices = session.execute(stmt).all()

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
        result[_aging_bucket_for(days_past)] += outstanding

    return result


def aging_bucket_detail(session: Session, as_of: date, bucket: str, branch: str | None = None) -> list[dict]:
    """Open AR drill-down rows for one aging bucket.

    Returns one row per open invoice in the bucket with customer + invoice context:
    [{customer_id, customer_name, invoice_id, invoice_number, knowify_invoice_number,
      invoice_date, due_date, status, total, paid, outstanding, days_past_due}]
    sorted by oldest/most-overdue first (then customer).

    branch — when given, only invoices whose customer belongs to that branch.
    Invoice.customer_id is NOT NULL, so no invoice is dropped for lack of a link.
    """
    if bucket not in AGING_BUCKETS:
        raise ValueError(f"bucket must be one of {AGING_BUCKETS}")

    stmt = (
        select(
            Invoice.id,
            Invoice.customer_id,
            Customer.display_name,
            Invoice.invoice_number,
            Invoice.knowify_invoice_number,
            Invoice.invoice_date,
            Invoice.due_date,
            Invoice.status,
            Invoice.total,
        )
        .outerjoin(Customer, Customer.id == Invoice.customer_id)
        .where(Invoice.status.in_(_OPEN_STATUSES))
    )
    if branch is not None:
        stmt = stmt.where(Customer.branch == branch)
    open_rows = session.execute(stmt).all()

    if not open_rows:
        return []

    invoice_ids = [r[0] for r in open_rows]
    paid_by_invoice: dict[int, Decimal] = {r[0]: Decimal("0") for r in open_rows}
    payment_rows = session.execute(
        select(Payment.invoice_id, func.sum(Payment.amount))
        .where(Payment.invoice_id.in_(invoice_ids))
        .group_by(Payment.invoice_id)
    ).all()
    for inv_id, paid in payment_rows:
        paid_by_invoice[inv_id] = Decimal(str(paid))

    rows: list[dict] = []
    for (
        inv_id,
        customer_id,
        customer_name,
        invoice_number,
        knowify_invoice_number,
        invoice_date,
        due_date,
        status,
        total,
    ) in open_rows:
        paid = paid_by_invoice.get(inv_id, Decimal("0"))
        outstanding = Decimal(str(total)) - paid
        if outstanding <= 0:
            continue

        if due_date is None:
            days_past = 0
            row_bucket = "current"
        else:
            due = due_date.date() if isinstance(due_date, datetime) else due_date
            days_past = (as_of - due).days
            row_bucket = _aging_bucket_for(days_past)

        if row_bucket != bucket:
            continue

        rows.append({
            "customer_id": customer_id,
            "customer_name": customer_name,
            "invoice_id": inv_id,
            "invoice_number": invoice_number,
            "knowify_invoice_number": knowify_invoice_number,
            "invoice_date": invoice_date.isoformat() if invoice_date else None,
            "due_date": due_date.isoformat() if due_date else None,
            "status": status,
            "total": str(Decimal(str(total))),
            "paid": str(paid),
            "outstanding": str(outstanding),
            "days_past_due": days_past,
        })

    rows.sort(key=lambda r: (-int(r["days_past_due"]), r["customer_name"] or "", r["invoice_id"]))
    return rows


# ---------------------------------------------------------------------------
# receivables_due_next
# ---------------------------------------------------------------------------

def receivables_due_next(session: Session, as_of: date, days: int = 30, branch: str | None = None) -> dict:
    """Open invoices with due_date in (as_of, as_of + days].

    Returns {count, total} — total is the OUTSTANDING balance (face value minus
    payments received) so a partially-paid invoice contributes only its unpaid
    portion, consistent with open_ar_summary.

    branch — when given, only invoices whose customer belongs to that branch.
    Invoice.customer_id is NOT NULL, so no invoice is dropped for lack of a link.
    """
    cutoff = datetime.combine(as_of + timedelta(days=days), datetime.min.time())
    as_of_dt = datetime.combine(as_of, datetime.min.time())

    stmt = select(Invoice.id, Invoice.total).where(
        Invoice.status.in_(_OPEN_STATUSES),
        Invoice.due_date > as_of_dt,
        Invoice.due_date <= cutoff,
    )
    if branch is not None:
        stmt = stmt.join(Customer, Customer.id == Invoice.customer_id).where(Customer.branch == branch)
    rows = session.execute(stmt).all()

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

def proposal_funnel(session: Session, from_dt: datetime, to_dt: datetime, branch: str | None = None) -> dict:
    """Proposal status distribution for proposals created in [from_dt, to_dt] (to_dt inclusive).

    Returns counts per status + win_rate (accepted / (accepted + declined), or 0).

    branch — when given, only proposals whose customer belongs to that branch.
    Proposal.customer_id is NOT NULL, so no proposal is dropped for lack of a link.
    """
    to_exclusive = to_dt + timedelta(days=1)
    stmt = select(Proposal.status).where(Proposal.created_at >= from_dt, Proposal.created_at < to_exclusive)
    if branch is not None:
        stmt = stmt.join(Customer, Customer.id == Proposal.customer_id).where(Customer.branch == branch)
    rows = session.execute(stmt).all()

    counts: dict[str, int] = {s: 0 for s in _FUNNEL_STATUSES}
    for (status,) in rows:
        if status in counts:
            counts[status] += 1

    decided = counts["accepted"] + counts["declined"]
    win_rate = (counts["accepted"] / decided) if decided > 0 else 0.0

    return {**counts, "win_rate": win_rate}


def proposal_funnel_over_time(
    session: Session,
    from_dt: datetime,
    to_dt: datetime,
    bucket: Bucket = "day",
    branch: str | None = None,
) -> list[dict]:
    """Proposal status distribution by time bucket.

    Uses the same selected range and bucket granularity as the dashboard
    payments/invoices chart. Four bars are returned per period:
    draft, sent/viewed, accepted, declined. Revision requests are not a funnel
    terminal and are intentionally omitted from the grouped time-series view.

    branch — when given, only proposals whose customer belongs to that branch.
    Proposal.customer_id is NOT NULL, so no proposal is dropped for lack of a link.
    """
    to_exclusive = to_dt + timedelta(days=1)
    stmt = select(Proposal.created_at, Proposal.status).where(
        Proposal.created_at >= from_dt, Proposal.created_at < to_exclusive
    )
    if branch is not None:
        stmt = stmt.join(Customer, Customer.id == Proposal.customer_id).where(Customer.branch == branch)
    rows = session.execute(stmt).all()

    buckets: dict[str, dict] = {
        period: {"period": period, "draft": 0, "sent": 0, "accepted": 0, "declined": 0}
        for period in _period_keys_between(from_dt, to_dt, bucket)
    }
    for created_at, status in rows:
        key = _bucket_key(created_at, bucket)
        if key not in buckets:
            buckets[key] = {"period": key, "draft": 0, "sent": 0, "accepted": 0, "declined": 0}
        if status == "draft":
            buckets[key]["draft"] += 1
        elif status in ("sent", "viewed"):
            buckets[key]["sent"] += 1
        elif status == "accepted":
            buckets[key]["accepted"] += 1
        elif status == "declined":
            buckets[key]["declined"] += 1

    return sorted(buckets.values(), key=lambda r: r["period"])
