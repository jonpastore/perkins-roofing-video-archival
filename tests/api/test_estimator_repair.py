"""Behavioral tests — POST /estimator/repair-quote (time-based repair pricing, Zoom 2026-07-20)
and a regression lock-in for the "missing shingle/tile/metal selection" bug report ([36:12]):
GET /estimator/rates must list all config-priced sloped roof types, and each must be
independently quotable via POST /estimator/quote.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db
from tests.api.test_estimator_f2 import AUTH, SAMPLE_CONFIG, _activate_config, _create_config

REPAIR_CONFIG = {
    **SAMPLE_CONFIG,
    "repair": {
        "roof_types": ["shingle", "tile", "metal", "flat"],
        "daily_labor_rate": {"one_man": 1185.00, "two_man": 1435.00},
    },
}


def _unique_branch(prefix: str = "repair") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                             "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


class TestRepairQuote:
    def test_repair_quote_computes_labor_plus_material(self, admin_client):
        branch = _unique_branch()
        created = _create_config(admin_client, branch=branch, config=REPAIR_CONFIG)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/repair-quote",
            json={"branch": branch, "roof_type": "shingle", "days": 2, "crew_size": 1,
                  "material_cost": 150},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["daily_labor_rate"] == 1185.00
        assert body["labor_cost"] == pytest.approx(2370.00)
        assert body["material_cost"] == 150.0
        assert body["project_total"] == pytest.approx(2520.00)
        assert body["pricing_config_id"] == created["id"]

    def test_repair_quote_two_man_crew(self, admin_client):
        branch = _unique_branch()
        created = _create_config(admin_client, branch=branch, config=REPAIR_CONFIG)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/repair-quote",
            json={"branch": branch, "roof_type": "tile", "days": 1, "crew_size": 2},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["daily_labor_rate"] == 1435.00

    def test_repair_quote_unknown_roof_type_422(self, admin_client):
        branch = _unique_branch()
        created = _create_config(admin_client, branch=branch, config=REPAIR_CONFIG)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/repair-quote",
            json={"branch": branch, "roof_type": "gutter", "days": 1},
            headers=AUTH,
        )
        assert r.status_code == 422

    def test_repair_quote_no_active_config_503(self, admin_client):
        branch = _unique_branch("repair-no-cfg")
        r = admin_client.post(
            "/estimator/repair-quote",
            json={"branch": branch, "roof_type": "shingle", "days": 1},
            headers=AUTH,
        )
        assert r.status_code == 503

    def test_repair_quote_missing_repair_config_422(self, admin_client):
        """A config with no `repair` block (e.g. pre-existing prod configs) fails clean, not 500."""
        branch = _unique_branch()
        created = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/repair-quote",
            json={"branch": branch, "roof_type": "shingle", "days": 1},
            headers=AUTH,
        )
        assert r.status_code == 422


class TestRoofTypeSelectionRegression:
    """Regression lock-in for the 07-20 Zoom report [36:12]: 'Fix missing shingle/tile/metal
    selection options in the estimate.' Not reproducible against current code (verified by
    inspection: the roof_type <select> in web/src/pages/Quoting.tsx is driven entirely by
    GET /estimator/rates roof_types, and the seeded fixture has carried all 5 sloped types
    since its first commit). This test locks the contract in so it can't silently regress.
    """

    def test_rates_lists_all_sloped_roof_types(self, admin_client):
        branch = _unique_branch("rates-roof-types")
        created = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        _activate_config(admin_client, created["id"])

        r = admin_client.get(f"/estimator/rates?branch={branch}&region=HVHZ", headers=AUTH)
        assert r.status_code == 200
        roof_types = r.json()["roof_types"]
        for expected in ("13_tile", "barrel_tile", "3tab_shingle", "dimensional_shingle",
                          "standing_seam_metal"):
            assert expected in roof_types, f"{expected!r} missing from /estimator/rates roof_types"

    @pytest.mark.parametrize("roof_type", [
        "13_tile", "barrel_tile", "3tab_shingle", "dimensional_shingle", "standing_seam_metal",
    ])
    def test_each_sloped_roof_type_is_independently_quotable(self, admin_client, roof_type):
        branch = _unique_branch("quote-roof-type")
        created = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": roof_type, "num_squares": 20.0},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        assert r.json()["roof_type"] == roof_type
