"""API route tests for /knowify/* endpoints (Wave 6 — read-only routes + authz).

Covers:
- GET /knowify/status  → per-entity sync health from knowify_sync_state, tenant-scoped
- GET /knowify/customers|invoices|payments → first-class mirror rows, tenant-scoped
- GET /knowify/raw/{entity} → paged raw records incl. is_present/deleted_at
- Authz: unauthenticated → 401; wrong role → 403; admin → allowed
- POST /knowify/sync-now / reconnect require knowify_admin (admin-only)
- RLS tenant-scoping: enforced by Postgres RLS FORCED policy (SQLite tests verify
  the route itself returns data; PG-specific isolation tested in test_knowify_raw.py)
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.knowify import router as knowify_router
from app.models import (
    Customer,
    Invoice,
    Job,
    KnowifyRawRecord,
    KnowifySyncState,
    Payment,
    SessionLocal,
    init_db,
)

# Mount the knowify router once (idempotent guard).
if not any(getattr(r, "path", None) == "/knowify/status" for r in appmod.app.routes):
    appmod.app.include_router(knowify_router)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Unique-ID counter so seeds don't collide across tests on the shared SQLite DB.
_counter = itertools.count(1)


def _uid() -> str:
    return str(next(_counter))


# ---------------------------------------------------------------------------
# DB + client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


def _make_client(role: str, email: str = "user@test.com", tenant_id: int = 1):
    set_verifier(lambda t: {
        "uid": "u1", "email": email, "role": role,
        "email_verified": True, "tenant_id": tenant_id,
    })
    return TestClient(appmod.app)


@pytest.fixture()
def admin_client():
    return _make_client("admin", "admin@test.com")


@pytest.fixture()
def sales_client():
    return _make_client("sales", "sales@test.com")


@pytest.fixture()
def no_auth_client():
    set_verifier(lambda t: (_ for _ in ()).throw(Exception("bad token")))
    return TestClient(appmod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Seed helpers — all IDs unique per call via _uid()
# ---------------------------------------------------------------------------

def _seed_sync_state(tenant_id: int = 1):
    """Insert two knowify_sync_state rows for a tenant."""
    n = _uid()
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    try:
        db.add(KnowifySyncState(
            entity=f"invoices-{n}", last_status="ok", rows_seen=5,
            last_run_at=_utcnow(),
        ))
        db.add(KnowifySyncState(
            entity=f"clients-{n}", last_status="error", rows_seen=0,
            last_error="HTTP 502",
        ))
        db.commit()
        return n
    finally:
        db.close()


def _seed_raw_records(tenant_id: int = 1):
    """Insert two raw records (one live, one tombstoned)."""
    n = _uid()
    entity = f"invoices-{n}"
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    try:
        db.add(KnowifyRawRecord(
            entity=entity, knowify_id=f"KW-{n}-1",
            payload={"Id": 1, "TotalAmount": "100.00"},
            content_hash="a" * 64, is_present=True,
        ))
        db.add(KnowifyRawRecord(
            entity=entity, knowify_id=f"KW-{n}-2",
            payload={"Id": 2, "TotalAmount": "50.00"},
            content_hash="b" * 64, is_present=False,
            deleted_at=_utcnow(),
        ))
        db.commit()
        return entity
    finally:
        db.close()


def _seed_first_class(tenant_id: int = 1):
    """Insert a Customer, Job, Invoice, Payment row for the given tenant."""
    n = _uid()
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    try:
        cust = Customer(display_name=f"Acme Roofing {n}", knowify_customer_id=f"KC-{n}")
        db.add(cust)
        db.flush()
        job = Job(proposal_id=None, status="pending", knowify_job_id=f"KJ-{n}")
        db.add(job)
        db.flush()
        inv = Invoice(
            job_id=job.id, customer_id=cust.id, status="sent",
            subtotal="1000.00", tax_amount="0.00", credit_amount="0.00",
            total="1000.00", created_by="sync",
            knowify_invoice_id=f"KI-{n}", knowify_invoice_number=f"INV-{n}",
        )
        db.add(inv)
        db.flush()
        pmt = Payment(
            invoice_id=inv.id, amount="500.00", method="check",
            payment_date=_utcnow(), knowify_payment_id=f"KP-{n}",
        )
        db.add(pmt)
        db.commit()
        return n
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /knowify/status
# ---------------------------------------------------------------------------

class TestKnowifyStatus:
    def test_returns_sync_health_for_tenant(self, admin_client):
        n = _seed_sync_state(tenant_id=1)
        r = admin_client.get("/knowify/status", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        entities = {row["entity"] for row in body}
        assert f"invoices-{n}" in entities
        assert f"clients-{n}" in entities
        inv_row = next(row for row in body if row["entity"] == f"invoices-{n}")
        assert inv_row["last_status"] == "ok"
        assert inv_row["rows_seen"] == 5

    def test_tenant_isolation_route_returns_list(self, admin_client):
        # SQLite has no real RLS — this verifies the route itself is functional.
        # Postgres RLS FORCED on knowify_sync_state enforces tenant-scoping in prod
        # (tested in the tenancy PG fixture suite).
        _seed_sync_state(tenant_id=1)
        r = admin_client.get("/knowify/status", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.get("/knowify/status", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_sales_role_200(self, sales_client):
        # billing_view widened to sales (Wave 3 authz update) — sales can now view legacy data.
        r = sales_client.get("/knowify/status", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /knowify/customers
# ---------------------------------------------------------------------------

class TestKnowifyCustomers:
    def test_returns_customers_with_crosswalk(self, admin_client):
        n = _seed_first_class(tenant_id=1)
        r = admin_client.get("/knowify/customers", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        row = next((c for c in body if c.get("knowify_customer_id") == f"KC-{n}"), None)
        assert row is not None
        assert row["display_name"] == f"Acme Roofing {n}"

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.get("/knowify/customers", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_sales_200(self, sales_client):
        # billing_view widened to sales (Wave 3) — sales can now view legacy data.
        r = sales_client.get("/knowify/customers", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /knowify/invoices
# ---------------------------------------------------------------------------

class TestKnowifyInvoices:
    def test_returns_invoices_with_crosswalk(self, admin_client):
        n = _seed_first_class(tenant_id=1)
        r = admin_client.get("/knowify/invoices", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        inv = next((i for i in body if i.get("knowify_invoice_id") == f"KI-{n}"), None)
        assert inv is not None
        assert inv["knowify_invoice_number"] == f"INV-{n}"
        assert "total" in inv

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.get("/knowify/invoices", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_sales_200(self, sales_client):
        # billing_view widened to sales (Wave 3) — sales can now view legacy data.
        r = sales_client.get("/knowify/invoices", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /knowify/payments
# ---------------------------------------------------------------------------

class TestKnowifyPayments:
    def test_returns_payments_with_crosswalk(self, admin_client):
        n = _seed_first_class(tenant_id=1)
        r = admin_client.get("/knowify/payments", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        pmt = next((p for p in body if p.get("knowify_payment_id") == f"KP-{n}"), None)
        assert pmt is not None
        assert pmt["amount"] == "500.00"

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.get("/knowify/payments", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_sales_200(self, sales_client):
        # billing_view widened to sales (Wave 3) — sales can now view legacy data.
        r = sales_client.get("/knowify/payments", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /knowify/raw/{entity}
# ---------------------------------------------------------------------------

class TestKnowifyRaw:
    def test_returns_paged_raw_records(self, admin_client):
        entity = _seed_raw_records(tenant_id=1)
        r = admin_client.get(f"/knowify/raw/{entity}", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 2

    def test_tombstoned_rows_visible_with_is_present_false(self, admin_client):
        entity = _seed_raw_records(tenant_id=1)
        r = admin_client.get(f"/knowify/raw/{entity}", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        items = r.json()["items"]
        # both live and tombstoned rows returned; is_present field present on each
        assert all("is_present" in item for item in items)
        tombstoned = [i for i in items if not i["is_present"]]
        assert len(tombstoned) == 1
        assert tombstoned[0]["deleted_at"] is not None

    def test_filter_present_only(self, admin_client):
        entity = _seed_raw_records(tenant_id=1)
        r = admin_client.get(
            f"/knowify/raw/{entity}?is_present=true",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert all(item["is_present"] for item in items)

    def test_pagination(self, admin_client):
        entity = _seed_raw_records(tenant_id=1)
        r = admin_client.get(
            f"/knowify/raw/{entity}?limit=1&offset=0",
            headers={"Authorization": "Bearer x"},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.get("/knowify/raw/invoices", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_sales_200(self, sales_client):
        # billing_view widened to sales (Wave 3) — sales can now view legacy data.
        r = sales_client.get("/knowify/raw/invoices", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /knowify/sync-now — knowify_admin required
# ---------------------------------------------------------------------------

class TestKnowifySyncNow:
    def test_admin_can_trigger_sync(self, admin_client):
        with patch("api.routes.knowify.trigger_sync") as mock_sync:
            mock_sync.return_value = {"triggered": True}
            r = admin_client.post("/knowify/sync-now", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        assert r.json()["triggered"] is True

    def test_sales_403(self, sales_client):
        r = sales_client.post("/knowify/sync-now", headers={"Authorization": "Bearer x"})
        assert r.status_code == 403

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.post("/knowify/sync-now", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_web_admin_403(self):
        client = _make_client("web_admin", "wa@test.com")
        r = client.post("/knowify/sync-now", headers={"Authorization": "Bearer x"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /knowify/reconnect — knowify_admin required
# ---------------------------------------------------------------------------

class TestKnowifyReconnect:
    def test_admin_gets_reconnect_payload(self, admin_client):
        r = admin_client.post("/knowify/reconnect", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        body = r.json()
        assert "status" in body
        assert "instructions" in body

    def test_sales_403(self, sales_client):
        r = sales_client.post("/knowify/reconnect", headers={"Authorization": "Bearer x"})
        assert r.status_code == 403

    def test_unauthenticated_401(self, no_auth_client):
        r = no_auth_client.post("/knowify/reconnect", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_web_admin_403(self):
        client = _make_client("web_admin", "wa@test.com")
        r = client.post("/knowify/reconnect", headers={"Authorization": "Bearer x"})
        assert r.status_code == 403
