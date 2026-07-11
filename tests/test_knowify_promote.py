"""TDD tests for core/knowify/promote.py — first-class promotion + ledger synthesis (Wave 3).

MONEY-CRITICAL. Proves TRD §2c exactly:
- money in DOLLARS (NO ÷100) straight to NUMERIC(12,2);
- imports never touch tenant_invoice_counters and never coerce the string
  InvoiceNumber into the integer invoice_number (AC-4);
- ONE net payment_recorded event of (Total − Outstanding) drives derived status
  (AC-14); re-sync upserts that single event on change with no double-count (AC-15);
- issued-unpaid → 'sent', Cancelled/Deleted → 'voided' (AC-16);
- imported dollar amounts == source (AC-19).

Runs against real Postgres (rls_engine) so RLS, JSONB, and the crosswalk
ON CONFLICT upserts are exercised. Marked @pytest.mark.postgres; skipped when
no PG is available. Pure-logic mapping tests also run on SQLite.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from core.invoicing import derive_invoice_status
from core.knowify.promote import (
    promote_clients,
    promote_invoices,
    promote_items,
    promote_payments,
    promote_run,
)

# ---------------------------------------------------------------------------
# Fixture payloads — the REAL anchor (Wave-0) plus the four status shapes.
# All money in DOLLARS (REST /api/v2 semantics).
# ---------------------------------------------------------------------------

CLIENT = {
    "Id": 555,
    "ClientName": "Anchor Customer LLC",   # real Knowify field (NOT "Name")
    "CompanyName": "Anchor Customer LLC",
    "Email": "billing@anchor.example",
    "PhoneNumber": "305-555-0100",          # real Knowify field (NOT "Phone")
}

# Regression fixture: a real Knowify client with a ClientName but NO CompanyName
# (very common — individual homeowners). Must map display_name from ClientName, not
# fall through to a "Knowify <id>" placeholder.
CLIENT_NO_COMPANY = {
    "Id": 556,
    "ClientName": "Physio Healing Therapy",
    "CompanyName": None,
    "Email": "fmorel@example.com",
    "PhoneNumber": "305-555-0199",
}

# Real Knowify `ServiceCatalogItems` field names (verified live via the MCP schema
# 2026-07-11): the catalog master carries `Name`, `ItemNumber` (the SKU/code — there is
# NO `Sku`), `UnitName` (there is NO `Unit`), `Price` (sell — there is NO `UnitPrice`),
# and `OurCost` (cost). Only Name/ItemNumber/UnitName/Price import; OurCost is stale (v2
# pricing is authoritative) and MUST NOT leak onto the row.
ITEM = {
    "Id": 900,
    "Name": "GAF Timberline HDZ",
    "ItemNumber": "GAF-HDZ",   # real Knowify field (NOT "Sku")
    "UnitName": "square",      # real Knowify field (NOT "Unit")
    "Price": "125.00",         # sell price — imported (real field, NOT "UnitPrice")
    "OurCost": "88.00",        # cost — MUST NOT be imported (stale, v2 is authoritative)
}

# Real fixture anchor: paid invoice #18732 (Id=2474204).
INV_PAID = {
    "Id": 2474204,
    "InvoiceNumber": "18732",
    "ClientId": 555,
    "ProjectId": 7001,
    "BusinessState": "Closed",
    "ObjectState": "Active",
    "TotalAmount": "6678.00",
    "OutstandingAmount": "0.00",
    "InvoiceDate": "2024-03-01",
    "DueDate": "2024-03-31",
}

# Its receivable payment (Id=7633145) — DOLLARS on REST, NO ÷100.
PAY_PAID = {
    "Id": 7633145,
    "InvoiceId": 2474204,
    "Amount": "6678.00",
    "Voided": False,
    "ObjectState": "Active",
    "isCreditCard": False,
    "CheckNumber": "1234",
    "PaymentDate": "2024-03-01",
    "Memo": "final draw",
}

# Issued but fully outstanding → 'sent'.
INV_SENT = {
    "Id": 3000,
    "InvoiceNumber": "18800",
    "ClientId": 555,
    "ProjectId": 7002,
    "BusinessState": "Outstanding",
    "ObjectState": "Active",
    "TotalAmount": "1000.00",
    "OutstandingAmount": "1000.00",
}

# Partially paid → 'partially_paid'.
INV_PARTIAL = {
    "Id": 3001,
    "InvoiceNumber": "18801",
    "ClientId": 555,
    "ProjectId": 7003,
    "BusinessState": "Outstanding",
    "ObjectState": "Active",
    "TotalAmount": "1000.00",
    "OutstandingAmount": "400.00",
}

# Cancelled → 'voided'.
INV_VOID = {
    "Id": 3002,
    "InvoiceNumber": "18802",
    "ClientId": 555,
    "ProjectId": 7004,
    "BusinessState": "Outstanding",
    "ObjectState": "Cancelled",
    "TotalAmount": "500.00",
    "OutstandingAmount": "500.00",
}


# ---------------------------------------------------------------------------
# SQLite pure-mapping tests (no RLS) — mapping + counter + no-÷100 invariants
# ---------------------------------------------------------------------------

def _sqlite_session(tenant_id: int = 1):
    from app.models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    sess = factory()
    sess.info["tenant_id"] = tenant_id
    return sess


class TestClientMappingSQLite:
    def test_client_promotes_to_customer(self):
        from app.models import Customer

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        cust = sess.execute(
            select(Customer).where(Customer.knowify_customer_id == "555")
        ).scalar_one()
        assert cust.display_name == "Anchor Customer LLC"
        assert cust.email == "billing@anchor.example"
        assert cust.phone == "305-555-0100"   # maps from PhoneNumber, not "Phone"

    def test_client_no_company_uses_clientname_not_placeholder(self):
        """Regression: a client with ClientName but NO CompanyName must map
        display_name from ClientName, not a 'Knowify <id>' placeholder."""
        from app.models import Customer

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT_NO_COMPANY])
        sess.flush()
        cust = sess.execute(
            select(Customer).where(Customer.knowify_customer_id == "556")
        ).scalar_one()
        assert cust.display_name == "Physio Healing Therapy"
        assert not cust.display_name.startswith("Knowify ")

    def test_inactive_objectstate_sets_is_active_false(self):
        from app.models import Customer

        sess = _sqlite_session()
        promote_clients(sess, [{**CLIENT_NO_COMPANY, "Id": 557, "ObjectState": "Inactive"}])
        sess.flush()
        cust = sess.execute(
            select(Customer).where(Customer.knowify_customer_id == "557")
        ).scalar_one()
        assert cust.is_active is False

    def test_active_client_is_active_true(self):
        from app.models import Customer

        sess = _sqlite_session()
        promote_clients(sess, [{**CLIENT, "ObjectState": "Active"}])
        sess.flush()
        cust = sess.execute(
            select(Customer).where(Customer.knowify_customer_id == "555")
        ).scalar_one()
        assert cust.is_active is True

    def test_invoice_orphan_client_creates_inactive_placeholder(self):
        """Regression: an invoice whose ClientId has no promoted client (e.g. an inactive
        client excluded from the pull) must create an inactive placeholder customer and
        link the invoice — never NULL customer_id / crash the batch."""
        from app.models import Customer, Invoice

        sess = _sqlite_session()
        promote_invoices(sess, [{
            "Id": 99001, "InvoiceNumber": "X1", "ClientId": 888888, "ProjectId": None,
            "BusinessState": "Outstanding", "ObjectState": "Active",
            "TotalAmount": "100.00", "OutstandingAmount": "100.00",
        }])
        sess.flush()
        cust = sess.execute(
            select(Customer).where(Customer.knowify_customer_id == "888888")
        ).scalar_one()
        assert cust.is_active is False
        assert cust.display_name == "Knowify 888888"
        inv = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id == "99001")
        ).scalar_one()
        assert inv.customer_id == cust.id

    def test_client_rerun_no_duplicate(self):
        from app.models import Customer

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_clients(sess, [CLIENT])
        sess.flush()
        n = sess.execute(
            select(func.count()).select_from(Customer).where(
                Customer.knowify_customer_id == "555"
            )
        ).scalar_one()
        assert n == 1


class TestItemMappingSQLite:
    def test_item_promotes_no_ourcost(self):
        from app.models import PriceBookItem

        sess = _sqlite_session()
        promote_items(sess, [ITEM])
        sess.flush()
        item = sess.execute(
            select(PriceBookItem).where(PriceBookItem.knowify_item_id == "900")
        ).scalar_one()
        assert item.name == "GAF Timberline HDZ"
        assert item.sku == "GAF-HDZ"
        assert item.unit_price == Decimal("125.00")
        # No stale OurCost anywhere on the row.
        for val in vars(item).values():
            assert val != Decimal("88.00"), "stale OurCost leaked into PriceBookItem"

    def test_item_rerun_no_duplicate(self):
        from app.models import PriceBookItem

        sess = _sqlite_session()
        promote_items(sess, [ITEM])
        sess.flush()
        promote_items(sess, [ITEM])
        sess.flush()
        n = sess.execute(
            select(func.count()).select_from(PriceBookItem).where(
                PriceBookItem.knowify_item_id == "900"
            )
        ).scalar_one()
        assert n == 1


class TestInvoiceMappingSQLite:
    def test_string_number_not_coerced_to_counter(self):
        """AC-4: string InvoiceNumber → knowify_invoice_number; integer stays NULL."""
        from app.models import Invoice

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_PAID])
        sess.flush()
        inv = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id == "2474204")
        ).scalar_one()
        assert inv.knowify_invoice_number == "18732"
        assert inv.invoice_number is None
        assert inv.source == "knowify_import"

    def test_counter_untouched(self):
        """AC-4: tenant_invoice_counters never written by import."""
        from app.models import TenantInvoiceCounter

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_PAID, INV_SENT, INV_PARTIAL, INV_VOID])
        sess.flush()
        n = sess.execute(
            select(func.count()).select_from(TenantInvoiceCounter)
        ).scalar_one()
        assert n == 0, "import must never create/advance tenant_invoice_counters"

    def test_dollars_no_divide_by_100(self):
        """AC-19: imported dollar amount == source dollars (no ÷100)."""
        from app.models import Invoice

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_PAID])
        sess.flush()
        inv = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id == "2474204")
        ).scalar_one()
        assert inv.total == Decimal("6678.00")

    def test_invoice_dates_import_from_knowify(self):
        from app.models import Invoice

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_PAID])
        sess.flush()
        inv = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id == "2474204")
        ).scalar_one()
        assert inv.invoice_date.date().isoformat() == "2024-03-01"
        assert inv.due_date.date().isoformat() == "2024-03-31"

    def test_invoice_links_customer(self):
        from app.models import Invoice

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_PAID])
        sess.flush()
        inv = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id == "2474204")
        ).scalar_one()
        assert inv.customer_id is not None

    def test_invoice_rerun_no_duplicate(self):
        from app.models import Invoice

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_PAID])
        sess.flush()
        promote_invoices(sess, [INV_PAID])
        sess.flush()
        n = sess.execute(
            select(func.count()).select_from(Invoice).where(
                Invoice.knowify_invoice_id == "2474204"
            )
        ).scalar_one()
        assert n == 1


class TestPureHelpers:
    """Pure-branch coverage that needs no Postgres."""

    def test_is_receivable_true_by_invoice(self):
        from core.knowify.promote import _is_receivable

        assert _is_receivable({"InvoiceId": 1}) is True

    def test_is_receivable_true_by_receivable_id(self):
        from core.knowify.promote import _is_receivable

        assert _is_receivable({"ReceivableId": 5, "InvoiceId": None}) is True

    def test_is_receivable_false_no_link(self):
        from core.knowify.promote import _is_receivable

        assert _is_receivable({"Id": 1}) is False

    def test_is_receivable_false_payable(self):
        from core.knowify.promote import _is_receivable

        assert _is_receivable({"InvoiceId": 1, "PayableId": 9}) is False

    def test_payment_method_card(self):
        from core.knowify.promote import _payment_method

        assert _payment_method({"isCreditCard": True}) == "card"

    def test_payment_method_check(self):
        from core.knowify.promote import _payment_method

        assert _payment_method({"CheckNumber": "1234"}) == "check"

    def test_payment_method_other(self):
        from core.knowify.promote import _payment_method

        assert _payment_method({}) == "other"

    def test_parse_date_iso_date(self):
        from core.knowify.promote import _parse_date

        assert _parse_date("2024-03-01").year == 2024

    def test_parse_date_full_iso(self):
        from core.knowify.promote import _parse_date

        assert _parse_date("2024-03-01T12:30:00Z").hour == 12

    def test_parse_date_none_and_garbage(self):
        from core.knowify.promote import _parse_date

        assert _parse_date(None) is None
        assert _parse_date("not-a-date") is None

    def test_customer_id_for_none(self):
        from core.knowify.promote import _customer_id_for

        sess = _sqlite_session()
        assert _customer_id_for(sess, None) is None


class TestJobResolutionSQLite:
    def test_projectless_invoice_reuses_placeholder_job(self):
        """Project-less imported invoices share ONE placeholder job (job_id NOT NULL)."""
        from app.models import Invoice, Job

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        inv_a = dict(INV_SENT, Id=8001, InvoiceNumber="A", ProjectId=None)
        inv_b = dict(INV_SENT, Id=8002, InvoiceNumber="B", ProjectId=None)
        promote_invoices(sess, [inv_a, inv_b])
        sess.flush()
        invs = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id.in_(["8001", "8002"]))
        ).scalars().all()
        job_ids = {i.job_id for i in invs}
        assert len(job_ids) == 1, "project-less invoices must reuse one placeholder job"
        placeholders = sess.execute(
            select(func.count()).select_from(Job).where(Job.status == "knowify_import")
        ).scalar_one()
        assert placeholders == 1

    def test_same_project_shares_job(self):
        from app.models import Invoice

        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        inv_a = dict(INV_SENT, Id=8003, InvoiceNumber="C", ProjectId=42)
        inv_b = dict(INV_SENT, Id=8004, InvoiceNumber="D", ProjectId=42)
        promote_invoices(sess, [inv_a, inv_b])
        sess.flush()
        invs = sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id.in_(["8003", "8004"]))
        ).scalars().all()
        assert len({i.job_id for i in invs}) == 1


class TestPaymentSkipSQLite:
    def test_payment_skipped_when_no_mirrored_invoice(self):
        from app.models import Payment

        sess = _sqlite_session()
        # No invoice mirrored → payment referencing it is skipped, not errored.
        n = promote_payments(sess, [dict(PAY_PAID, Id=999, InvoiceId=2474204)])
        sess.flush()
        assert n == 0
        rows = sess.execute(select(func.count()).select_from(Payment)).scalar_one()
        assert rows == 0


# ---------------------------------------------------------------------------
# Per-record error resilience — bad records skip, good ones still land
# ---------------------------------------------------------------------------

class TestErrorResilienceSQLite:
    """Each promote_* function must catch per-record errors and continue."""

    def test_client_bad_record_skipped(self):
        sess = _sqlite_session()
        # Record missing 'Id' key triggers KeyError inside promote_clients.
        n = promote_clients(sess, [{"Name": "No ID"}])
        assert n == 0

    def test_item_bad_record_skipped(self):
        sess = _sqlite_session()
        n = promote_items(sess, [{"Name": "No ID"}])
        assert n == 0

    def test_invoice_bad_record_skipped(self):
        sess = _sqlite_session()
        # Missing 'Id' key → KeyError inside promote_invoices.
        n = promote_invoices(sess, [{"InvoiceNumber": "X", "Total": "100"}])
        assert n == 0

    def test_payment_bad_record_skipped(self):
        # Seed a client + invoice so the invoice lookup succeeds, then pass
        # a payment record with no Amount → KeyError inside _money → except branch.
        sess = _sqlite_session()
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, [INV_SENT])
        sess.flush()
        # InvoiceId matches knowify_invoice_id "3000"; missing Amount → KeyError.
        bad_pay = {"Id": "9999", "InvoiceId": "3000", "ObjectState": "Active"}
        n = promote_payments(sess, [bad_pay])
        assert n == 0


# ---------------------------------------------------------------------------
# Postgres — full money path with RLS + real JSONB ledger
# ---------------------------------------------------------------------------

def _pg_session(rls_engine, tenant_id: int = 1):
    sess = rls_engine()
    sess.info["tenant_id"] = tenant_id
    return sess


def _events_for(sess, invoice_id):
    from app.models import JobBillingEvent

    rows = sess.execute(
        select(
            JobBillingEvent.event_type,
            JobBillingEvent.payload,
            JobBillingEvent.idempotency_key,
        ).where(JobBillingEvent.invoice_id == invoice_id)
    ).all()
    return [{"event_type": r[0], "payload": r[1] or {}, "idempotency_key": r[2]} for r in rows]


def _knowify_event_count(sess):
    from app.models import JobBillingEvent

    return sess.execute(
        select(func.count()).select_from(JobBillingEvent).where(
            JobBillingEvent.idempotency_key.like("knowify:%")
        )
    ).scalar_one()


@pytest.mark.postgres
class TestPromoteMoneyPathPostgres:
    def _seed_and_promote(self, sess, invoices, payments=None):
        promote_clients(sess, [CLIENT])
        sess.flush()
        promote_invoices(sess, invoices)
        sess.flush()
        if payments:
            promote_payments(sess, payments)
            sess.flush()

    def _get_invoice(self, sess, kiid):
        from app.models import Invoice

        return sess.execute(
            select(Invoice).where(Invoice.knowify_invoice_id == kiid)
        ).scalar_one()

    def test_ac14_paid_invoice_derives_paid(self, rls_engine):
        """AC-14: PAID invoice → status 'paid', paid total == invoice.total,
        via ONE net payment_recorded of Total − Outstanding dollars."""
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PAID], [PAY_PAID])
            inv = self._get_invoice(sess, "2474204")
            events = _events_for(sess, inv.id)
            assert derive_invoice_status(events, inv.total) == "paid"

            pay_events = [e for e in events if e["event_type"] == "payment_recorded"]
            assert len(pay_events) == 1, "exactly ONE net payment_recorded per invoice"
            assert Decimal(str(pay_events[0]["payload"]["amount"])) == Decimal("6678.00")
            assert inv.total == Decimal("6678.00")
            # Cached status matches derive.
            assert inv.status == "paid"
        finally:
            sess.rollback()
            sess.close()

    def test_ac16_sent_and_voided(self, rls_engine):
        """AC-16: issued-unpaid → 'sent'; Cancelled/Deleted → 'voided'."""
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_SENT, INV_VOID])

            inv_sent = self._get_invoice(sess, "3000")
            assert derive_invoice_status(_events_for(sess, inv_sent.id), inv_sent.total) == "sent"
            assert inv_sent.status == "sent"

            inv_void = self._get_invoice(sess, "3002")
            assert derive_invoice_status(_events_for(sess, inv_void.id), inv_void.total) == "voided"
            assert inv_void.status == "voided"
        finally:
            sess.rollback()
            sess.close()

    def test_partially_paid(self, rls_engine):
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PARTIAL])
            inv = self._get_invoice(sess, "3001")
            events = _events_for(sess, inv.id)
            assert derive_invoice_status(events, inv.total) == "partially_paid"
            pay = [e for e in events if e["event_type"] == "payment_recorded"]
            assert len(pay) == 1
            assert Decimal(str(pay[0]["payload"]["amount"])) == Decimal("600.00")
            assert inv.status == "partially_paid"
        finally:
            sess.rollback()
            sess.close()

    def test_ac15_resync_idempotent_no_double_count(self, rls_engine):
        """AC-15: full re-sync leaves knowify:% event count unchanged."""
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PAID], [PAY_PAID])
            sess.flush()
            count1 = _knowify_event_count(sess)

            # Full re-sync — identical payloads.
            self._seed_and_promote(sess, [INV_PAID], [PAY_PAID])
            sess.flush()
            count2 = _knowify_event_count(sess)
            assert count2 == count1, "re-sync must not add ledger events"

            inv = self._get_invoice(sess, "2474204")
            events = _events_for(sess, inv.id)
            pay = [e for e in events if e["event_type"] == "payment_recorded"]
            assert len(pay) == 1, "still exactly ONE net payment event after re-sync"
            assert Decimal(str(pay[0]["payload"]["amount"])) == Decimal("6678.00")
        finally:
            sess.rollback()
            sess.close()

    def test_ac15_changed_outstanding_upserts_net_event(self, rls_engine):
        """AC-15: changed OutstandingAmount upserts the ONE net event (no double-count,
        new paid reflected)."""
        sess = _pg_session(rls_engine)
        try:
            # First sync: partially paid $600 of $1000.
            self._seed_and_promote(sess, [INV_PARTIAL])
            sess.flush()
            inv = self._get_invoice(sess, "3001")
            events = _events_for(sess, inv.id)
            pay = [e for e in events if e["event_type"] == "payment_recorded"]
            assert Decimal(str(pay[0]["payload"]["amount"])) == Decimal("600.00")

            # Re-sync: now fully paid (Outstanding 0 → paid 1000).
            inv_now_paid = dict(INV_PARTIAL, OutstandingAmount="0.00", BusinessState="Closed")
            promote_invoices(sess, [inv_now_paid])
            sess.flush()

            events2 = _events_for(sess, inv.id)
            pay2 = [e for e in events2 if e["event_type"] == "payment_recorded"]
            assert len(pay2) == 1, "still exactly ONE net payment event (upsert, not append)"
            assert Decimal(str(pay2[0]["payload"]["amount"])) == Decimal("1000.00")
            assert derive_invoice_status(events2, inv.total) == "paid"
        finally:
            sess.rollback()
            sess.close()

    def test_ac19_dollars_match_source(self, rls_engine):
        """AC-19: imported dollar amount equals Knowify's displayed dollars (no ÷100)."""
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PAID], [PAY_PAID])
            inv = self._get_invoice(sess, "2474204")
            assert inv.total == Decimal("6678.00")

            from app.models import Payment

            pay = sess.execute(
                select(Payment).where(Payment.knowify_payment_id == "7633145")
            ).scalar_one()
            assert pay.amount == Decimal("6678.00")
        finally:
            sess.rollback()
            sess.close()

    def test_payments_receivables_only(self, rls_engine):
        """Payables / AIA / voided / non-active payments are excluded."""
        from app.models import Payment

        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PAID])
            sess.flush()
            excluded = [
                dict(PAY_PAID, Id=1, InvoiceId=None, PayableId=42, VendorId=7),
                dict(PAY_PAID, Id=2, Voided=True),
                dict(PAY_PAID, Id=3, ObjectState="Cancelled"),
                dict(PAY_PAID, Id=4, isAIA=True),
                dict(PAY_PAID, Id=5, InvoiceAIAId=99),
            ]
            promote_payments(sess, excluded + [PAY_PAID])
            sess.flush()
            rows = sess.execute(select(Payment)).scalars().all()
            kids = {r.knowify_payment_id for r in rows}
            assert kids == {"7633145"}, f"only the receivable payment should import, got {kids}"
        finally:
            sess.rollback()
            sess.close()

    def test_payment_rerun_no_duplicate(self, rls_engine):
        from app.models import Payment

        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PAID], [PAY_PAID])
            sess.flush()
            promote_payments(sess, [PAY_PAID])
            sess.flush()
            n = sess.execute(
                select(func.count()).select_from(Payment).where(
                    Payment.knowify_payment_id == "7633145"
                )
            ).scalar_one()
            assert n == 1
        finally:
            sess.rollback()
            sess.close()

    def test_promote_run_ordering(self, rls_engine):
        """promote_run drives clients → invoices → payments FK-safe (payment.invoice_id
        NOT NULL FK resolves)."""
        from app.models import Payment

        sess = _pg_session(rls_engine)
        try:
            promote_run(
                sess,
                clients=[CLIENT],
                items=[ITEM],
                invoices=[INV_PAID],
                payments=[PAY_PAID],
            )
            sess.flush()
            pay = sess.execute(
                select(Payment).where(Payment.knowify_payment_id == "7633145")
            ).scalar_one()
            assert pay.invoice_id is not None
        finally:
            sess.rollback()
            sess.close()

    def test_only_import_events_touched(self, rls_engine):
        """Native source='api' events are never mutated by the importer."""
        from app.models import JobBillingEvent

        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [INV_PAID], [PAY_PAID])
            sess.flush()
            inv = self._get_invoice(sess, "2474204")
            # Simulate a native ledger event on the same invoice.
            sess.add(JobBillingEvent(
                invoice_id=inv.id, event_type="payment_recorded",
                payload={"amount": "1.00"}, idempotency_key="native:key:1", source="api",
            ))
            sess.flush()

            # Re-sync with a changed paid amount → import upserts its own event only.
            inv_changed = dict(INV_PAID, OutstandingAmount="100.00", BusinessState="Outstanding")
            promote_invoices(sess, [inv_changed])
            sess.flush()

            native = sess.execute(
                select(JobBillingEvent).where(JobBillingEvent.idempotency_key == "native:key:1")
            ).scalar_one()
            assert native.source == "api"
            assert native.payload == {"amount": "1.00"}, "native event must be untouched"
        finally:
            sess.rollback()
            sess.close()

    def test_voided_after_payment_no_crash(self, rls_engine):
        """CRITICAL: Cancelled invoice with paid>0 → derive returns 'voided_after_payment'
        which is NOT in the CHECK constraint. Cached status must be clamped to 'voided'
        so the UPDATE does not crash. Ledger still shows both events (paid dollars visible
        via derive_invoice_status for the API)."""

        # Cancelled but only partially paid (Outstanding < Total → paid > 0).
        inv_void_paid = {
            "Id": 9001,
            "InvoiceNumber": "VOID-PAID",
            "ClientId": 555,
            "ProjectId": 9001,
            "BusinessState": "Outstanding",
            "ObjectState": "Cancelled",
            "TotalAmount": "500.00",
            "OutstandingAmount": "200.00",   # paid = 300 > 0
        }
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [inv_void_paid])
            inv = self._get_invoice(sess, "9001")
            # Cached column must be in the allowed set — no crash.
            assert inv.status == "voided", f"expected 'voided', got {inv.status!r}"
            # Ledger still contains both events; live derive reflects voided_after_payment.
            events = _events_for(sess, inv.id)
            live = derive_invoice_status(events, inv.total)
            assert live == "voided_after_payment", f"expected voided_after_payment, got {live!r}"
        finally:
            sess.rollback()
            sess.close()

    def test_refund_to_zero_clears_payment_event(self, rls_engine):
        """HIGH: re-sync where Outstanding rises back to Total (refund/reversal) must
        DELETE the net payment_recorded event so status reverts from 'paid' to 'sent'."""
        sess = _pg_session(rls_engine)
        try:
            # First sync: fully paid.
            self._seed_and_promote(sess, [INV_PAID])
            inv = self._get_invoice(sess, "2474204")
            assert derive_invoice_status(_events_for(sess, inv.id), inv.total) == "paid"

            # Re-sync: refund — Outstanding back to Total, paid = 0.
            inv_refunded = dict(INV_PAID, OutstandingAmount="6678.00", BusinessState="Outstanding")
            promote_invoices(sess, [inv_refunded])
            sess.flush()

            events = _events_for(sess, inv.id)
            pay_events = [e for e in events if e["event_type"] == "payment_recorded"]
            assert pay_events == [], "refund must remove net payment event"
            status = derive_invoice_status(events, inv.total)
            assert status == "sent", f"expected 'sent' after refund, got {status!r}"
        finally:
            sess.rollback()
            sess.close()

    def test_un_void_clears_void_event(self, rls_engine):
        """HIGH: an invoice that returns to ObjectState=Active on a later sync must have
        its stale invoice_voided event removed so status recomputes correctly."""
        sess = _pg_session(rls_engine)
        try:
            # First sync: cancelled.
            self._seed_and_promote(sess, [INV_VOID])
            inv = self._get_invoice(sess, "3002")
            assert derive_invoice_status(_events_for(sess, inv.id), inv.total) == "voided"

            # Re-sync: back to Active (un-void).
            inv_unvoided = dict(INV_VOID, ObjectState="Active", BusinessState="Outstanding")
            promote_invoices(sess, [inv_unvoided])
            sess.flush()

            events = _events_for(sess, inv.id)
            void_events = [e for e in events if e["event_type"] == "invoice_voided"]
            assert void_events == [], "un-void sync must remove the stale invoice_voided event"
            status = derive_invoice_status(events, inv.total)
            assert status == "sent", f"expected 'sent' after un-void, got {status!r}"
        finally:
            sess.rollback()
            sess.close()

    def test_zero_total_invoice(self, rls_engine):
        """MEDIUM: Total==0 invoice should not derive 'sent' (paid=0-0=0 with an issued
        event). No payment_recorded is synthesized; BusinessState=Closed maps to 'paid'
        since it is fully settled (0 outstanding of 0)."""

        inv_zero = {
            "Id": 9002,
            "InvoiceNumber": "ZERO",
            "ClientId": 555,
            "ProjectId": 9002,
            "BusinessState": "Closed",
            "ObjectState": "Active",
            "TotalAmount": "0.00",
            "OutstandingAmount": "0.00",
        }
        sess = _pg_session(rls_engine)
        try:
            self._seed_and_promote(sess, [inv_zero])
            inv = self._get_invoice(sess, "9002")
            events = _events_for(sess, inv.id)
            # No payment event should be synthesized (paid = 0, total = 0).
            pay_events = [e for e in events if e["event_type"] == "payment_recorded"]
            assert pay_events == [], "Total==0 must not synthesize a payment event"
            # BusinessState=Closed + Total==0 → cached as 'paid' (fully settled, zero-dollar).
            assert inv.status == "paid", (
                f"$0 Closed invoice should cache as 'paid', got {inv.status!r}"
            )
        finally:
            sess.rollback()
            sess.close()
