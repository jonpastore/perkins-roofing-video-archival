"""F2 API behavioral tests — pricing config CRUD + estimator hash stamping + measurements.

Tests the full HTTP surface:
  - GET/POST /estimator/configs (list, create, get, diff, active, activate)
  - POST /estimator/quote (hash stamping, authz)
  - POST/GET /measurements (manual entry, provenance)

Uses the fake-verifier pattern from existing tests (no live Firebase needed).
All tests run against the SQLite test engine via init_db().

DB isolation: each test that needs a clean slate for version numbers uses
a unique branch name (branch=<test-scoped-uuid-prefix>) to avoid cross-test
version counter pollution — init_db() creates the schema once and tests share
the same SQLite file across the suite.
"""
import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from api.routes.pricing_configs import router as pricing_configs_router
from api.routes.measurements import router as measurements_router
from app.models import PricingConfig, SessionLocal, init_db

# Mount new routers once if not already present (idempotent guard)
_MOUNTED = set(getattr(r, "prefix", None) for r in appmod.app.routes)
if "/estimator/configs" not in _MOUNTED:
    appmod.app.include_router(pricing_configs_router)
if "/measurements" not in _MOUNTED:
    appmod.app.include_router(measurements_router)


SAMPLE_CONFIG = {
    "schema_version": 1,
    "exhibit_version": "B-2026-07",
    "boundary_inclusive_lower": True,
    "boundary_exclusive_upper": True,
    "zones": ["HVHZ", "FBC"],
    "counties": {
        "miami_dade": "HVHZ", "broward": "HVHZ",
        "palm_beach": "FBC", "lee": "FBC", "st_lucie": "FBC",
    },
    "county_overrides": {
        "miami_dade": {"permit_fee_add": 0, "materials_tax_7pct_tile": False, "extra_line_items": {}},
        "broward":    {"permit_fee_add": 0, "materials_tax_7pct_tile": False, "extra_line_items": {}},
        "palm_beach": {"permit_fee_add": 0, "materials_tax_7pct_tile": False, "extra_line_items": {}},
        "lee":        {"permit_fee_add": 0, "materials_tax_7pct_tile": False, "extra_line_items": {}},
        "st_lucie":   {"permit_fee_add": 0, "materials_tax_7pct_tile": False, "extra_line_items": {}},
    },
    "sloped_base_cost_lm": {
        "HVHZ": {"13_tile": 780, "barrel_tile": 1455, "3tab_shingle": 395,
                 "dimensional_shingle": 420, "standing_seam_metal": 1020},
        "FBC":  {"13_tile": 770, "barrel_tile": 1435, "3tab_shingle": 395,
                 "dimensional_shingle": 420, "standing_seam_metal": 750},
    },
    "sloped_overhead": {
        "HVHZ": {"3tab_shingle": 125, "dimensional_shingle": 125, "13_tile": 270,
                 "barrel_tile": 420, "standing_seam_metal": 280},
        "FBC":  {"3tab_shingle": 105, "dimensional_shingle": 105, "13_tile": 185,
                 "barrel_tile": 350, "standing_seam_metal": 205},
    },
    "profit_scale": [[1, 400], [4, 200], [7, 160], [14, 140], [20, 120], [29, 110], [None, 100]],
    "cost_category_tags": {
        "base_cost_lm": "Materials", "overhead": "OH", "profit": "Profit",
        "roof_cuts": "Labor", "roof_height": "Labor", "tile_pointing": "Labor",
        "specialty_tile": "Materials", "pitch_7_12_add": "Labor", "tile_demo": "Labor",
        "metal_demo": "Labor", "secondary_water_barrier": "Materials", "winterguard": "Materials",
        "stucco_metal": "Labor", "penetrations": "Labor", "ridge_vents": "Materials",
        "delivery_plywood_vents": "Materials", "new_bonus_values": "Misc",
        "permit_processing": "Misc", "tile_dumpster": "Equipment", "pm_incentive": "Misc",
        "insulation": "Materials", "tapered": "Materials",
    },
    "profit_floor_pct": 0.13,
    "profit_plus_oh_floor_pct": 0.33,
    "floor_excluded_categories": {"insulation": ["Profit"], "tapered": ["OH", "Profit"]},
    "commission_pct": {"sloped": 0.10, "low_slope": 0.15, "sloped_hvhz": None},
    "pm_incentive": {
        "HVHZ": {"residential_lt20": 150, "commercial_20_50": 300, "commercial_gt50": 300},
        "FBC":  {"residential_lt20": 50,  "commercial_20_50": 100, "commercial_gt50": 250},
    },
    "roof_height": {"1_story": 0, "2_stories": 50, "3_5_stories": None, "6_plus": None},
    "roof_height_3_5_flat_add": 1200,
    "roof_cuts": {"low": 0, "medium": 25, "high": 50},
    "tile_pointing": {"no": 0, "yes": 200},
    "specialty_tile_upgrade": {"HVHZ": {"santa_fe_clay_s": 160}, "FBC": {"santa_fe_clay_s": 160}},
    "pitch_7_12_add": 200,
    "tile_demo_add": 40,
    "metal_demo_add": 60,
    "secondary_water_barrier_add": 75,
    "winterguard_add": 140,
    "stucco_metal_per_lf": 9,
    "penetration_each": 75,
    "ridge_vent_per_lf": 9.79,
    "delivery_plywood_vents": 650,
    "new_bonus_values": 1350,
    "permit_processing": 500,
    "permit_commercial_add": 500,
    "tile_dumpster_cost": 300,
    "tile_dumpster_threshold": {"HVHZ": 15, "FBC": 30},
    "tile_dumpster_boundary_inclusive": True,
    "line_items": {
        "HVHZ": {"blown_in_iso_r19": 135, "turbine_vents": 257.50, "solar_vents": 1339.00},
        "FBC":  {"blown_in_iso_r19": 135, "turbine_vents": 257.50, "solar_vents": 1489.00},
    },
    "low_slope": {
        "base_cost_lm": {"HVHZ": {"tpo": None, "coatings": None, "silicone": None, "bur": None},
                         "FBC":  {"tpo": None, "coatings": None, "silicone": None, "bur": None}},
        "overhead": {"HVHZ": {"flat_oh": None, "tpo_oh": None, "coatings_oh": None},
                     "FBC":  {"flat_oh": None, "tpo_oh": None, "coatings_oh": None}},
        "insulation_tiers": [],
        "tapered_cost_per_sq": None,
        "deck_types": {"existing_concrete": 0, "plywood_replace": None},
        "tear_off_per_layer_per_sq": None,
        "crane_threshold_stories": 3,
        "trash_chute_flat_add": 1200,
    },
}


def _hash(cfg: dict) -> str:
    import jcs
    return hashlib.sha256(jcs.canonicalize(cfg)).hexdigest()


def _unique_branch(prefix: str = "test") -> str:
    """Return a branch name unique per test call to avoid version counter pollution."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


AUTH = {"Authorization": "Bearer x"}


def _make_admin_client():
    """Create a fresh admin TestClient, setting the verifier at call time."""
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                             "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


def _make_sales_client():
    """Create a fresh sales TestClient, setting the verifier at call time."""
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                             "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# Helper: seed a config version via the API
# ---------------------------------------------------------------------------

def _create_config(client, branch="miami", label="Test", config=None):
    cfg = config or SAMPLE_CONFIG
    r = client.post("/estimator/configs", json={"branch": branch, "label": label, "config": cfg},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def _activate_config(client, config_id):
    r = client.post(f"/estimator/configs/{config_id}/activate", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Config list endpoint
# ---------------------------------------------------------------------------

class TestListConfigs:
    def test_list_empty_branch(self, admin_client):
        branch = _unique_branch("list-empty")
        r = admin_client.get(f"/estimator/configs?branch={branch}", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == []

    def test_list_returns_created_versions(self, admin_client):
        branch = _unique_branch("list-ver")
        _create_config(admin_client, branch=branch, label="v1")
        _create_config(admin_client, branch=branch, label="v2")
        r = admin_client.get(f"/estimator/configs?branch={branch}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        versions = sorted(d["version"] for d in data)
        assert versions == [1, 2]

    def test_list_requires_auth(self):
        client = TestClient(appmod.app)
        r = client.get("/estimator/configs")
        assert r.status_code == 401

    def test_list_sales_allowed(self, sales_client):
        """sales role has estimating_view so can list configs."""
        r = sales_client.get("/estimator/configs", headers=AUTH)
        assert r.status_code == 200

    def test_list_no_branch_returns_all_branches(self, admin_client):
        b1 = _unique_branch("all-b1")
        b2 = _unique_branch("all-b2")
        _create_config(admin_client, branch=b1)
        _create_config(admin_client, branch=b2)
        r = admin_client.get("/estimator/configs", headers=AUTH)
        assert r.status_code == 200
        branches = {d["branch"] for d in r.json()}
        assert b1 in branches
        assert b2 in branches


# ---------------------------------------------------------------------------
# Config create endpoint
# ---------------------------------------------------------------------------

class TestCreateConfig:
    def test_create_returns_version_and_hash(self, admin_client):
        branch = _unique_branch("create-hash")
        r = admin_client.post(
            "/estimator/configs",
            json={"branch": branch, "label": "Exhibit B", "config": SAMPLE_CONFIG},
            headers=AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == 1
        assert body["branch"] == branch
        assert len(body["config_hash"]) == 64
        assert body["is_active"] is False
        assert body["created_by"] == "admin@perkins.com"

    def test_create_hash_matches_rfc8785(self, admin_client):
        branch = _unique_branch("create-rfc")
        r = admin_client.post(
            "/estimator/configs",
            json={"branch": branch, "config": SAMPLE_CONFIG},
            headers=AUTH,
        )
        body = r.json()
        expected_hash = _hash(SAMPLE_CONFIG)
        assert body["config_hash"] == expected_hash

    def test_create_version_increments(self, admin_client):
        branch = _unique_branch("incr")
        r1 = _create_config(admin_client, branch=branch)
        r2 = _create_config(admin_client, branch=branch)
        assert r1["version"] == 1
        assert r2["version"] == 2

    def test_create_sales_forbidden(self, sales_client):
        """sales has estimating_view but not estimating_manage."""
        r = sales_client.post(
            "/estimator/configs",
            json={"branch": "miami", "config": SAMPLE_CONFIG},
            headers=AUTH,
        )
        assert r.status_code == 403

    def test_create_returns_config_body(self, admin_client):
        branch = _unique_branch("cfg-body")
        r = admin_client.post(
            "/estimator/configs",
            json={"branch": branch, "config": SAMPLE_CONFIG},
            headers=AUTH,
        )
        body = r.json()
        assert "config" in body
        assert body["config"]["schema_version"] == 1

    def test_create_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.post("/estimator/configs", json={"branch": "miami", "config": {}})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Config get endpoint
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_get_returns_config_and_hash(self, admin_client):
        branch = _unique_branch("get-cfg")
        created = _create_config(admin_client, branch=branch)
        r = admin_client.get(f"/estimator/configs/{created['id']}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["config_hash"] == created["config_hash"]
        assert "config" in body

    def test_get_404_unknown_id(self, admin_client):
        r = admin_client.get("/estimator/configs/999999", headers=AUTH)
        assert r.status_code == 404

    def test_get_sales_can_read(self):
        ac = _make_admin_client()
        branch = _unique_branch("get-sales")
        created = _create_config(ac, branch=branch)

        sc = _make_sales_client()
        r = sc.get(f"/estimator/configs/{created['id']}", headers=AUTH)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Config activate endpoint
# ---------------------------------------------------------------------------

class TestActivateConfig:
    def test_activate_sets_is_active(self, admin_client):
        branch = _unique_branch("act-set")
        created = _create_config(admin_client, branch=branch)
        assert created["is_active"] is False
        r = _activate_config(admin_client, created["id"])
        assert r["is_active"] is True

    def test_activate_idempotent(self, admin_client):
        """Activating an already-active config twice returns 200 both times."""
        branch = _unique_branch("act-idem")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])
        r2 = admin_client.post(f"/estimator/configs/{created['id']}/activate", headers=AUTH)
        assert r2.status_code == 200
        assert r2.json()["is_active"] is True

    def test_activate_deactivates_prior(self, admin_client):
        """Activating v2 sets v1 is_active=False."""
        branch = _unique_branch("act-swap")
        v1 = _create_config(admin_client, branch=branch, label="v1")
        v2 = _create_config(admin_client, branch=branch, label="v2")
        _activate_config(admin_client, v1["id"])
        _activate_config(admin_client, v2["id"])

        r1 = admin_client.get(f"/estimator/configs/{v1['id']}", headers=AUTH)
        r2 = admin_client.get(f"/estimator/configs/{v2['id']}", headers=AUTH)
        assert r1.json()["is_active"] is False
        assert r2.json()["is_active"] is True

    def test_activate_404_unknown(self, admin_client):
        r = admin_client.post("/estimator/configs/999999/activate", headers=AUTH)
        assert r.status_code == 404

    def test_activate_sales_forbidden(self):
        """sales has estimating_view but not estimating_manage.
        Use call-time client construction to avoid fixture verifier ordering race."""
        ac = _make_admin_client()
        branch = _unique_branch("act-sales-403")
        created = _create_config(ac, branch=branch)

        sc = _make_sales_client()
        r = sc.post(f"/estimator/configs/{created['id']}/activate", headers=AUTH)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Active config endpoint
# ---------------------------------------------------------------------------

class TestActiveConfig:
    def test_active_404_when_none(self, admin_client):
        branch = _unique_branch("active-none")
        r = admin_client.get(f"/estimator/configs/active?branch={branch}", headers=AUTH)
        assert r.status_code == 404

    def test_active_returns_active_version(self, admin_client):
        branch = _unique_branch("active-ret")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])
        r = admin_client.get(f"/estimator/configs/active?branch={branch}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == created["id"]
        assert body["is_active"] is True
        assert "config" in body

    def test_active_updates_after_swap(self, admin_client):
        branch = _unique_branch("active-swap")
        v1 = _create_config(admin_client, branch=branch, label="v1")
        v2 = _create_config(admin_client, branch=branch, label="v2")
        _activate_config(admin_client, v1["id"])
        _activate_config(admin_client, v2["id"])
        r = admin_client.get(f"/estimator/configs/active?branch={branch}", headers=AUTH)
        assert r.json()["id"] == v2["id"]


# ---------------------------------------------------------------------------
# Diff endpoint
# ---------------------------------------------------------------------------

class TestDiffConfigs:
    def test_diff_returns_changes_as_array(self, admin_client):
        """changes is a list of {path, from_value, to_value} entries sorted by path."""
        branch = _unique_branch("diff-chg")
        cfg2 = {**SAMPLE_CONFIG, "schema_version": 2}
        v1 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        v2 = _create_config(admin_client, branch=branch, config=cfg2)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["changes"], list)
        assert body["changed_count"] == 1
        entry = body["changes"][0]
        assert entry["path"] == "schema_version"
        assert entry["from_value"] == 1
        assert entry["to_value"] == 2

    def test_diff_dot_path_for_nested_field(self, admin_client):
        """A change deep in a nested dict produces a dot-path entry."""
        branch = _unique_branch("diff-nested")
        cfg2 = {
            **SAMPLE_CONFIG,
            "sloped_base_cost_lm": {
                **SAMPLE_CONFIG["sloped_base_cost_lm"],
                "HVHZ": {**SAMPLE_CONFIG["sloped_base_cost_lm"]["HVHZ"], "13_tile": 999},
            },
        }
        v1 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        v2 = _create_config(admin_client, branch=branch, config=cfg2)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        paths = {e["path"] for e in body["changes"]}
        assert "sloped_base_cost_lm.HVHZ.13_tile" in paths
        entry = next(e for e in body["changes"] if e["path"] == "sloped_base_cost_lm.HVHZ.13_tile")
        assert entry["from_value"] == 780
        assert entry["to_value"] == 999

    def test_diff_added_key_has_null_from(self, admin_client):
        """A key present only in the 'to' config has from_value=null."""
        branch = _unique_branch("diff-add")
        cfg2 = {**SAMPLE_CONFIG, "new_field": "hello"}
        v1 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        v2 = _create_config(admin_client, branch=branch, config=cfg2)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        entry = next((e for e in r.json()["changes"] if e["path"] == "new_field"), None)
        assert entry is not None
        assert entry["from_value"] is None
        assert entry["to_value"] == "hello"

    def test_diff_removed_key_has_null_to(self, admin_client):
        """A key present only in the 'from' config has to_value=null."""
        branch = _unique_branch("diff-rm")
        cfg1 = {**SAMPLE_CONFIG, "old_field": "bye"}
        v1 = _create_config(admin_client, branch=branch, config=cfg1)
        v2 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        entry = next((e for e in r.json()["changes"] if e["path"] == "old_field"), None)
        assert entry is not None
        assert entry["from_value"] == "bye"
        assert entry["to_value"] is None

    def test_diff_sorted_by_path(self, admin_client):
        """changes list is sorted alphabetically by dot-path."""
        branch = _unique_branch("diff-sort")
        cfg2 = {**SAMPLE_CONFIG, "schema_version": 2, "exhibit_version": "B-v2"}
        v1 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        v2 = _create_config(admin_client, branch=branch, config=cfg2)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        paths = [e["path"] for e in r.json()["changes"]]
        assert paths == sorted(paths)

    def test_diff_no_changes(self, admin_client):
        branch = _unique_branch("diff-none")
        v1 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        v2 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["changed_count"] == 0
        assert body["changes"] == []

    def test_diff_response_has_hashes(self, admin_client):
        """Response includes from_hash and to_hash for UI display."""
        branch = _unique_branch("diff-hashes")
        cfg2 = {**SAMPLE_CONFIG, "schema_version": 2}
        v1 = _create_config(admin_client, branch=branch, config=SAMPLE_CONFIG)
        v2 = _create_config(admin_client, branch=branch, config=cfg2)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id={v2['id']}", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["from_hash"] == v1["config_hash"]
        assert body["to_hash"] == v2["config_hash"]

    def test_diff_404_unknown_from(self, admin_client):
        branch = _unique_branch("diff-404f")
        v1 = _create_config(admin_client, branch=branch)
        r = admin_client.get(f"/estimator/configs/diff?from_id=999999&to_id={v1['id']}", headers=AUTH)
        assert r.status_code == 404

    def test_diff_404_unknown_to(self, admin_client):
        branch = _unique_branch("diff-404t")
        v1 = _create_config(admin_client, branch=branch)
        r = admin_client.get(f"/estimator/configs/diff?from_id={v1['id']}&to_id=999999", headers=AUTH)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /estimator/quote — hash stamping
# ---------------------------------------------------------------------------

class TestEstimatorQuote:
    def test_api_quote_returns_hash_when_config_active(self, admin_client):
        """POST /estimator/quote stamps pricing_config_hash when a config is active."""
        branch = _unique_branch("quote-hash")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "HVHZ",
                "roof_type": "13_tile",
                "num_squares": 10.0,
            },
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "pricing_config_hash" in body
        assert body["pricing_config_hash"] == created["config_hash"]
        assert body["pricing_config_id"] == created["id"]

    def test_api_quote_no_active_config_returns_503(self, admin_client):
        """When no config is active for that branch, /quote returns HTTP 503 (Fix 3)."""
        branch = _unique_branch("quote-nohash")
        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": 5.0},
            headers=AUTH,
        )
        assert r.status_code == 503, r.text
        assert "no active pricing config" in r.json()["detail"].lower()

    def test_api_quote_unknown_specialty_tile_400(self, admin_client):
        branch = _unique_branch("quote-stile")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])
        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile",
                  "num_squares": 10.0, "specialty_tile": "not_a_real_tile"},
            headers=AUTH,
        )
        assert r.status_code == 400

    def test_api_quote_stamped_branch_and_zone(self, admin_client):
        branch = _unique_branch("quote-zone")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])
        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "FBC", "roof_type": "3tab_shingle",
                  "num_squares": 8.0},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["branch"] == branch
        assert body["code_zone"] == "FBC"

    def test_api_quote_estimating_view_sufficient(self):
        """sales role has estimating_view — can call /estimator/quote (needs active config)."""
        ac = _make_admin_client()
        branch = _unique_branch("quote-sales")
        created = _create_config(ac, branch=branch)
        _activate_config(ac, created["id"])

        sc = _make_sales_client()
        r = sc.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": 5.0},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text

    def test_api_quote_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.post("/estimator/quote",
                        json={"branch": "miami", "code_zone": "HVHZ",
                              "roof_type": "13_tile", "num_squares": 5.0})
        assert r.status_code == 401

    def test_api_quote_pinned_config_id(self, admin_client):
        """Specifying config_id pins the estimate to that version, not the active one."""
        branch = _unique_branch("quote-pin")
        v1 = _create_config(admin_client, branch=branch, label="v1")
        v2 = _create_config(admin_client, branch=branch, label="v2")
        _activate_config(admin_client, v2["id"])

        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile",
                  "num_squares": 5.0, "config_id": v1["id"]},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pricing_config_id"] == v1["id"]
        assert body["pricing_config_hash"] == v1["config_hash"]

    def test_api_quote_invalid_config_id_404(self, admin_client):
        r = admin_client.post(
            "/estimator/quote",
            json={"branch": "miami", "code_zone": "HVHZ", "roof_type": "13_tile",
                  "num_squares": 5.0, "config_id": 999999},
            headers=AUTH,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST/GET /measurements
# ---------------------------------------------------------------------------

class TestMeasurements:
    def test_create_manual_measurement(self, admin_client):
        r = admin_client.post(
            "/measurements",
            json={"total_sq": 28.0, "hips_lf": 120.0, "pitch_primary": 4.0},
            headers=AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] is not None
        assert body["provider"] == "manual"
        assert body["status"] == "complete"
        assert body["confidence"] is None
        assert body["total_sq"] == 28.0

    def test_create_measurement_provenance_auto_set(self, admin_client):
        r = admin_client.post(
            "/measurements",
            json={"total_sq": 15.0},
            headers=AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        assert "admin@perkins.com" in body["provenance_note"]
        assert "Manual entry by" in body["provenance_note"]

    def test_create_measurement_custom_provenance(self, admin_client):
        r = admin_client.post(
            "/measurements",
            json={"total_sq": 10.0, "provenance_note": "Verified by Tim on site"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["provenance_note"] == "Verified by Tim on site"

    def test_get_measurement_by_id(self, admin_client):
        created = admin_client.post(
            "/measurements",
            json={"total_sq": 41.5, "pitch_primary": 5.0},
            headers=AUTH,
        ).json()
        r = admin_client.get(f"/measurements/{created['id']}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total_sq"] == 41.5

    def test_get_measurement_404(self, admin_client):
        r = admin_client.get("/measurements/999999", headers=AUTH)
        assert r.status_code == 404

    def test_create_measurement_sales_forbidden(self, sales_client):
        """sales has estimating_view but not estimating_manage."""
        r = sales_client.post(
            "/measurements",
            json={"total_sq": 10.0},
            headers=AUTH,
        )
        assert r.status_code == 403

    def test_get_measurement_sales_allowed(self):
        ac = _make_admin_client()
        created = ac.post(
            "/measurements",
            json={"total_sq": 5.0},
            headers=AUTH,
        ).json()

        sc = _make_sales_client()
        r = sc.get(f"/measurements/{created['id']}", headers=AUTH)
        assert r.status_code == 200

    def test_measurement_unauthenticated_401(self):
        client = TestClient(appmod.app)
        r = client.post("/measurements", json={"total_sq": 5.0})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /estimator/rates — config-driven
# ---------------------------------------------------------------------------

class TestRatesEndpoint:
    def test_rates_no_active_config_returns_response(self, admin_client):
        """Without an active config, rates returns a valid response (legacy or empty)."""
        branch = _unique_branch("rates-legacy")
        r = admin_client.get(f"/estimator/rates?branch={branch}&region=FBC", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["config_id"] is None
        assert body["config_hash"] is None

    def test_rates_with_active_config_returns_config_data(self, admin_client):
        branch = _unique_branch("rates-cfg")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])
        r = admin_client.get(f"/estimator/rates?branch={branch}&region=HVHZ", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["config_id"] == created["id"]
        assert body["config_hash"] == created["config_hash"]
        assert "13_tile" in body["roof_types"]

    def test_rates_sales_allowed(self, sales_client):
        r = sales_client.get("/estimator/rates", headers=AUTH)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Fix 1 (H1): Single hash function — stored hash must equal core.compute_hash
# ---------------------------------------------------------------------------

class TestHashConsistency:
    def test_create_hash_matches_core_compute_hash(self, admin_client):
        """POST /estimator/configs stores a hash equal to core.compute_hash(fixture).
        The API route's local _compute_hash skips the underscore-key strip, producing
        a different digest. This test is red until the route imports core.compute_hash."""
        import json
        from pathlib import Path
        from core.pricing_config import compute_hash

        fixture_path = Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
        fixture = json.loads(fixture_path.read_text())
        expected_hash = compute_hash(fixture)

        branch = _unique_branch("hash-consistency")
        r = admin_client.post(
            "/estimator/configs",
            json={"branch": branch, "config": fixture},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        stored_hash = r.json()["config_hash"]
        assert stored_hash == expected_hash, (
            f"Stored hash {stored_hash[:16]}... != core.compute_hash {expected_hash[:16]}...; "
            "API route must use core.pricing_config.compute_hash, not a local inline function"
        )


# ---------------------------------------------------------------------------
# Fix 3 (H3): No active config -> 503 (not legacy fallback)
# ---------------------------------------------------------------------------

class TestNoActiveConfig503:
    def test_quote_no_active_config_returns_503(self, admin_client):
        """Without an active config, POST /quote must return HTTP 503."""
        branch = _unique_branch("no-cfg-503")
        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": 5.0},
            headers=AUTH,
        )
        assert r.status_code == 503, f"Expected 503 got {r.status_code}: {r.text}"
        assert "no active pricing config" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Fix 5 (H5): Tenant scoping — active-config lookup must filter by tenant_id
# ---------------------------------------------------------------------------

class TestTenantScoping:
    def test_active_config_scoped_to_tenant(self, admin_client):
        """A config active for tenant 2 must not satisfy tenant-1 active lookup."""
        import uuid
        from app.models import PricingConfig as PCModel, SessionLocal
        from core.pricing_config import compute_hash

        branch = f"scope-{uuid.uuid4().hex[:8]}"
        cfg_t2 = {**SAMPLE_CONFIG, "exhibit_version": "tenant2-only"}
        h = compute_hash(cfg_t2)

        with SessionLocal() as db:
            row = PCModel(
                tenant_id=2, branch=branch, version=1,
                config=cfg_t2, config_hash=h, is_active=True,
                created_by="t2@perkins.com",
            )
            db.add(row)
            db.commit()

        # No tenant-1 config on that branch -> must get 503, not the tenant-2 config
        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": 5.0},
            headers=AUTH,
        )
        assert r.status_code == 503, (
            f"Expected 503 (no tenant-1 config), got {r.status_code} — tenant scoping broken"
        )

    def test_no_multiple_results_found_with_two_tenants(self, admin_client):
        """Two tenants with active configs on the same branch must not raise MultipleResultsFound."""
        import uuid
        from app.models import PricingConfig as PCModel, SessionLocal
        from core.pricing_config import compute_hash

        branch = f"multi-{uuid.uuid4().hex[:8]}"
        h = compute_hash(SAMPLE_CONFIG)

        with SessionLocal() as db:
            row = PCModel(
                tenant_id=2, branch=branch, version=1,
                config=SAMPLE_CONFIG, config_hash=h, is_active=True,
                created_by="t2@perkins.com",
            )
            db.add(row)
            db.commit()

        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/quote",
            json={"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": 5.0},
            headers=AUTH,
        )
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        assert r.json()["pricing_config_id"] == created["id"]


# ---------------------------------------------------------------------------
# Fix 7 (M2): Dumpster boundary flag — inclusive=ceil, exclusive=floor
#
# inclusive=True  (default): ceil(sq / threshold)  — sq=16, threshold=15 -> 2
# inclusive=False (exclusive): floor(sq / threshold) — sq=16, threshold=15 -> 1
# ---------------------------------------------------------------------------

class TestDumpsterBoundaryFlag:
    def test_dumpster_boundary_flag_changes_count(self):
        """Flag flip at sq=16, HVHZ threshold=15: ceil=2 (inclusive), floor=1 (exclusive)."""
        import json
        from pathlib import Path
        from core.pricing_config import load_config

        raw = json.loads(
            (Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json")
            .read_text()
        )
        cfg_inc = load_config({**raw, "tile_dumpster_boundary_inclusive": True})
        cfg_exc = load_config({**raw, "tile_dumpster_boundary_inclusive": False})

        # sq=16 at HVHZ threshold=15: inclusive->ceil(16/15)=2, exclusive->floor(16/15)=1
        assert cfg_inc.tile_dumpster_count(16.0, "HVHZ") == 2
        assert cfg_exc.tile_dumpster_count(16.0, "HVHZ") == 1

    def test_dumpster_boundary_cases_inclusive(self):
        """15/16/30/31 sq at HVHZ threshold=15, inclusive=ceil."""
        import json
        from pathlib import Path
        from core.pricing_config import load_config

        raw = json.loads(
            (Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json")
            .read_text()
        )
        cfg = load_config({**raw, "tile_dumpster_boundary_inclusive": True})
        assert cfg.tile_dumpster_count(15.0, "HVHZ") == 1   # ceil(15/15)=1
        assert cfg.tile_dumpster_count(16.0, "HVHZ") == 2   # ceil(16/15)=2
        assert cfg.tile_dumpster_count(30.0, "HVHZ") == 2   # ceil(30/15)=2
        assert cfg.tile_dumpster_count(31.0, "HVHZ") == 3   # ceil(31/15)=3

    def test_dumpster_boundary_cases_exclusive(self):
        """15/16/30/31 sq at HVHZ threshold=15, exclusive=floor."""
        import json
        from pathlib import Path
        from core.pricing_config import load_config

        raw = json.loads(
            (Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json")
            .read_text()
        )
        cfg = load_config({**raw, "tile_dumpster_boundary_inclusive": False})
        assert cfg.tile_dumpster_count(15.0, "HVHZ") == 1   # floor(15/15)=1
        assert cfg.tile_dumpster_count(16.0, "HVHZ") == 1   # floor(16/15)=1
        assert cfg.tile_dumpster_count(30.0, "HVHZ") == 2   # floor(30/15)=2
        assert cfg.tile_dumpster_count(31.0, "HVHZ") == 2   # floor(31/15)=2


# ---------------------------------------------------------------------------
# Fix 8 (M1): Estimate persistence — /quote persists Estimate row
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# R2 HIGH-3: API trust boundary validation for v2 fields
# ---------------------------------------------------------------------------

# Minimal config with daily_overhead_rates so the engine can run v2 paths
SAMPLE_CONFIG_V2 = {
    **SAMPLE_CONFIG,
    "daily_overhead_rates": {
        "demo_dry_in_flat": 1050,
        "tile": 745,
        "metal": 850,
        "shingle": 700,
    },
    "daily_overhead_weeks_rounding_mode": "ceil",
    "profit_mode_default": "scale",
    "weekly_profit_floor": 2500,
    "job_profit_floor": 2500,
}


class TestV2APIValidation:
    """HIGH-3: DailySeriesItem must validate days and series name at the API boundary (→422)."""

    def _branch_with_v2_config(self, client) -> str:
        branch = _unique_branch("v2-api")
        created = _create_config(client, branch=branch, config=SAMPLE_CONFIG_V2)
        _activate_config(client, created["id"])
        return branch

    def test_daily_series_non_half_increment_returns_422(self, admin_client):
        """days=1.3 is not a 0.5 multiple — must return 422, not 500."""
        branch = self._branch_with_v2_config(admin_client)
        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "FBC",
                "roof_type": "3tab_shingle",
                "num_squares": 10.0,
                "project_kind": "residential",
                "overhead_mode": "daily",
                "daily_series": [{"series": "shingle", "days": 1.3}],
            },
            headers=AUTH,
        )
        assert r.status_code == 422, f"Expected 422 for days=1.3, got {r.status_code}: {r.text}"

    def test_daily_series_unknown_series_returns_422(self, admin_client):
        """Unknown series name must return 422, not 500."""
        branch = self._branch_with_v2_config(admin_client)
        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "FBC",
                "roof_type": "3tab_shingle",
                "num_squares": 10.0,
                "project_kind": "residential",
                "overhead_mode": "daily",
                "daily_series": [{"series": "mystery_series", "days": 1.0}],
            },
            headers=AUTH,
        )
        assert r.status_code == 422, f"Expected 422 for unknown series, got {r.status_code}: {r.text}"

    def test_flat_profit_negative_returns_422(self, admin_client):
        """flat_profit_dollars < 0 must return 422 (MEDIUM-1: ge=0 constraint)."""
        branch = self._branch_with_v2_config(admin_client)
        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "FBC",
                "roof_type": "3tab_shingle",
                "num_squares": 10.0,
                "project_kind": "residential",
                "profit_mode": "flat",
                "flat_profit_dollars": -500.0,
            },
            headers=AUTH,
        )
        assert r.status_code == 422, f"Expected 422 for negative flat_profit, got {r.status_code}: {r.text}"

    def test_daily_series_zero_days_returns_422(self, admin_client):
        """days=0 must return 422 (gt=0 field constraint)."""
        branch = self._branch_with_v2_config(admin_client)
        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "FBC",
                "roof_type": "3tab_shingle",
                "num_squares": 10.0,
                "project_kind": "residential",
                "overhead_mode": "daily",
                "daily_series": [{"series": "shingle", "days": 0}],
            },
            headers=AUTH,
        )
        assert r.status_code == 422, f"Expected 422 for days=0, got {r.status_code}: {r.text}"

    def test_v2_daily_oh_valid_request_succeeds(self, admin_client):
        """Valid daily OH request with known series and 0.5-increment days returns 200."""
        branch = self._branch_with_v2_config(admin_client)
        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "FBC",
                "roof_type": "3tab_shingle",
                "num_squares": 10.0,
                "project_kind": "residential",
                "overhead_mode": "daily",
                "daily_series": [
                    {"series": "demo_dry_in_flat", "days": 1.0},
                    {"series": "shingle", "days": 2.5},
                ],
            },
            headers=AUTH,
        )
        assert r.status_code == 200, f"Expected 200 for valid v2 request, got {r.status_code}: {r.text}"
        data = r.json()
        assert "profit_guidance" in data
        assert data["profit_guidance"]["on_site_weeks"] == 1  # ceil(3.5/5)=1

    def test_rates_endpoint_includes_v2_fields(self, admin_client):
        """GET /estimator/rates must return daily_overhead_rates and profit floor fields (MEDIUM-3)."""
        branch = self._branch_with_v2_config(admin_client)
        r = admin_client.get(
            f"/estimator/rates?branch={branch}&region=FBC",
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "daily_overhead_rates" in data, "rates must include daily_overhead_rates"
        assert "weekly_profit_floor" in data
        assert "job_profit_floor" in data
        assert "daily_overhead_weeks_rounding_mode" in data
        assert data["daily_overhead_rates"]["shingle"] == 700


class TestEstimatePersistence:
    def test_quote_persists_estimate_row(self, admin_client):
        """POST /quote with active config must persist an Estimate row with audit fields."""
        from sqlalchemy import select
        from app.models import Estimate, SessionLocal

        branch = _unique_branch("est-persist")
        created = _create_config(admin_client, branch=branch)
        _activate_config(admin_client, created["id"])

        r = admin_client.post(
            "/estimator/quote",
            json={
                "branch": branch,
                "code_zone": "HVHZ",
                "roof_type": "13_tile",
                "num_squares": 10.0,
                "county": "broward",
            },
            headers=AUTH,
        )
        assert r.status_code == 200, r.text

        with SessionLocal() as db:
            rows = db.execute(
                select(Estimate).where(Estimate.pricing_config_id == created["id"])
            ).scalars().all()

        assert len(rows) == 1, f"Expected 1 Estimate row, got {len(rows)}"
        row = rows[0]
        assert row.pricing_config_hash == created["config_hash"]
        assert row.branch == branch
        assert row.code_zone == "HVHZ"
        assert row.input_json is not None
        assert row.result_json is not None
