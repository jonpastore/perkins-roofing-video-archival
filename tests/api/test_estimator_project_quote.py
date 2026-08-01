"""POST /estimator/project-quote — the persistence half of #430/#449 (slice 2).

R1 behavioural validation for new I/O: core/bid_project.py's pricing is already covered as pure
logic, so what these tests exist to prove is the part that only fails against a real request and a
real session — that the site-scoped fees are charged ONCE through the HTTP path, that N estimates
and one bid_project actually persist with the join populated, and that a project quote prices each
building through the same mapping a single quote does.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
import core.bid_project as BP
from app.models import BidProject, Estimate, SessionLocal, init_db

from tests.api.test_estimator_f2 import (
    AUTH,
    SAMPLE_CONFIG,
    _activate_config,
    _create_config,
    _unique_branch,
)


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                            "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


def _seeded_branch(client, prefix="proj"):
    branch = _unique_branch(prefix)
    created = _create_config(client, branch=branch, label="v1", config=SAMPLE_CONFIG)
    _activate_config(client, created["id"])
    return branch


def _building(name, squares, branch, **over):
    quote = {"branch": branch, "code_zone": "HVHZ", "roof_type": "13_tile",
             "num_squares": squares, "overhead_mode": "per_sq"}
    quote.update(over)
    return {"name": name, "quote": quote}


def _payload(branch, buildings, **over):
    body = {"name": f"Evergrene {uuid.uuid4().hex[:6]}", "buildings": buildings}
    body.update(over)
    return body


class TestProjectQuote:
    def test_site_fees_are_charged_once_not_per_building(self, admin_client):
        """The whole point of #430: three buildings, ONE delivery/permit/bonus charge.

        Compared against the same three roofs quoted separately, which is what prod did before.
        """
        branch = _seeded_branch(admin_client)
        buildings = [_building(n, sq, branch) for n, sq in
                     [("Clubhouse", 30), ("Bus Stop", 3), ("Gazebo", 5)]]

        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, buildings), headers=AUTH)
        assert r.status_code == 200, r.text
        data = r.json()

        fixed_keys = [f["key"] for f in data["project_fixed"]]
        assert fixed_keys.count("delivery_plywood_vents") == 1
        assert fixed_keys.count("permit_processing") == 1
        assert fixed_keys.count("new_bonus_values") == 1

        separate = 0.0
        for b in buildings:
            single = admin_client.post("/estimator/quote", json=b["quote"], headers=AUTH)
            assert single.status_code == 200, single.text
            separate += single.json()["project_total"]
        # The project must come in UNDER three standalone quotes — that gap is the over-charge.
        assert data["project_total"] < separate

    def test_persists_one_project_and_one_estimate_per_building(self, admin_client):
        branch = _seeded_branch(admin_client)
        buildings = [_building("Clubhouse", 30, branch), _building("Bus Stop", 3, branch)]
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, buildings), headers=AUTH)
        assert r.status_code == 200, r.text
        data = r.json()

        assert len(data["estimate_ids"]) == 2
        db = SessionLocal()
        db.info["tenant_id"] = 1
        try:
            project = db.get(BidProject, data["bid_project_id"])
            assert project is not None
            assert project.profit_floor_basis == "project"
            rows = (db.query(Estimate)
                      .filter(Estimate.bid_project_id == data["bid_project_id"])
                      .order_by(Estimate.id).all())
            assert [e.structure_name for e in rows] == ["Clubhouse", "Bus Stop"]
            # Every row must carry the join AND the config hash, or a project is not reproducible.
            assert all(e.pricing_config_hash for e in rows)
        finally:
            db.close()

    def test_persist_false_writes_nothing(self, admin_client):
        """The SPA re-prices on every keystroke; that must not litter the audit table."""
        branch = _seeded_branch(admin_client)
        db = SessionLocal()
        db.info["tenant_id"] = 1
        before = db.query(Estimate).count()
        db.close()

        r = admin_client.post(
            "/estimator/project-quote",
            json=_payload(branch, [_building("Clubhouse", 30, branch)], persist=False),
            headers=AUTH)
        assert r.status_code == 200, r.text
        assert "bid_project_id" not in r.json()

        db = SessionLocal()
        db.info["tenant_id"] = 1
        assert db.query(Estimate).count() == before
        db.close()

    def test_mixed_branches_refused(self, admin_client):
        branch = _seeded_branch(admin_client)
        other = _seeded_branch(admin_client, "other")
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("A", 10, branch), _building("B", 10, other)]), headers=AUTH)
        assert r.status_code == 422
        assert "branch" in r.text

    def test_mixed_zones_refused(self, admin_client):
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch,
            [_building("A", 10, branch),
             _building("B", 10, branch, code_zone="FBC")]), headers=AUTH)
        assert r.status_code == 422
        assert "code_zone" in r.text

    def test_no_buildings_refused_by_validation(self, admin_client):
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, []), headers=AUTH)
        assert r.status_code == 422

    def test_building_basis_matches_separate_quotes(self, admin_client):
        """`building` basis is the documented escape hatch back to pre-project behaviour.

        If it does not reproduce standalone quotes, the rollback is not a rollback.
        """
        branch = _seeded_branch(admin_client)
        buildings = [_building("A", 20, branch), _building("B", 12, branch)]
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, buildings, floor_basis="building"), headers=AUTH)
        assert r.status_code == 200, r.text

        separate = 0.0
        for b in buildings:
            single = admin_client.post("/estimator/quote", json=b["quote"], headers=AUTH)
            separate += single.json()["project_total"]
        assert r.json()["project_total"] == pytest.approx(separate, abs=0.02)

    def test_project_items_add_to_total_and_profit(self, admin_client):
        """General Conditions is markup-bearing scope, not a pass-through cost."""
        branch = _seeded_branch(admin_client)
        base = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("Clubhouse", 30, branch)], persist=False), headers=AUTH).json()

        withgc = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("Clubhouse", 30, branch)], persist=False,
            project_items=[{"key": "gc", "label": "General Conditions",
                            "cost": 31800, "markup": 1.15}]), headers=AUTH).json()

        assert withgc["project_total"] == pytest.approx(base["project_total"] + 36570, abs=0.02)
        assert withgc["profit"] == pytest.approx(base["profit"] + (36570 - 31800), abs=0.02)

    def test_dominant_roof_type_is_the_largest_not_the_first(self, admin_client):
        """A nine-structure tile job must not describe itself by whatever was listed first."""
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(branch, [
            _building("Small metal", 3, branch, roof_type="standing_seam_metal"),
            _building("Big tile", 40, branch, roof_type="13_tile"),
        ], persist=False), headers=AUTH)
        assert r.status_code == 200, r.text
        assert r.json()["dominant_roof_type"] == "13_tile"
        assert r.json()["num_squares"] == pytest.approx(43)

    def test_unknown_roof_type_still_422s_through_the_project_path(self, admin_client):
        """The shared mapping must keep its validation — not lose it via the project route."""
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("A", 10, branch, roof_type="not_a_roof")]), headers=AUTH)
        assert r.status_code == 422


class TestBidProjectDefaults:
    def test_once_per_project_fees_defaults_to_the_measured_set_not_empty(self):
        """A BidProject created without naming its fees must NOT charge them per building.

        SQLAlchemy sends a Python-side default explicitly, so an ORM `default=list` would write
        `[]` and migration 0052's server default would never apply — reintroducing exactly the
        per-building over-charge #430 exists to remove.
        """
        db = SessionLocal()
        db.info["tenant_id"] = 1
        try:
            row = BidProject(tenant_id=1, name="defaults probe")
            db.add(row)
            db.flush()
            # ONE authority — the same set price_project suppresses. A row created without
            # naming its fees must price identically to the quote that created it.
            assert sorted(row.once_per_project_fees) == sorted(BP.DEFAULT_ONCE_PER_PROJECT)
            assert "tile_dumpster" in row.once_per_project_fees
            assert row.profit_floor_basis == "project"
            assert row.status == "draft"
        finally:
            db.rollback()
            db.close()


class TestProjectPathHonoursTheSameGuardsAsQuote:
    """The two HIGH findings from the R2 architect review, as red tests.

    Both came from one root cause: BuildingInput.quote is the FULL QuoteRequest, so the project
    endpoint advertises every field /quote supports while implementing a subset.
    """

    def test_gutter_accessories_without_gutter_lf_are_refused(self, admin_client):
        """core/estimator.py prices the whole accessory block inside `if q.gutter_lf:`.

        Without the guard these cost exactly $0 and a bid ships under-priced, silently.
        """
        branch = _seeded_branch(admin_client)
        bad = _building("Clubhouse", 30, branch,
                        gutter_elbows=20, leaf_guard="upgraded", gutter_lf=0)
        # /quote refuses it —
        single = admin_client.post("/estimator/quote", json=bad["quote"], headers=AUTH)
        assert single.status_code == 422, single.text
        # — so the project path must too, and must name the structure.
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, [bad]), headers=AUTH)
        assert r.status_code == 422, r.text
        assert "gutter_lf" in r.text
        assert "Clubhouse" in r.text

    def test_per_building_discounts_are_refused_not_silently_dropped(self, admin_client):
        """A discount that never comes off the price, persisted into input_json, would make the
        audit row disagree with what the customer was quoted."""
        branch = _seeded_branch(admin_client)
        b = _building("Clubhouse", 30, branch,
                      discounts=[{"description": "Repeat client", "amount": 2500}])
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, [b]), headers=AUTH)
        assert r.status_code == 422, r.text
        assert "discounts" in r.text

    def test_mixed_config_id_refused(self, admin_client):
        """Third axis of the same decision as branch and code_zone."""
        branch = _seeded_branch(admin_client)
        created = _create_config(admin_client, branch=branch, label="pinned", config=SAMPLE_CONFIG)
        r = admin_client.post("/estimator/project-quote", json=_payload(branch, [
            _building("A", 10, branch),
            _building("B", 10, branch, config_id=created["id"]),
        ]), headers=AUTH)
        assert r.status_code == 422
        assert "config_id" in r.text

    def test_unknown_daily_series_names_the_building(self, admin_client):
        """On a nine-structure bid, "unknown daily_series" without a name is unactionable."""
        branch = _seeded_branch(admin_client)
        b = _building("Bus Stop", 3, branch, overhead_mode="daily",
                      daily_series=[{"series": "not_a_series", "days": 1.0}])
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, [b]), headers=AUTH)
        assert r.status_code == 422, r.text
        assert "Bus Stop" in r.text


def test_unknown_property_id_is_refused(admin_client):
    """property_id is a plain FK, and Postgres checks FKs with row security BYPASSED — so RLS on
    `properties` does not stop a bid referencing another tenant's property, only reading it back.
    """
    branch = _seeded_branch(admin_client)
    r = admin_client.post("/estimator/project-quote", json=_payload(
        branch, [_building("A", 10, branch)], property_id=999999), headers=AUTH)
    assert r.status_code == 404, r.text
    assert "Property" in r.text
