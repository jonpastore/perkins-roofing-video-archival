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


class TestPricingConfigBranch:
    """#359: `branch` is a reference, not a free string — on every writer, not just customers.

    Migration 0055 enforces it in Postgres; these cover the API answer, which must be a 422
    naming the branch rather than the integrity error the FK would otherwise raise. SQLite
    does not enforce foreign keys, so without this the route is the only thing standing
    between a typo and a config version nothing will ever read.
    """

    _CONFIG = {"branch": "atlantis", "config": {"labor": {"rate": 1.0}}, "label": "t"}

    def test_create_config_unknown_branch_422(self, admin_client):
        r = admin_client.post("/estimator/configs", json=self._CONFIG, headers=AUTH)
        assert r.status_code == 422, r.text
        assert "atlantis" in r.text

    def test_create_config_valid_branch_accepted(self, admin_client):
        # A branch of its own, not a seeded one: `init_db` builds ONE SQLite DB for the whole
        # session and nothing truncates between tests, so writing a config under a shared
        # branch key collides with whichever other test claims (tenant, branch, version=1) —
        # tests/test_f2_models.py claims exactly that for 'jupiter'.
        admin_client.post("/branches", json={"key": "cfgok", "name": "CfgOk"}, headers=AUTH)
        r = admin_client.post("/estimator/configs",
                              json={**self._CONFIG, "branch": "cfgok"}, headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json()["branch"] == "cfgok"

    def test_create_config_inactive_branch_422(self, admin_client):
        bid = admin_client.post("/branches", json={"key": "cfgtemp", "name": "T"},
                                headers=AUTH).json()["id"]
        admin_client.put(f"/branches/{bid}", json={"active": False}, headers=AUTH)
        r = admin_client.post("/estimator/configs",
                              json={**self._CONFIG, "branch": "cfgtemp"}, headers=AUTH)
        assert r.status_code == 422, r.text


class TestCopyPricingConfigBetweenBranches:
    """#388 — the copy-config flow the Branches page performs.

    A branch with no pricing config cannot be quoted: the estimator returns 503 rather than
    guessing a price. Perkins Construction (`gc`) has been in the branch list since migration 0041
    and has never had one, so it has been unquotable since the day it was created.

    The UI composes three EXISTING endpoints — read active, create version, activate — because
    configs are immutable-versioned, so a copy is just a create. These pin that sequence, since
    the button has no backend of its own to test.
    """

    _CFG = {"labor": {"rate": 2.5}, "schema_version": 1}

    def _branch(self, client, key):
        client.post("/branches", json={"key": key, "name": key}, headers=AUTH)
        return key

    def test_target_branch_has_no_active_config_to_begin_with(self, admin_client):
        self._branch(admin_client, "copysrc")
        dst = self._branch(admin_client, "copydst")
        r = admin_client.get(f"/estimator/configs/active?branch={dst}", headers=AUTH)
        assert r.status_code == 404, "a branch with no config must not report one"

    def test_copy_makes_the_target_active_with_the_source_config(self, admin_client):
        src, dst = self._branch(admin_client, "cpsrc2"), self._branch(admin_client, "cpdst2")
        created = admin_client.post(
            "/estimator/configs", json={"branch": src, "label": "v1", "config": self._CFG},
            headers=AUTH).json()
        admin_client.post(f"/estimator/configs/{created['id']}/activate", headers=AUTH)

        # ── exactly what the button does ──
        active_src = admin_client.get(f"/estimator/configs/active?branch={src}", headers=AUTH).json()
        copied = admin_client.post("/estimator/configs", headers=AUTH, json={
            "branch": dst, "label": f"copied from {src} v{active_src['version']}",
            "config": active_src["config"]}).json()
        act = admin_client.post(f"/estimator/configs/{copied['id']}/activate", headers=AUTH)
        assert act.status_code == 200, act.text

        got = admin_client.get(f"/estimator/configs/active?branch={dst}", headers=AUTH).json()
        assert got["config"] == self._CFG
        assert got["branch"] == dst

    def test_copy_leaves_the_source_untouched(self, admin_client):
        """The source branch must keep its own active version — a copy is not a move."""
        src, dst = self._branch(admin_client, "cpsrc3"), self._branch(admin_client, "cpdst3")
        created = admin_client.post(
            "/estimator/configs", json={"branch": src, "config": self._CFG}, headers=AUTH).json()
        admin_client.post(f"/estimator/configs/{created['id']}/activate", headers=AUTH)
        before = admin_client.get(f"/estimator/configs/active?branch={src}", headers=AUTH).json()

        copied = admin_client.post("/estimator/configs", headers=AUTH,
                                   json={"branch": dst, "config": before["config"]}).json()
        admin_client.post(f"/estimator/configs/{copied['id']}/activate", headers=AUTH)

        after = admin_client.get(f"/estimator/configs/active?branch={src}", headers=AUTH).json()
        assert after["id"] == before["id"], "copying must not move the source's active pointer"

    def test_copy_to_an_unknown_branch_is_refused(self, admin_client):
        """The 422 from #417's create_config guard is what stops a typo'd target creating a config
        no selector can ever reach."""
        r = admin_client.post("/estimator/configs",
                              json={"branch": "atlantis", "config": self._CFG}, headers=AUTH)
        assert r.status_code == 422
