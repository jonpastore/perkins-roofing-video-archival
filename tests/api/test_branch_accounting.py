"""B9 scaffold — per-branch QuickBooks/Knowify mapping admin API.

Live QBO OAuth client is HELD; this only exercises the mapping CRUD (GET/PUT
/branches/{branch}/accounting) added to api/routes/branches.py.
"""
import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db

AUTH = {"Authorization": "Bearer x"}


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


class TestBranchAccounting:
    def test_get_no_row_404(self, admin_client):
        r = admin_client.get("/branches/jupiter/accounting", headers=AUTH)
        assert r.status_code == 404

    def test_put_then_get_roundtrip(self, admin_client):
        body = {
            "qb_realm_id": "realm-123",
            "qb_company_name": "Perkins Jupiter LLC",
            "knowify_subscription_id": "sub-456",
        }
        r = admin_client.put("/branches/jupiter/accounting", json=body, headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json() == {"branch": "jupiter", "active": True, **body}

        r = admin_client.get("/branches/jupiter/accounting", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == {"branch": "jupiter", "active": True, **body}

    def test_put_upserts_existing_row(self, admin_client):
        admin_client.put("/branches/naples/accounting",
                          json={"qb_realm_id": "r1"}, headers=AUTH)
        r = admin_client.put("/branches/naples/accounting",
                              json={"qb_realm_id": "r2"}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["qb_realm_id"] == "r2"

    def test_put_unknown_branch_422(self, admin_client):
        r = admin_client.put("/branches/atlantis/accounting",
                              json={"qb_realm_id": "r1"}, headers=AUTH)
        assert r.status_code == 422

    def test_sales_cannot_put(self, sales_client):
        r = sales_client.put("/branches/miami/accounting",
                              json={"qb_realm_id": "r1"}, headers=AUTH)
        assert r.status_code == 403

    def test_sales_can_get(self, sales_client, admin_client):
        admin_client.put("/branches/gc/accounting", json={"qb_realm_id": "r1"}, headers=AUTH)
        r = sales_client.get("/branches/gc/accounting", headers=AUTH)
        assert r.status_code == 200
