"""Behavioral tests for core/dashboard.py — in-memory SQLite, no network."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Invoice, Payment, Proposal
from core.dashboard import (
    aging_buckets,
    invoices_issued_over_time,
    open_ar_summary,
    payments_over_time,
    proposal_funnel,
    receivables_due_next,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _engine():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return e


def _session(engine, tenant_id: int = 1):
    factory = sessionmaker(bind=engine, future=True)
    s = factory()
    s.info["tenant_id"] = tenant_id
    return s


def _dt(y, m, d, h=0) -> datetime:
    return datetime(y, m, d, h, 0, 0)


def _invoice(session, *, status="sent", total="1000.00", due_date=None, created_at=None,
             job_id=1, customer_id=1) -> Invoice:
    inv = Invoice(
        job_id=job_id,
        customer_id=customer_id,
        status=status,
        total=total,
        subtotal=total,
        tax_amount="0.00",
        credit_amount="0.00",
        created_by="test",
    )
    if due_date is not None:
        inv.due_date = due_date
    if created_at is not None:
        inv.created_at = created_at
    session.add(inv)
    session.flush()
    return inv


def _payment(session, invoice_id: int, amount: str, payment_date: datetime) -> Payment:
    p = Payment(invoice_id=invoice_id, amount=amount, payment_date=payment_date)
    session.add(p)
    session.flush()
    return p


def _proposal(session, status="draft", created_at=None) -> Proposal:
    prop = Proposal(
        customer_id=1,
        property_id=1,
        title="Test Proposal",
        accept_token=uuid.uuid4().hex[:86],
        created_by="test",
        status=status,
        quote_snapshot={},
    )
    if created_at is not None:
        prop.created_at = created_at
    session.add(prop)
    session.flush()
    return prop


# ---------------------------------------------------------------------------
# payments_over_time
# ---------------------------------------------------------------------------

class TestPaymentsOverTime:
    def test_empty(self):
        s = _session(_engine())
        result = payments_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31))
        assert result == []

    def test_single_day_bucket(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s)
        _payment(s, inv.id, "500.00", _dt(2024, 1, 10))
        _payment(s, inv.id, "300.00", _dt(2024, 1, 10))
        result = payments_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31), bucket="day")
        assert len(result) == 1
        assert result[0]["period"] == "2024-01-10"
        assert result[0]["total"] == Decimal("800.00")
        assert result[0]["count"] == 2

    def test_multi_day_buckets(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s)
        _payment(s, inv.id, "100.00", _dt(2024, 1, 5))
        _payment(s, inv.id, "200.00", _dt(2024, 1, 6))
        result = payments_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31), bucket="day")
        assert len(result) == 2
        assert result[0]["period"] == "2024-01-05"
        assert result[1]["period"] == "2024-01-06"

    def test_week_bucket(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s)
        # 2024-01-08 is Monday; 2024-01-10 same week
        _payment(s, inv.id, "100.00", _dt(2024, 1, 8))
        _payment(s, inv.id, "200.00", _dt(2024, 1, 10))
        result = payments_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31), bucket="week")
        assert len(result) == 1
        assert result[0]["total"] == Decimal("300.00")

    def test_month_bucket(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s)
        _payment(s, inv.id, "100.00", _dt(2024, 1, 5))
        _payment(s, inv.id, "200.00", _dt(2024, 2, 5))
        result = payments_over_time(s, _dt(2024, 1, 1), _dt(2024, 3, 1), bucket="month")
        assert len(result) == 2
        assert result[0]["period"] == "2024-01"
        assert result[1]["period"] == "2024-02"

    def test_excludes_out_of_range(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s)
        _payment(s, inv.id, "999.00", _dt(2023, 12, 31))  # before range
        result = payments_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31))
        assert result == []

    def test_same_day_range_captures_that_day(self):
        """from==to must capture events on that calendar day (fix 9: to_dt inclusive)."""
        e = _engine()
        s = _session(e)
        inv = _invoice(s)
        # Payment at midday on Jan 15 — should appear when from=to=Jan 15
        _payment(s, inv.id, "250.00", _dt(2024, 1, 15, 12))
        result = payments_over_time(s, _dt(2024, 1, 15), _dt(2024, 1, 15))
        assert len(result) == 1
        assert result[0]["total"] == Decimal("250.00")



# ---------------------------------------------------------------------------
# invoices_issued_over_time
# ---------------------------------------------------------------------------

class TestInvoicesIssuedOverTime:
    def test_empty(self):
        s = _session(_engine())
        result = invoices_issued_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31))
        assert result == []

    def test_groups_by_day(self):
        e = _engine()
        s = _session(e)
        _invoice(s, total="500.00", created_at=_dt(2024, 1, 15))
        _invoice(s, total="300.00", created_at=_dt(2024, 1, 15))
        _invoice(s, total="200.00", created_at=_dt(2024, 1, 20))
        result = invoices_issued_over_time(s, _dt(2024, 1, 1), _dt(2024, 1, 31), bucket="day")
        assert len(result) == 2
        assert result[0]["period"] == "2024-01-15"
        assert result[0]["total"] == Decimal("800.00")
        assert result[0]["count"] == 2
        assert result[1]["period"] == "2024-01-20"
        assert result[1]["total"] == Decimal("200.00")

    def test_month_bucket(self):
        e = _engine()
        s = _session(e)
        _invoice(s, total="1000.00", created_at=_dt(2024, 1, 5))
        _invoice(s, total="2000.00", created_at=_dt(2024, 2, 10))
        result = invoices_issued_over_time(s, _dt(2024, 1, 1), _dt(2024, 3, 1), bucket="month")
        assert len(result) == 2
        assert result[0]["period"] == "2024-01"
        assert result[1]["period"] == "2024-02"

    def test_same_day_range_captures_that_day(self):
        """from==to must capture invoices created on that calendar day (fix 9)."""
        e = _engine()
        s = _session(e)
        _invoice(s, total="800.00", created_at=_dt(2024, 1, 20, 9))
        result = invoices_issued_over_time(s, _dt(2024, 1, 20), _dt(2024, 1, 20))
        assert len(result) == 1
        assert result[0]["total"] == Decimal("800.00")



# ---------------------------------------------------------------------------
# open_ar_summary
# ---------------------------------------------------------------------------

class TestOpenArSummary:
    def test_no_open(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="paid", total="1000.00")
        result = open_ar_summary(s)
        assert result["open_count"] == 0
        assert result["open_total"] == Decimal("0")
        assert result["outstanding_total"] == Decimal("0")

    def test_open_fully_unpaid(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="1000.00")
        _invoice(s, status="viewed", total="500.00")
        result = open_ar_summary(s)
        assert result["open_count"] == 2
        assert result["open_total"] == Decimal("1500.00")
        assert result["outstanding_total"] == Decimal("1500.00")

    def test_outstanding_is_total_minus_paid(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s, status="partially_paid", total="1000.00")
        _payment(s, inv.id, "400.00", _dt(2024, 1, 1))
        result = open_ar_summary(s)
        assert result["open_count"] == 1
        assert result["open_total"] == Decimal("1000.00")
        assert result["outstanding_total"] == Decimal("600.00")

    def test_multiple_payments_summed(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s, status="partially_paid", total="1000.00")
        _payment(s, inv.id, "200.00", _dt(2024, 1, 1))
        _payment(s, inv.id, "300.00", _dt(2024, 1, 2))
        result = open_ar_summary(s)
        assert result["outstanding_total"] == Decimal("500.00")

    def test_mix_of_open_and_closed(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="800.00")
        inv_paid = _invoice(s, status="paid", total="1000.00")
        _payment(s, inv_paid.id, "1000.00", _dt(2024, 1, 1))
        result = open_ar_summary(s)
        assert result["open_count"] == 1
        assert result["open_total"] == Decimal("800.00")
        assert result["outstanding_total"] == Decimal("800.00")


# ---------------------------------------------------------------------------
# aging_buckets
# ---------------------------------------------------------------------------

class TestAgingBuckets:
    def test_empty(self):
        s = _session(_engine())
        result = aging_buckets(s, date(2024, 3, 1))
        assert result["current"] == Decimal("0")
        assert result["d90_plus"] == Decimal("0")

    def test_current_not_yet_due(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="1000.00", due_date=_dt(2024, 3, 15))
        result = aging_buckets(s, date(2024, 3, 1))
        assert result["current"] == Decimal("1000.00")
        assert result["d1_30"] == Decimal("0")

    def test_d1_30(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="1000.00", due_date=_dt(2024, 2, 15))
        result = aging_buckets(s, date(2024, 3, 1))  # 15 days past due
        assert result["d1_30"] == Decimal("1000.00")
        assert result["current"] == Decimal("0")

    def test_d31_60(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="500.00", due_date=_dt(2024, 1, 15))
        result = aging_buckets(s, date(2024, 3, 1))  # 46 days past due
        assert result["d31_60"] == Decimal("500.00")

    def test_d61_90(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="500.00", due_date=_dt(2023, 12, 20))
        result = aging_buckets(s, date(2024, 3, 1))  # 72 days past due
        assert result["d61_90"] == Decimal("500.00")

    def test_d90_plus(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="250.00", due_date=_dt(2023, 11, 1))
        result = aging_buckets(s, date(2024, 3, 1))  # >90 days
        assert result["d90_plus"] == Decimal("250.00")

    def test_partially_paid_reduces_outstanding(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s, status="partially_paid", total="1000.00", due_date=_dt(2024, 2, 1))
        _payment(s, inv.id, "600.00", _dt(2024, 2, 5))
        result = aging_buckets(s, date(2024, 3, 1))  # 29 days past due
        assert result["d1_30"] == Decimal("400.00")

    def test_paid_invoices_excluded(self):
        e = _engine()
        s = _session(e)
        inv = _invoice(s, status="paid", total="1000.00", due_date=_dt(2024, 1, 1))
        _payment(s, inv.id, "1000.00", _dt(2024, 1, 15))
        result = aging_buckets(s, date(2024, 3, 1))
        assert all(v == Decimal("0") for v in result.values())

    def test_no_due_date_goes_to_current(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="300.00", due_date=None)
        result = aging_buckets(s, date(2024, 3, 1))
        assert result["current"] == Decimal("300.00")

    def test_zero_outstanding_skipped(self):
        # Covers `if outstanding <= 0: continue` (line 180)
        # An open invoice that has been fully paid still appears as open in status
        # (race before status update) — outstanding should be 0, skipped in buckets.
        e = _engine()
        s = _session(e)
        inv = _invoice(s, status="sent", total="500.00", due_date=_dt(2024, 2, 1))
        _payment(s, inv.id, "500.00", _dt(2024, 2, 5))
        result = aging_buckets(s, date(2024, 3, 1))
        assert all(v == Decimal("0") for v in result.values())


# ---------------------------------------------------------------------------
# receivables_due_next
# ---------------------------------------------------------------------------

class TestReceivablesDueNext:
    def test_empty(self):
        s = _session(_engine())
        result = receivables_due_next(s, date(2024, 3, 1))
        assert result["count"] == 0
        assert result["total"] == Decimal("0")

    def test_in_window(self):
        e = _engine()
        s = _session(e)
        # due in 10 days — within 30; fully unpaid so outstanding == face
        _invoice(s, status="sent", total="500.00", due_date=_dt(2024, 3, 11))
        result = receivables_due_next(s, date(2024, 3, 1), days=30)
        assert result["count"] == 1
        assert result["total"] == Decimal("500.00")

    def test_excludes_today_and_past(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="500.00", due_date=_dt(2024, 3, 1))   # exactly today — excluded (>)
        _invoice(s, status="sent", total="500.00", due_date=_dt(2024, 2, 28))  # past — excluded
        result = receivables_due_next(s, date(2024, 3, 1), days=30)
        assert result["count"] == 0

    def test_includes_last_day_of_window(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="sent", total="700.00", due_date=_dt(2024, 3, 31))  # exactly 30 days out
        result = receivables_due_next(s, date(2024, 3, 1), days=30)
        assert result["count"] == 1
        assert result["total"] == Decimal("700.00")

    def test_excludes_closed(self):
        e = _engine()
        s = _session(e)
        _invoice(s, status="paid", total="1000.00", due_date=_dt(2024, 3, 15))
        result = receivables_due_next(s, date(2024, 3, 1), days=30)
        assert result["count"] == 0

    def test_sums_outstanding_not_face_value(self):
        """Partially-paid invoice contributes only its unpaid balance (fix 8)."""
        e = _engine()
        s = _session(e)
        inv = _invoice(s, status="partially_paid", total="1000.00", due_date=_dt(2024, 3, 15))
        _payment(s, inv.id, "300.00", _dt(2024, 3, 5))
        result = receivables_due_next(s, date(2024, 3, 1), days=30)
        assert result["count"] == 1
        assert result["total"] == Decimal("700.00")

    def test_multiple_invoices_outstanding_summed(self):
        """Two partially-paid invoices: totals their outstanding balances."""
        e = _engine()
        s = _session(e)
        inv1 = _invoice(s, status="partially_paid", total="1000.00", due_date=_dt(2024, 3, 10))
        _payment(s, inv1.id, "400.00", _dt(2024, 3, 2))
        inv2 = _invoice(s, status="sent", total="500.00", due_date=_dt(2024, 3, 20))
        result = receivables_due_next(s, date(2024, 3, 1), days=30)
        assert result["count"] == 2
        # 600 + 500 = 1100
        assert result["total"] == Decimal("1100.00")


# ---------------------------------------------------------------------------
# proposal_funnel
# ---------------------------------------------------------------------------

class TestProposalFunnel:
    def test_empty(self):
        s = _session(_engine())
        result = proposal_funnel(s, _dt(2024, 1, 1), _dt(2024, 12, 31))
        assert result["win_rate"] == 0.0
        assert result["accepted"] == 0

    def test_basic_counts(self):
        e = _engine()
        s = _session(e)
        _proposal(s, status="draft",    created_at=_dt(2024, 2, 1))
        _proposal(s, status="sent",     created_at=_dt(2024, 2, 5))
        _proposal(s, status="viewed",   created_at=_dt(2024, 2, 6))
        _proposal(s, status="accepted", created_at=_dt(2024, 2, 10))
        _proposal(s, status="declined", created_at=_dt(2024, 2, 12))
        result = proposal_funnel(s, _dt(2024, 1, 1), _dt(2024, 3, 1))
        assert result["draft"] == 1
        assert result["sent"] == 1
        assert result["viewed"] == 1
        assert result["accepted"] == 1
        assert result["declined"] == 1

    def test_win_rate(self):
        e = _engine()
        s = _session(e)
        _proposal(s, status="accepted", created_at=_dt(2024, 2, 1))
        _proposal(s, status="accepted", created_at=_dt(2024, 2, 2))
        _proposal(s, status="declined", created_at=_dt(2024, 2, 3))
        result = proposal_funnel(s, _dt(2024, 1, 1), _dt(2024, 3, 1))
        # 2 accepted / (2+1) = 0.666...
        assert abs(result["win_rate"] - 2 / 3) < 1e-9

    def test_win_rate_all_accepted(self):
        e = _engine()
        s = _session(e)
        _proposal(s, status="accepted", created_at=_dt(2024, 2, 1))
        result = proposal_funnel(s, _dt(2024, 1, 1), _dt(2024, 3, 1))
        assert result["win_rate"] == 1.0

    def test_excludes_out_of_range(self):
        e = _engine()
        s = _session(e)
        _proposal(s, status="accepted", created_at=_dt(2023, 12, 1))  # before range
        result = proposal_funnel(s, _dt(2024, 1, 1), _dt(2024, 3, 1))
        assert result["accepted"] == 0
        assert result["win_rate"] == 0.0

    def test_revision_requested_counted(self):
        e = _engine()
        s = _session(e)
        _proposal(s, status="revision_requested", created_at=_dt(2024, 2, 1))
        result = proposal_funnel(s, _dt(2024, 1, 1), _dt(2024, 3, 1))
        assert result["revision_requested"] == 1
