"""Branch management API + customer branch association (Zoom 2026-07-17)."""
import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db

_MOUNTED = set(getattr(r, "prefix", None) for r in appmod.app.routes)
if "/quoting/customers" not in _MOUNTED:
    from api.routes.customers import router as customers_router
    appmod.app.include_router(customers_router)

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


class TestBranchesCrud:
    def test_seeded_branches_listed_in_sort_order(self, admin_client):
        r = admin_client.get("/branches", headers=AUTH)
        assert r.status_code == 200, r.text
        keys = [b["key"] for b in r.json()]
        assert keys[:4] == ["miami", "jupiter", "naples", "gc"]

    def test_sales_can_read_branches(self, sales_client):
        assert sales_client.get("/branches", headers=AUTH).status_code == 200

    def test_sales_cannot_create_branch(self, sales_client):
        r = sales_client.post("/branches", json={"key": "x", "name": "X"}, headers=AUTH)
        assert r.status_code == 403

    def test_create_rename_deactivate_roundtrip(self, admin_client):
        r = admin_client.post("/branches", json={"key": "keywest", "name": "Key West", "sort": 9}, headers=AUTH)
        assert r.status_code == 201, r.text
        bid = r.json()["id"]
        r = admin_client.put(f"/branches/{bid}", json={"name": "Key West FL", "active": False}, headers=AUTH)
        assert r.status_code == 200 and r.json()["active"] is False
        active_keys = [b["key"] for b in admin_client.get("/branches", headers=AUTH).json()]
        assert "keywest" not in active_keys
        all_keys = [b["key"] for b in admin_client.get("/branches?include_inactive=true", headers=AUTH).json()]
        assert "keywest" in all_keys

    def test_duplicate_key_409(self, admin_client):
        r = admin_client.post("/branches", json={"key": "miami", "name": "Miami 2"}, headers=AUTH)
        assert r.status_code == 409

    def test_bad_key_format_422(self, admin_client):
        r = admin_client.post("/branches", json={"key": "Key West!", "name": "KW"}, headers=AUTH)
        assert r.status_code == 422

    def test_update_missing_branch_404(self, admin_client):
        assert admin_client.put("/branches/99999", json={"name": "x"}, headers=AUTH).status_code == 404


class TestCustomerBranch:
    def test_customer_defaults_to_miami(self, admin_client):
        r = admin_client.post("/quoting/customers", json={"display_name": "BranchDefault Co"}, headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json()["branch"] == "miami"

    def test_customer_created_in_valid_branch(self, admin_client):
        r = admin_client.post("/quoting/customers",
                              json={"display_name": "Jup Co", "branch": "jupiter"}, headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json()["branch"] == "jupiter"

    def test_customer_unknown_branch_422(self, admin_client):
        r = admin_client.post("/quoting/customers",
                              json={"display_name": "Bad Co", "branch": "atlantis"}, headers=AUTH)
        assert r.status_code == 422

    def test_customer_inactive_branch_422(self, admin_client):
        bid = admin_client.post("/branches", json={"key": "temp", "name": "Temp"}, headers=AUTH).json()["id"]
        admin_client.put(f"/branches/{bid}", json={"active": False}, headers=AUTH)
        r = admin_client.post("/quoting/customers",
                              json={"display_name": "T Co", "branch": "temp"}, headers=AUTH)
        assert r.status_code == 422

    def test_customer_branch_update(self, admin_client):
        cid = admin_client.post("/quoting/customers",
                                json={"display_name": "Mover Co"}, headers=AUTH).json()["id"]
        r = admin_client.put(f"/quoting/customers/{cid}", json={"branch": "naples"}, headers=AUTH)
        assert r.status_code == 200 and r.json()["branch"] == "naples"
