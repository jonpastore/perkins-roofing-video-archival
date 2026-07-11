"""Sales console API — behavioral tests for Wave 2 endpoints.

Covers:
  - GET /quoting/customers: search, is_active filter, sort, pagination, total
  - PATCH /quoting/customers/{id}/deactivate: soft-deactivate
  - GET /invoices: pagination, filters (status/customer_id/source/date range), sort,
      customer_display_name join, source + knowify_invoice_number in response
  - GET /invoices/{id}: billing_view gate, customer_display_name in response
  - GET /invoices/{id}/payments: read-only list of payments for an invoice
  - GET /payments: list with search, method filter, invoice_id filter, pagination
  - GET /payments/{id}: detail
  - Role gating: sales CAN read invoices/payments (billing_view); CANNOT create invoice
      (billing_manage); CANNOT record payment (billing_manage)

SQLite in-memory via init_db(). Uses the fake-verifier pattern from test_f3_customers.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import Customer, Invoice, Payment, SessionLocal, init_db

# Idempotent router mount guard (same pattern as test_f3_customers.py)
_MOUNTED = {getattr(r, "prefix", None) for r in appmod.app.routes}
if "/payments" not in _MOUNTED:
    from api.routes.payments import router as _payments_router
    appmod.app.include_router(_payments_router)

AUTH = {"Authorization": "Bearer x"}


# ---------------------------------------------------------------------------
# DB + client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


def _admin_client() -> TestClient:
    set_verifier(lambda t: {"uid": "u1", "email": "admin@p.com", "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


def _sales_client() -> TestClient:
    set_verifier(lambda t: {"uid": "u2", "email": "sales@p.com", "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


def _web_admin_client() -> TestClient:
    set_verifier(lambda t: {"uid": "u3", "email": "wa@p.com", "role": "web_admin", "email_verified": True})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _customer(db, display_name="Alice", company_name=None, email=None, phone=None, is_active=True):
    row = Customer(
        tenant_id=1,
        display_name=display_name,
        company_name=company_name,
        email=email,
        phone=phone,
        is_active=is_active,
    )
    db.add(row)
    db.flush()
    return row


def _invoice(db, customer_id=1, status="sent", total="500.00", source="v2",
             invoice_date=None, knowify_invoice_number=None):
    inv = Invoice(
        tenant_id=1,
        job_id=1,
        customer_id=customer_id,
        status=status,
        total=total,
        subtotal=total,
        tax_amount="0.00",
        credit_amount="0.00",
        created_by="test",
        source=source,
        invoice_date=invoice_date,
        knowify_invoice_number=knowify_invoice_number,
    )
    db.add(inv)
    db.flush()
    return inv


def _payment(db, invoice_id, amount="200.00", method="check", reference=None,
             payment_date=None, knowify_payment_id=None):
    p = Payment(
        tenant_id=1,
        invoice_id=invoice_id,
        amount=amount,
        method=method,
        reference=reference,
        payment_date=payment_date or datetime(2025, 1, 1),
        knowify_payment_id=knowify_payment_id,
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# GET /quoting/customers — search
# ---------------------------------------------------------------------------

class TestCustomerSearch:
    def test_search_by_display_name(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"Roof-{tag}-Rite")
        _customer(db, display_name=f"Tile-{tag}-Masters")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search=Roof-{tag}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert f"Roof-{tag}" in data["items"][0]["display_name"]

    def test_search_by_email(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"A-{tag}", email=f"bob-{tag}@example.com")
        _customer(db, display_name=f"B-{tag}", email=f"carol-{tag}@other.com")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search=bob-{tag}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_search_by_phone(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"A-{tag}", phone=f"555-{tag[:4]}")
        _customer(db, display_name=f"B-{tag}", phone=f"666-{tag[:4]}")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search=555-{tag[:4]}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_search_case_insensitive(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"UPPER-{tag}-CASE")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search=upper-{tag}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1


class TestCustomerFilter:
    def test_is_active_true(self):
        tag = uuid.uuid4().hex[:6]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"Active-{tag}", is_active=True)
        _customer(db, display_name=f"Inactive-{tag}", is_active=False)
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search={tag}&is_active=true", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert "Active" in data["items"][0]["display_name"]

    def test_is_active_false(self):
        tag = uuid.uuid4().hex[:6]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"Active-{tag}", is_active=True)
        _customer(db, display_name=f"Inactive-{tag}", is_active=False)
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search={tag}&is_active=false", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert "Inactive" in data["items"][0]["display_name"]


class TestCustomerPaginationAndTotal:
    def test_total_and_pagination(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        for i in range(5):
            _customer(db, display_name=f"Customer-{tag}-{i:02d}")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search={tag}&limit=2&skip=0", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

    def test_page_param(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        for i in range(4):
            _customer(db, display_name=f"Page-{tag}-{i:02d}")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search={tag}&limit=2&page=2", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 4
        assert len(data["items"]) == 2

    def test_sort_asc_desc(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        _customer(db, display_name=f"ZZZ-{tag}")
        _customer(db, display_name=f"AAA-{tag}")
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/quoting/customers?search={tag}&sort=display_name&order=asc", headers=AUTH)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items[0]["display_name"].startswith("AAA")
        assert items[1]["display_name"].startswith("ZZZ")

        r2 = c.get(f"/quoting/customers?search={tag}&sort=display_name&order=desc", headers=AUTH)
        items2 = r2.json()["items"]
        assert items2[0]["display_name"].startswith("ZZZ")


# ---------------------------------------------------------------------------
# PATCH /quoting/customers/{id}/deactivate
# ---------------------------------------------------------------------------

class TestCustomerDeactivate:
    def test_deactivate_sets_is_active_false(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name="To Deactivate", is_active=True)
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.patch(f"/quoting/customers/{cid}/deactivate", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    def test_deactivate_404(self):
        c = _admin_client()
        r = c.patch("/quoting/customers/99999/deactivate", headers=AUTH)
        assert r.status_code == 404

    def test_deactivate_not_hard_delete(self):
        """Customer row still exists after deactivation."""
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name="Still Exists")
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        c.patch(f"/quoting/customers/{cid}/deactivate", headers=AUTH)

        r = c.get(f"/quoting/customers/{cid}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["is_active"] is False


# ---------------------------------------------------------------------------
# GET /invoices — list with filters, join, pagination
# ---------------------------------------------------------------------------

class TestInvoiceList:
    def test_list_returns_items_and_total(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"TestCo-{uuid.uuid4().hex[:6]}")
        _invoice(db, customer_id=cust.id)
        _invoice(db, customer_id=cust.id)
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 2

    def test_list_includes_customer_display_name(self):
        tag = uuid.uuid4().hex[:6]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"Acme-{tag}")
        _invoice(db, customer_id=cust.id)
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}", headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1
        item = r.json()["items"][0]
        assert f"Acme-{tag}" in item["customer_display_name"]

    def test_list_includes_source_and_knowify_number(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"KnowifyCo-{uuid.uuid4().hex[:6]}")
        _invoice(db, customer_id=cust.id, source="knowify_import", knowify_invoice_number="KW-001")
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}&source=knowify_import", headers=AUTH)
        assert r.status_code == 200
        item = r.json()["items"][0]
        assert item["source"] == "knowify_import"
        assert item["knowify_invoice_number"] == "KW-001"

    def test_filter_by_status(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"StatusCo-{uuid.uuid4().hex[:6]}")
        _invoice(db, customer_id=cust.id, status="sent")
        _invoice(db, customer_id=cust.id, status="paid")
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}&status=sent", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        # Filter returns only the 1 invoice whose stored status is "sent";
        # derived status from events ledger may differ in SQLite test (no events).
        assert data["total"] == 1

    def test_filter_by_customer_id(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        c1 = _customer(db, display_name=f"C1-{uuid.uuid4().hex[:6]}")
        c2 = _customer(db, display_name=f"C2-{uuid.uuid4().hex[:6]}")
        _invoice(db, customer_id=c1.id)
        _invoice(db, customer_id=c2.id)
        c1id = c1.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={c1id}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_filter_by_source(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"SrcCo-{uuid.uuid4().hex[:6]}")
        _invoice(db, customer_id=cust.id, source="v2")
        _invoice(db, customer_id=cust.id, source="knowify_import")
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}&source=knowify_import", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_filter_by_date_range(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"DateCo-{uuid.uuid4().hex[:6]}")
        _invoice(db, customer_id=cust.id, invoice_date=datetime(2025, 1, 15))
        _invoice(db, customer_id=cust.id, invoice_date=datetime(2025, 3, 1))
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}&date_from=2025-01-01&date_to=2025-01-31", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_pagination(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"PageCo-{uuid.uuid4().hex[:6]}")
        for _ in range(5):
            _invoice(db, customer_id=cust.id)
        cid = cust.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices?customer_id={cid}&limit=2&skip=0", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# GET /invoices/{id} — detail with customer_display_name
# ---------------------------------------------------------------------------

class TestInvoiceDetail:
    def test_get_includes_customer_display_name(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name="Detail Co")
        inv = _invoice(db, customer_id=cust.id)
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices/{inv_id}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["customer_display_name"] == "Detail Co"

    def test_get_404(self):
        c = _admin_client()
        r = c.get("/invoices/99999", headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /invoices/{id}/payments
# ---------------------------------------------------------------------------

class TestInvoicePayments:
    def test_list_payments_for_invoice(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db)
        inv = _invoice(db, customer_id=cust.id)
        _payment(db, invoice_id=inv.id, amount="100.00", method="check")
        _payment(db, invoice_id=inv.id, amount="50.00", method="ach")
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices/{inv_id}/payments", headers=AUTH)
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2

    def test_payments_include_knowify_payment_id(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db)
        inv = _invoice(db, customer_id=cust.id)
        _payment(db, invoice_id=inv.id, knowify_payment_id="kp-abc")
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/invoices/{inv_id}/payments", headers=AUTH)
        assert r.status_code == 200
        assert r.json()[0]["knowify_payment_id"] == "kp-abc"

    def test_invoice_not_found_returns_404(self):
        c = _admin_client()
        r = c.get("/invoices/99999/payments", headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /payments — list
# ---------------------------------------------------------------------------

class TestPaymentList:
    def test_list_returns_items_and_total(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"PayCo-{uuid.uuid4().hex[:6]}")
        inv = _invoice(db, customer_id=cust.id)
        _payment(db, invoice_id=inv.id, amount="100.00")
        _payment(db, invoice_id=inv.id, amount="200.00")
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments?invoice_id={inv_id}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert data["total"] == 2

    def test_list_includes_invoice_number_and_customer_name(self):
        tag = uuid.uuid4().hex[:6]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"JoinCo-{tag}")
        inv = _invoice(db, customer_id=cust.id)
        # Give the invoice an invoice_number so it appears in the join result
        inv.invoice_number = 9000
        _payment(db, invoice_id=inv.id, amount="50.00")
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments?invoice_id={inv_id}", headers=AUTH)
        assert r.status_code == 200
        item = r.json()["items"][0]
        assert item["invoice_number"] == 9000
        assert f"JoinCo-{tag}" in item["customer_display_name"]

    def test_filter_by_invoice_id(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"FiltCo-{uuid.uuid4().hex[:6]}")
        inv1 = _invoice(db, customer_id=cust.id)
        inv2 = _invoice(db, customer_id=cust.id)
        _payment(db, invoice_id=inv1.id)
        _payment(db, invoice_id=inv2.id)
        inv1_id = inv1.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments?invoice_id={inv1_id}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_filter_by_method(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"MethCo-{uuid.uuid4().hex[:6]}")
        inv = _invoice(db, customer_id=cust.id)
        _payment(db, invoice_id=inv.id, method="check")
        _payment(db, invoice_id=inv.id, method="ach")
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments?invoice_id={inv_id}&method=check", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_search_by_reference(self):
        tag = uuid.uuid4().hex[:8]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"RefCo-{tag}")
        inv = _invoice(db, customer_id=cust.id)
        _payment(db, invoice_id=inv.id, reference=f"CHK-{tag}")
        _payment(db, invoice_id=inv.id, reference=f"ACH-{tag}")
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments?invoice_id={inv_id}&search=CHK-{tag}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_pagination(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"PagCo-{uuid.uuid4().hex[:6]}")
        inv = _invoice(db, customer_id=cust.id)
        for _ in range(5):
            _payment(db, invoice_id=inv.id)
        inv_id = inv.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments?invoice_id={inv_id}&limit=2&skip=0", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# GET /payments/{id}
# ---------------------------------------------------------------------------

class TestPaymentDetail:
    def test_get_payment(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db)
        inv = _invoice(db, customer_id=cust.id)
        p = _payment(db, invoice_id=inv.id, amount="123.45", method="card")
        pid = p.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments/{pid}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["amount"] == "123.45"
        assert data["method"] == "card"

    def test_get_payment_includes_invoice_number_and_customer_name(self):
        tag = uuid.uuid4().hex[:6]
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db, display_name=f"DetailCo-{tag}")
        inv = _invoice(db, customer_id=cust.id)
        inv.invoice_number = 8001
        p = _payment(db, invoice_id=inv.id, amount="75.00")
        pid = p.id
        db.commit()
        db.close()

        c = _admin_client()
        r = c.get(f"/payments/{pid}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["invoice_number"] == 8001
        assert f"DetailCo-{tag}" in data["customer_display_name"]

    def test_get_payment_404(self):
        c = _admin_client()
        r = c.get("/payments/99999", headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Role gating — billing_view vs billing_manage
# ---------------------------------------------------------------------------

class TestRoleGating:
    def test_sales_can_list_invoices(self):
        c = _sales_client()
        r = c.get("/invoices", headers=AUTH)
        assert r.status_code == 200

    def test_sales_can_get_invoice(self):
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db)
        inv = _invoice(db, customer_id=cust.id)
        inv_id = inv.id
        db.commit()
        db.close()

        c = _sales_client()
        r = c.get(f"/invoices/{inv_id}", headers=AUTH)
        assert r.status_code == 200

    def test_sales_can_list_payments(self):
        c = _sales_client()
        r = c.get("/payments", headers=AUTH)
        assert r.status_code == 200

    def test_sales_cannot_create_invoice(self):
        """billing_manage is admin-only; sales must get 403."""
        c = _sales_client()
        r = c.post("/invoices", json={
            "job_id": 1, "customer_id": 1, "milestone_pct": "0.30",
            "scopes": [{"description": "Test", "scope_value": "1000.00"}],
        }, headers=AUTH)
        assert r.status_code == 403

    def test_sales_cannot_record_payment(self):
        """billing_manage is admin-only; sales must get 403."""
        db = SessionLocal()
        db.info["tenant_id"] = 1
        cust = _customer(db)
        inv = _invoice(db, customer_id=cust.id)
        inv_id = inv.id
        db.commit()
        db.close()

        c = _sales_client()
        r = c.post(f"/invoices/{inv_id}/payments", json={
            "amount": "100.00",
            "idempotency_key": uuid.uuid4().hex,
        }, headers=AUTH)
        assert r.status_code == 403

    def test_web_admin_can_list_invoices(self):
        c = _web_admin_client()
        r = c.get("/invoices", headers=AUTH)
        assert r.status_code == 200

    def test_web_admin_can_list_payments(self):
        c = _web_admin_client()
        r = c.get("/payments", headers=AUTH)
        assert r.status_code == 200
