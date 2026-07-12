"""QuickBooks sync — stub adapter behaviour (Shape C1: stub -> live is a config flip).

The stub carries the real-shaped sync contract WITHOUT live QBO credentials:
  - one QB Invoice per Perkins Invoice (per milestone draw), never one-per-job;
  - each invoice/payment maps to a QB Customer:Job (sub-customer);
  - sync is IDEMPOTENT keyed on our invoice/payment id (a replay is a no-op that
    returns the same qb_entity_id — no double-post).

Going live means swapping StubQuickBooksClient for a real QBO OAuth client that
honours the same QuickBooksSyncClient protocol; these tests pin that contract.
"""

from adapters.quickbooks_stub import (
    QBSyncResult,
    StubQuickBooksClient,
    invoice_sync_payload,
    payment_sync_payload,
)


class _Cust:
    def __init__(self, cid, display_name, email=None):
        self.id = cid
        self.display_name = display_name
        self.email = email


class _Inv:
    def __init__(self, iid, customer_id, job_id, invoice_number, total):
        self.id = iid
        self.customer_id = customer_id
        self.job_id = job_id
        self.invoice_number = invoice_number
        self.total = total


class _Pay:
    def __init__(self, pid, invoice_id, amount, method="check"):
        self.id = pid
        self.invoice_id = invoice_id
        self.amount = amount
        self.method = method


def _client():
    return StubQuickBooksClient()


# ── payload mapping ─────────────────────────────────────────────────────────────


def test_invoice_payload_maps_customer_job_subcustomer():
    cust = _Cust(7, "Palmer Residence", "palmer@example.com")
    inv = _Inv(iid=42, customer_id=7, job_id=99, invoice_number=653, total="1500.00")
    payload = invoice_sync_payload(inv, cust)
    # QB Customer:Job sub-customer mapping (§ tim-docs invoices.md).
    assert payload["customer_ref"] == "cust:7"
    assert payload["customer_job_ref"] == "cust:7:job:99"
    assert payload["doc_number"] == "653"
    assert payload["total"] == "1500.00"


def test_payment_payload_links_invoice():
    pay = _Pay(pid=5, invoice_id=42, amount="500.00", method="ach")
    payload = payment_sync_payload(pay, qb_invoice_entity_id="QB-INV-42")
    assert payload["linked_invoice_ref"] == "QB-INV-42"
    assert payload["amount"] == "500.00"
    assert payload["method"] == "ach"


# ── one QB invoice per draw ─────────────────────────────────────────────────────


def test_sync_invoice_creates_one_qb_invoice_per_perkins_invoice():
    c = _client()
    cust = _Cust(7, "Palmer Residence")
    inv_a = _Inv(iid=42, customer_id=7, job_id=99, invoice_number=653, total="450.00")
    inv_b = _Inv(iid=43, customer_id=7, job_id=99, invoice_number=654, total="450.00")
    ra = c.sync_invoice(invoice_sync_payload(inv_a, cust), source_invoice_id=42)
    rb = c.sync_invoice(invoice_sync_payload(inv_b, cust), source_invoice_id=43)
    # Two Perkins invoices (draws) on the SAME job -> two distinct QB invoices.
    assert ra.qb_entity_id != rb.qb_entity_id
    assert c.invoice_count() == 2


# ── idempotency (no double-post) ────────────────────────────────────────────────


def test_sync_invoice_is_idempotent_on_source_id():
    c = _client()
    cust = _Cust(7, "Palmer Residence")
    inv = _Inv(iid=42, customer_id=7, job_id=99, invoice_number=653, total="450.00")
    r1 = c.sync_invoice(invoice_sync_payload(inv, cust), source_invoice_id=42)
    r2 = c.sync_invoice(invoice_sync_payload(inv, cust), source_invoice_id=42)
    assert r1.qb_entity_id == r2.qb_entity_id
    assert r1.created is True
    assert r2.created is False          # replay is a no-op
    assert c.invoice_count() == 1       # not double-posted


def test_sync_payment_is_idempotent_on_source_id():
    c = _client()
    r1 = c.sync_payment(payment_sync_payload(_Pay(5, 42, "500.00"), "QB-INV-42"),
                        source_payment_id=5)
    r2 = c.sync_payment(payment_sync_payload(_Pay(5, 42, "500.00"), "QB-INV-42"),
                        source_payment_id=5)
    assert r1.qb_entity_id == r2.qb_entity_id
    assert r2.created is False
    assert c.payment_count() == 1


def test_result_shape_reports_status_and_no_error():
    c = _client()
    cust = _Cust(7, "Palmer Residence")
    inv = _Inv(iid=42, customer_id=7, job_id=99, invoice_number=653, total="450.00")
    r = c.sync_invoice(invoice_sync_payload(inv, cust), source_invoice_id=42)
    assert isinstance(r, QBSyncResult)
    assert r.status == "synced"         # maps to Invoice.qb_sync_status
    assert r.error_message is None
    assert r.qb_entity_id.startswith("QB-")


def test_no_live_credentials_required():
    # The stub must never reach for OAuth secrets/network — constructing + syncing
    # works with zero configuration (this is what makes CI hermetic).
    c = StubQuickBooksClient()
    cust = _Cust(1, "Anyone")
    inv = _Inv(iid=1, customer_id=1, job_id=1, invoice_number=1, total="1.00")
    assert c.sync_invoice(invoice_sync_payload(inv, cust), source_invoice_id=1).status == "synced"
