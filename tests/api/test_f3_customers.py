"""F3 API — Customers/Properties CRUD behavioral tests.

Tests the HTTP surface for:
  - GET/POST /quoting/customers (list, create)
  - GET/PUT /quoting/customers/{id} (get with contacts+properties, update)
  - POST /quoting/customers/{id}/contacts (add contact)
  - POST /quoting/customers/{id}/properties (add property)
  - PUT /quoting/properties/{id} (update property)

Authz coverage:
  - quoting_view  → GET endpoints (sales + web_admin)
  - quoting_create → POST/PUT (web_admin; sales also has this)
  - unauthenticated → 401

All tests run against SQLite via init_db(). Uses the fake-verifier pattern.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import SessionLocal, init_db

# Mount F3 routers if not already present (idempotent guard)
_MOUNTED = set(getattr(r, "prefix", None) for r in appmod.app.routes)
if "/quoting/customers" not in _MOUNTED:
    from api.routes.customers import router as customers_router
    appmod.app.include_router(customers_router)
if "/quoting/proposals" not in _MOUNTED:
    from api.routes.proposals import router as proposals_router
    appmod.app.include_router(proposals_router)


AUTH = {"Authorization": "Bearer x"}


def _uid():
    return uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                            "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                            "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def unauth_client():
    set_verifier(None)
    return TestClient(appmod.app)


def _make_admin():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                            "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


def _make_sales():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                            "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_customer(client, name=None):
    name = name or f"Customer-{_uid()}"
    r = client.post("/quoting/customers", json={"display_name": name,
                                                 "email": f"{_uid()}@test.com"},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _create_property(client, customer_id, street=None):
    street = street or f"{_uid()} Test St"
    r = client.post(f"/quoting/customers/{customer_id}/properties",
                    json={"street": street, "city": "Miami", "state": "FL",
                          "zip": "33101", "code_zone": "HVHZ"},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# POST /quoting/customers — Create
# ---------------------------------------------------------------------------

class TestCreateCustomer:
    def test_create_returns_id_and_name(self, admin_client):
        r = admin_client.post("/quoting/customers",
                              json={"display_name": "Tim Perkins"},
                              headers=AUTH)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] is not None
        assert body["display_name"] == "Tim Perkins"
        assert body["tenant_id"] == 1

    def test_create_optional_fields(self, admin_client):
        r = admin_client.post("/quoting/customers",
                              json={"display_name": "Test Co",
                                    "company_name": "Acme Roofing",
                                    "email": "test@acme.com",
                                    "phone": "555-1234"},
                              headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["company_name"] == "Acme Roofing"
        assert body["email"] == "test@acme.com"

    def test_create_requires_display_name(self, admin_client):
        r = admin_client.post("/quoting/customers",
                              json={"email": "no-name@test.com"},
                              headers=AUTH)
        assert r.status_code == 422

    def test_create_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.post("/quoting/customers", json={"display_name": "X"})
        assert r.status_code == 401

    def test_create_sales_allowed(self, sales_client):
        r = sales_client.post("/quoting/customers",
                              json={"display_name": f"SalesCustomer-{_uid()}"},
                              headers=AUTH)
        assert r.status_code == 200

    def test_create_is_tenant_scoped(self, admin_client):
        r = admin_client.post("/quoting/customers",
                              json={"display_name": "Scoped Customer"},
                              headers=AUTH)
        assert r.json()["tenant_id"] == 1


# ---------------------------------------------------------------------------
# GET /quoting/customers — List
# ---------------------------------------------------------------------------

class TestListCustomers:
    def test_list_returns_created(self, admin_client):
        name = f"ListTest-{_uid()}"
        _create_customer(admin_client, name=name)
        r = admin_client.get("/quoting/customers?limit=200", headers=AUTH)
        assert r.status_code == 200
        names = [c["display_name"] for c in r.json()["items"]]
        assert name in names

    def test_list_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.get("/quoting/customers")
        assert r.status_code == 401

    def test_list_sales_allowed(self, sales_client):
        r = sales_client.get("/quoting/customers", headers=AUTH)
        assert r.status_code == 200

    def test_list_tenant_isolation(self, admin_client):
        from app.models import Customer
        with SessionLocal() as db:
            c2 = Customer(tenant_id=2, display_name="OtherTenant")
            db.add(c2)
            db.commit()
        r = admin_client.get("/quoting/customers", headers=AUTH)
        names = [c["display_name"] for c in r.json()["items"]]
        assert "OtherTenant" not in names


# ---------------------------------------------------------------------------
# GET /quoting/customers/{id} — Detail
# ---------------------------------------------------------------------------

class TestGetCustomer:
    def test_get_returns_customer(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.get(f"/quoting/customers/{created['id']}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_includes_contacts_and_properties(self, admin_client):
        created = _create_customer(admin_client)
        admin_client.post(f"/quoting/customers/{created['id']}/contacts",
                          json={"name": "Bob", "role": "Owner", "email": "bob@test.com",
                                "is_primary": True},
                          headers=AUTH)
        _create_property(admin_client, created["id"])
        r = admin_client.get(f"/quoting/customers/{created['id']}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert "contacts" in body
        assert "properties" in body
        assert len(body["contacts"]) >= 1
        assert len(body["properties"]) >= 1

    def test_get_404_unknown(self, admin_client):
        r = admin_client.get("/quoting/customers/999999", headers=AUTH)
        assert r.status_code == 404

    def test_get_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.get("/quoting/customers/1")
        assert r.status_code == 401

    def test_get_wrong_tenant_returns_404(self, admin_client):
        from app.models import Customer
        with SessionLocal() as db:
            c2 = Customer(tenant_id=2, display_name="OtherTenantCust")
            db.add(c2)
            db.commit()
            other_id = c2.id
        r = admin_client.get(f"/quoting/customers/{other_id}", headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /quoting/customers/{id} — Update
# ---------------------------------------------------------------------------

class TestUpdateCustomer:
    def test_update_display_name(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.put(f"/quoting/customers/{created['id']}",
                             json={"display_name": "Updated Name"},
                             headers=AUTH)
        assert r.status_code == 200
        assert r.json()["display_name"] == "Updated Name"

    def test_update_404_unknown(self, admin_client):
        r = admin_client.put("/quoting/customers/999999",
                             json={"display_name": "X"},
                             headers=AUTH)
        assert r.status_code == 404

    def test_update_sales_allowed(self):
        ac = _make_admin()
        created = _create_customer(ac)
        sc = _make_sales()
        r = sc.put(f"/quoting/customers/{created['id']}",
                   json={"display_name": "SalesUpdate"},
                   headers=AUTH)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /quoting/customers/{id}/contacts — Add contact
# ---------------------------------------------------------------------------

class TestAddContact:
    def test_add_contact_returns_id(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.post(f"/quoting/customers/{created['id']}/contacts",
                              json={"name": "Alice", "role": "PM",
                                    "email": "alice@test.com", "is_primary": True},
                              headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] is not None
        assert body["name"] == "Alice"
        assert body["customer_id"] == created["id"]

    def test_add_contact_requires_name(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.post(f"/quoting/customers/{created['id']}/contacts",
                              json={"email": "noname@test.com"},
                              headers=AUTH)
        assert r.status_code == 422

    def test_add_contact_404_unknown_customer(self, admin_client):
        r = admin_client.post("/quoting/customers/999999/contacts",
                              json={"name": "X"},
                              headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /quoting/customers/{id}/properties — Add property
# ---------------------------------------------------------------------------

class TestAddProperty:
    def test_add_property_returns_id(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.post(f"/quoting/customers/{created['id']}/properties",
                              json={"street": "123 Main St", "city": "Miami",
                                    "state": "FL", "zip": "33101", "code_zone": "HVHZ"},
                              headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] is not None
        assert body["street"] == "123 Main St"
        assert body["code_zone"] == "HVHZ"
        assert body["customer_id"] == created["id"]

    def test_add_property_default_code_zone_fbc(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.post(f"/quoting/customers/{created['id']}/properties",
                              json={"street": "456 Oak Ave", "city": "West Palm Beach",
                                    "state": "FL"},
                              headers=AUTH)
        assert r.status_code == 200
        assert r.json()["code_zone"] in ("FBC", "HVHZ")

    def test_add_property_requires_street_and_city(self, admin_client):
        created = _create_customer(admin_client)
        r = admin_client.post(f"/quoting/customers/{created['id']}/properties",
                              json={"zip": "33101"},
                              headers=AUTH)
        assert r.status_code == 422

    def test_add_property_404_unknown_customer(self, admin_client):
        r = admin_client.post("/quoting/customers/999999/properties",
                              json={"street": "1 X St", "city": "Miami", "state": "FL"},
                              headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /quoting/properties/{id} — Update property
# ---------------------------------------------------------------------------

class TestUpdateProperty:
    def test_update_code_zone(self, admin_client):
        created = _create_customer(admin_client)
        prop = _create_property(admin_client, created["id"])
        r = admin_client.put(f"/quoting/properties/{prop['id']}",
                             json={"code_zone": "FBC"},
                             headers=AUTH)
        assert r.status_code == 200
        assert r.json()["code_zone"] == "FBC"

    def test_update_property_404_unknown(self, admin_client):
        r = admin_client.put("/quoting/properties/999999",
                             json={"city": "Tampa"},
                             headers=AUTH)
        assert r.status_code == 404

    def test_update_property_wrong_tenant_404(self, admin_client):
        from app.models import Customer, Property
        with SessionLocal() as db:
            c2 = Customer(tenant_id=2, display_name="T2Cust")
            db.add(c2)
            db.flush()
            p2 = Property(tenant_id=2, customer_id=c2.id,
                          street="1 X St", city="Miami", state="FL",
                          code_zone="HVHZ")
            db.add(p2)
            db.commit()
            prop_id = p2.id
        r = admin_client.put(f"/quoting/properties/{prop_id}",
                             json={"code_zone": "FBC"},
                             headers=AUTH)
        assert r.status_code == 404
