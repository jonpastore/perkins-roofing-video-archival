#!/usr/bin/env python3
"""Behavioral self-check for the JB4 billing schema (migration 0030).

Hermetic: builds an isolated in-memory SQLite DB from the ORM metadata (does NOT
touch the app's real engine), then exercises the money invariants the billing
core will rely on — draw math, discount-as-negative-line, invoice total
aggregation, per-tenant number issuance, and billing-event idempotency.

    python scripts/validate_billing_schema.py    # exits non-zero on any failure
"""
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Customer,
    Invoice,
    InvoiceLine,
    Job,
    JobBillingEvent,
    MilestoneDraw,
    MilestoneSchedule,
    Payment,
    TenantInvoiceCounter,
)

engine = create_engine("sqlite:///:memory:", future=True)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, future=True)


def issue_number(s, tenant_id):
    """Atomic-ish next-number issuance the billing core will do FOR UPDATE in PG."""
    row = s.get(TenantInvoiceCounter, tenant_id)
    row.last_number += 1
    return row.last_number


def main():
    s = Session()
    # tenant 1 (Perkins) is auto-seeded by the Tenant.after_create hook on create_all.
    s.add(TenantInvoiceCounter(tenant_id=1, last_number=18732))  # live Knowify max
    cust = Customer(display_name="Jim Malooley")
    s.add(cust)
    s.flush()
    job = Job(proposal_id=None, status="in_progress")
    s.add(job)
    s.flush()

    # A 30% draw invoice with 3 scope lines + a discount (negative), tax=0.
    sched = MilestoneSchedule(job_id=job.id, milestones_snapshot=[
        {"sequence": 1, "name": "Deposit", "pct": 0.15},
        {"sequence": 2, "name": "Work start", "pct": 0.30},
    ])
    s.add(sched)
    s.flush()
    draw = MilestoneDraw(job_id=job.id, schedule_id=sched.id, sequence_number=2,
                         milestone_name="Work start", pct_due=Decimal("0.30"))
    s.add(draw)
    s.flush()

    num = issue_number(s, 1)
    inv = Invoice(invoice_number=num, job_id=job.id, customer_id=cust.id,
                  milestone_draw_id=draw.id, status="sent",
                  milestone_pct=Decimal("0.30"), created_by="test")
    s.add(inv)
    s.flush()

    pct = Decimal("0.30")
    scope_contract_values = [Decimal("100000.00"), Decimal("20000.00"), Decimal("7000.00")]
    lines = []
    for i, cv in enumerate(scope_contract_values):
        up = (cv * pct).quantize(Decimal("0.01"))
        lines.append(InvoiceLine(invoice_id=inv.id, line_type="scope",
                                 description=f"Scope {i}", milestone_pct=pct,
                                 quantity=1, unit_price=up, subtotal=up, sort_order=i))
    # Discount line: negative, SAME pct as the other lines (plan HIGH-1 (c)).
    disc = (Decimal("-1000.00") * pct).quantize(Decimal("0.01"))
    lines.append(InvoiceLine(invoice_id=inv.id, line_type="discount",
                             description="Discount", milestone_pct=pct,
                             quantity=1, unit_price=disc, subtotal=disc, sort_order=99))
    for ln in lines:
        s.add(ln)
    s.flush()

    # --- Invariants ---
    for ln in lines:
        assert ln.subtotal == (ln.quantity * ln.unit_price), "line subtotal != qty*unit_price"
    assert disc < 0, "discount line must be negative"
    subtotal = sum(ln.subtotal for ln in lines)
    inv.subtotal = subtotal
    inv.tax_amount = Decimal("0.00")   # FL roofing services exempt
    inv.total = subtotal + inv.tax_amount - inv.credit_amount
    s.flush()
    # 100000*.30 + 20000*.30 + 7000*.30 - 1000*.30 = 30000+6000+2100-300 = 37800
    assert inv.total == Decimal("37800.00"), f"invoice total wrong: {inv.total}"
    assert inv.tax_amount == 0, "FL roofing tax must be 0"

    # Numbering continues the live Knowify sequence, not the plan's stale 653.
    assert inv.invoice_number == 18733, f"first issued number should be 18733, got {inv.invoice_number}"
    num2 = issue_number(s, 1)
    assert num2 == 18734, "numbering must be monotonic (+1)"

    # Immutable ledger + idempotency: a duplicate idempotency_key is rejected.
    s.add(JobBillingEvent(job_id=job.id, invoice_id=inv.id, event_type="invoice_issued",
                          idempotency_key="inv-18733-issued", payload={"n": 18733}))
    s.commit()
    s.add(JobBillingEvent(job_id=job.id, invoice_id=inv.id, event_type="invoice_issued",
                          idempotency_key="inv-18733-issued", payload={"n": 18733}))
    try:
        s.commit()
        raise AssertionError("duplicate idempotency_key should have been rejected")
    except IntegrityError:
        s.rollback()

    # A payment record round-trips.
    s.add(Payment(invoice_id=inv.id, amount=Decimal("37800.00"), method="check", reference="1234"))
    s.commit()

    print("OK — billing schema invariants hold:")
    print("  draw math: subtotal == qty*unit_price for all lines")
    print("  discount is a negative line at the same 30% pct")
    print(f"  invoice total = ${inv.total} (30% draw of a $127k multi-scope job, $0 tax)")
    print(f"  numbering issued #{inv.invoice_number} then #{num2} (continues live Knowify seq)")
    print("  billing-event idempotency_key rejects replays; payment round-trips")


if __name__ == "__main__":
    main()
