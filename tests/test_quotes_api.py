"""Behavioral tests for GET /quotes and GET /quotes/{id}, plus role-gate tests.

Mirrors tests/test_knowify_api.py fixture style: set_verifier + shared SessionLocal
(SQLite in-memory via init_db()), seeds KnowifyRawRecord rows directly.

Covers:
- list: search, business_state filter, client_id filter, sort, pagination, total
- detail: contract fields + deliverable line-items join + project address join
- detail: 404 on missing/tombstoned contract
- role gates: sales CAN read /quotes and widened /knowify reads; CANNOT hit sync-now
"""
from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.quotes import router as quotes_router
from app.models import KnowifyRawRecord, SessionLocal, init_db

# Mount the quotes router once (idempotent guard).
if not any(getattr(r, "path", None) == "/quotes" for r in appmod.app.routes):
    appmod.app.include_router(quotes_router)

_counter = itertools.count(1000)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CONTRACT_1 = {
    "Id": "C1",
    "ContractType": "Standard",
    "BusinessState": "Signed",
    "ContractName": "ACME Roofing Repair",
    "OriginalContractSum": "15000.00",
    "CurrentContractSum": "15000.00",
    "AdditionalContractSum": "0.00",
    "DepositAmount": "5000.00",
    "ClientId": "CL1",
    "ProjectId": "P1",
    "DateCreated": "2024-03-01",
    "ExpirationDate": "2024-04-01",
    "IsSigned": True,
    "PONumber": "PO-100",
    "ContactName": "Bob Smith",
}

_CONTRACT_2 = {
    "Id": "C2",
    "ContractType": "Insurance",
    "BusinessState": "Draft",
    "ContractName": "Johnson Insurance Claim",
    "OriginalContractSum": "32000.00",
    "CurrentContractSum": "32000.00",
    "AdditionalContractSum": "1500.00",
    "DepositAmount": "0.00",
    "ClientId": "CL2",
    "ProjectId": "P2",
    "DateCreated": "2024-05-15",
    "ExpirationDate": None,
    "IsSigned": False,
    "PONumber": None,
    "ContactName": "Alice Johnson",
}

_DELIVERABLE_1A = {
    "Id": "D1",
    "ContractId": "C1",
    "Description": "Remove and replace 30sq shingles",
    "Quantity": "30",
    "UnitPrice": "450.00",
    "Price": "13500.00",
    "PriceBilled": "13500.00",
    "CostLabor": "4000.00",
    "CostMaterials": "6000.00",
    "ObjectState": "Active",
}

_DELIVERABLE_1B = {
    "Id": "D2",
    "ContractId": "C1",
    "Description": "Flashing repair",
    "Quantity": "1",
    "UnitPrice": "1500.00",
    "Price": "1500.00",
    "PriceBilled": "1500.00",
    "CostLabor": "500.00",
    "CostMaterials": "200.00",
    "ObjectState": "Active",
}

_DELIVERABLE_2A = {
    "Id": "D3",
    "ContractId": "C2",
    "Description": "Full roof replacement 45sq",
    "Quantity": "45",
    "UnitPrice": "700.00",
    "Price": "31500.00",
    "PriceBilled": "0.00",
    "CostLabor": "9000.00",
    "CostMaterials": "14000.00",
    "ObjectState": "Active",
}

_PROJECT_1 = {
    "Id": "P1",
    "Address1": "123 Main St",
    "City": "Miami",
    "StateProvince": "FL",
    "Zip": "33101",
}

_PROJECT_2 = {
    "Id": "P2",
    "Address1": "456 Oak Ave",
    "City": "Fort Lauderdale",
    "StateProvince": "FL",
    "Zip": "33301",
}


def _uid() -> str:
    return str(next(_counter))


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


def _seed():
    """Insert realistic contract/deliverable/project rows for tenant 1."""
    n = _uid()
    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        for entity, kid, payload in [
            ("contracts", f"C1-{n}", {**_CONTRACT_1, "Id": f"C1-{n}",
                                       "ProjectId": f"P1-{n}", "ClientId": f"CL1-{n}"}),
            ("contracts", f"C2-{n}", {**_CONTRACT_2, "Id": f"C2-{n}",
                                       "ProjectId": f"P2-{n}", "ClientId": f"CL2-{n}"}),
            ("deliverables", f"D1-{n}", {**_DELIVERABLE_1A, "Id": f"D1-{n}",
                                          "ContractId": f"C1-{n}"}),
            ("deliverables", f"D2-{n}", {**_DELIVERABLE_1B, "Id": f"D2-{n}",
                                          "ContractId": f"C1-{n}"}),
            ("deliverables", f"D3-{n}", {**_DELIVERABLE_2A, "Id": f"D3-{n}",
                                          "ContractId": f"C2-{n}"}),
            ("projects", f"P1-{n}", {**_PROJECT_1, "Id": f"P1-{n}"}),
            ("projects", f"P2-{n}", {**_PROJECT_2, "Id": f"P2-{n}"}),
        ]:
            db.add(KnowifyRawRecord(
                tenant_id=1, entity=entity, knowify_id=kid,
                payload=payload, content_hash="a" * 64, is_present=True,
            ))
        # Tombstoned contract — must NOT appear in results.
        db.add(KnowifyRawRecord(
            tenant_id=1, entity="contracts", knowify_id=f"CDEL-{n}",
            payload={"Id": f"CDEL-{n}", "ContractName": "Deleted Contract"},
            content_hash="b" * 64, is_present=False,
        ))
        db.commit()
        return n  # suffix to look up per-test knowify_ids
    finally:
        db.close()


def _make_client(role: str, email: str = "user@test.com") -> TestClient:
    set_verifier(lambda t: {
        "uid": "u1", "email": email, "role": role,
        "email_verified": True, "tenant_id": 1,
    })
    return TestClient(appmod.app, headers={"Authorization": "Bearer test-token"})


# ---------------------------------------------------------------------------
# List endpoint tests
# ---------------------------------------------------------------------------

class TestListQuotes:
    def test_returns_live_contracts(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    def test_tombstoned_excluded(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get("/quotes")
        ids = {item["contract_id"] for item in r.json()["items"]}
        assert f"CDEL-{n}" not in ids

    def test_search_contract_name(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"search": "ACME Roofing"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert all("ACME" in (item.get("ContractName") or "") for item in data["items"])

    def test_search_contact_name(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"search": "alice"})
        data = r.json()
        assert data["total"] >= 1
        assert all("Johnson" in (item.get("ContactName") or "") for item in data["items"])

    def test_search_po_number(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"search": "PO-100"})
        data = r.json()
        assert data["total"] >= 1

    def test_search_no_match(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"search": "zzznomatch_xyzzy"})
        assert r.json()["total"] == 0

    def test_filter_business_state(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"business_state": "Draft"})
        data = r.json()
        assert data["total"] >= 1
        assert all(item["BusinessState"] == "Draft" for item in data["items"])

    def test_filter_client_id(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"client_id": f"CL1-{n}"})
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["contract_id"] == f"C1-{n}"

    def test_sort_invalid_col_422(self):
        client = _make_client("admin")
        r = client.get("/quotes", params={"sort": "DROP TABLE"})
        assert r.status_code == 422

    def test_sort_invalid_order_422(self):
        client = _make_client("admin")
        r = client.get("/quotes", params={"order": "sideways"})
        assert r.status_code == 422

    def test_sort_by_original_contract_sum(self):
        """Numeric sort: 32000 > 15000 > 9000, not lexicographic "9…" > "3…" (fix 5)."""
        _seed()
        # Add a third contract with a value that would sort wrong lexicographically
        # ("9000" > "32000" > "15000" lexicographically but wrong numerically).
        n2 = _uid()
        db = SessionLocal()
        db.info["tenant_id"] = 1
        try:
            db.add(KnowifyRawRecord(
                tenant_id=1, entity="contracts", knowify_id=f"C3-{n2}",
                payload={**_CONTRACT_1, "Id": f"C3-{n2}", "OriginalContractSum": "9000.00",
                         "ProjectId": f"P3-{n2}", "ClientId": f"CL3-{n2}"},
                content_hash="c" * 64, is_present=True,
            ))
            db.commit()
        finally:
            db.close()

        client = _make_client("admin")
        r = client.get("/quotes", params={"sort": "OriginalContractSum", "order": "desc"})
        assert r.status_code == 200
        items = r.json()["items"]
        # Extract numeric values and verify descending numeric order
        sums = [float(item["OriginalContractSum"]) for item in items if item.get("OriginalContractSum")]
        assert sums == sorted(sums, reverse=True), f"Expected numeric desc, got: {sums}"
        # Verify the order: 32000 before 15000 before 9000
        assert sums[0] >= sums[1] >= sums[-1]
        # Specifically: 9000 must NOT appear before 32000 (catches the old lexico bug)
        idx_32k = next(i for i, s in enumerate(sums) if s == 32000.0)
        idx_9k = next(i for i, s in enumerate(sums) if s == 9000.0)
        assert idx_32k < idx_9k

    def test_pagination_limit(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"limit": 1, "page": 1})
        data = r.json()
        assert data["total"] >= 2
        assert len(data["items"]) == 1

    def test_pagination_page_2(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"limit": 1, "page": 2})
        data = r.json()
        assert data["total"] >= 2
        assert len(data["items"]) == 1

    def test_pagination_past_end_empty(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"limit": 10, "page": 9999})
        data = r.json()
        assert data["items"] == []

    def test_contract_fields_present(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get("/quotes", params={"client_id": f"CL1-{n}"})
        item = r.json()["items"][0]
        assert item["ContractName"] == "ACME Roofing Repair"
        assert item["OriginalContractSum"] == "15000.00"
        assert item["IsSigned"] is True
        assert item["DepositAmount"] == "5000.00"

    def test_total_in_response(self):
        _seed()
        client = _make_client("admin")
        r = client.get("/quotes")
        assert "total" in r.json()
        assert isinstance(r.json()["total"], int)


# ---------------------------------------------------------------------------
# Detail endpoint tests
# ---------------------------------------------------------------------------

class TestGetQuote:
    def test_detail_contract_fields(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C1-{n}")
        assert r.status_code == 200
        data = r.json()
        assert data["contract_id"] == f"C1-{n}"
        assert data["ContractName"] == "ACME Roofing Repair"
        assert data["DepositAmount"] == "5000.00"

    def test_detail_line_items(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C1-{n}")
        line_items = r.json()["line_items"]
        assert len(line_items) == 2
        ids = {li["Id"] for li in line_items}
        assert ids == {f"D1-{n}", f"D2-{n}"}

    def test_detail_line_items_only_for_this_contract(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C2-{n}")
        line_items = r.json()["line_items"]
        assert len(line_items) == 1
        assert line_items[0]["Id"] == f"D3-{n}"

    def test_detail_line_item_money_not_divided(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C1-{n}")
        d1 = next(li for li in r.json()["line_items"] if li["Id"] == f"D1-{n}")
        assert d1["Price"] == "13500.00"
        assert d1["UnitPrice"] == "450.00"

    def test_detail_project_address(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C1-{n}")
        addr = r.json()["project_address"]
        assert addr is not None
        assert addr["Address1"] == "123 Main St"
        assert addr["City"] == "Miami"
        assert addr["Zip"] == "33101"

    def test_detail_project_address_c2(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C2-{n}")
        addr = r.json()["project_address"]
        assert addr["City"] == "Fort Lauderdale"

    def test_detail_note_mentions_measurements(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/C1-{n}")
        note = r.json().get("_note", "")
        assert "measurement" in note.lower() or "Roof" in note

    def test_detail_404_missing(self):
        client = _make_client("admin")
        r = client.get("/quotes/NONEXISTENT_ID_XYZ")
        assert r.status_code == 404

    def test_detail_404_tombstoned(self):
        n = _seed()
        client = _make_client("admin")
        r = client.get(f"/quotes/CDEL-{n}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Role gate tests
# ---------------------------------------------------------------------------

class TestRoleGates:
    """sales CAN read /quotes and widened /knowify reads; CANNOT hit sync-now."""

    def test_sales_can_list_quotes(self):
        _seed()
        r = _make_client("sales").get("/quotes")
        assert r.status_code == 200

    def test_sales_can_get_quote_detail(self):
        n = _seed()
        r = _make_client("sales").get(f"/quotes/C1-{n}")
        assert r.status_code == 200

    def test_sales_can_get_knowify_status(self):
        r = _make_client("sales").get("/knowify/status")
        assert r.status_code == 200

    def test_sales_can_get_knowify_customers(self):
        r = _make_client("sales").get("/knowify/customers")
        assert r.status_code == 200

    def test_sales_can_get_knowify_invoices(self):
        r = _make_client("sales").get("/knowify/invoices")
        assert r.status_code == 200

    def test_sales_can_get_knowify_payments(self):
        r = _make_client("sales").get("/knowify/payments")
        assert r.status_code == 200

    def test_sales_can_get_knowify_raw(self):
        r = _make_client("sales").get("/knowify/raw/contracts")
        assert r.status_code == 200

    def test_sales_cannot_sync_now(self):
        r = _make_client("sales").post("/knowify/sync-now")
        assert r.status_code == 403

    def test_sales_cannot_reconnect(self):
        r = _make_client("sales").post("/knowify/reconnect")
        assert r.status_code == 403

    def test_web_admin_can_list_quotes(self):
        _seed()
        r = _make_client("web_admin").get("/quotes")
        assert r.status_code == 200

    def test_unknown_role_cannot_list_quotes(self):
        r = _make_client("viewer").get("/quotes")
        assert r.status_code == 403

    def test_unauthenticated_cannot_list_quotes(self):
        set_verifier(lambda t: (_ for _ in ()).throw(Exception("bad token")))
        r = TestClient(appmod.app, raise_server_exceptions=False).get(
            "/quotes", headers={"Authorization": "Bearer bad"}
        )
        assert r.status_code == 401
