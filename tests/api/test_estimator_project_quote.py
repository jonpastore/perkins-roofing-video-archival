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



def _branch_that_prices_low_slope(client, prefix="lowslope"):
    """SAMPLE_CONFIG carries the low-slope KEYS with null prices, so nothing low-slope can be
    quoted against it. Give this branch a real price for `tpo` — the slope_type invariant under
    test is about which path prices the roof, not about the rate."""
    import copy as _copy
    cfg = _copy.deepcopy(SAMPLE_CONFIG)
    # SAMPLE_CONFIG also has no daily_overhead_rates, so nothing can be quoted BY DAYS against it
    # — the API validates every submitted series name against that map. Give it Tim's four rates
    # plus low_slope. (infra/fixtures/pricing_config_exhibit_b.json has the same gap against prod;
    # see the fixture-drift note in the handoff.)
    cfg.setdefault("daily_overhead_rates", {}).update(
        {"tile": 745, "metal": 850, "shingle": 700, "demo_dry_in_flat": 1050, "low_slope": 1050})
    cfg["overhead_basis"] = "branch"
    cfg["office_daily_overhead"] = 1470
    cfg["concurrent_crews"] = 1.5
    # `demo_series` is what tells the install-days guard which entry is the tear-off. Without it
    # a demo-only quote counts its demo days AS install and slips through — which is how the
    # guard's own test first passed against a 200.
    cfg.setdefault("daily_overhead_day_model", {}).update({
        "demo_series": "demo_dry_in_flat",
        "series": {"tile": {"setup": 0.45, "rate": 0.129},
                   "demo_dry_in_flat": {"setup": 1.31, "rate": 0.044},
                   "low_slope": {"setup": 0.389, "rate": 0.0851}},
        "install_series_by_roof_type": {"13_tile": "tile", "tpo": "low_slope"},
        "flat_series": {"series": "low_slope"},
    })
    for zone in ("HVHZ", "FBC"):
        cfg.setdefault("low_slope", {}).setdefault("base_cost_lm", {}).setdefault(zone, {})["tpo"] = 485
        cfg["low_slope"].setdefault("overhead", {}).setdefault(zone, {})["tpo_oh"] = 135
        cfg["low_slope"]["overhead"][zone].setdefault("flat_oh", 155)
    branch = _unique_branch(prefix)
    created = _create_config(client, branch=branch, label="v1", config=cfg)
    _activate_config(client, created["id"])
    return branch, cfg


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
        # persist is opt-IN: the SPA re-prices per keystroke and must not grow two tables doing it.
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, buildings, persist=True), headers=AUTH)
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
            json=_payload(branch, [_building("Clubhouse", 30, branch)]),
            headers=AUTH)
        assert r.status_code == 200, r.text
        assert "bid_project_id" not in r.json(), "persist must default to False"

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


class TestProjectQuoteBounds:
    def test_duplicate_structure_names_refused(self, admin_client):
        """structure_name is how a persisted project tells nine estimates apart."""
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("Main", 10, branch), _building("Main", 12, branch)]), headers=AUTH)
        assert r.status_code == 422
        assert "duplicate structure name" in r.text

    def test_building_list_is_capped(self, admin_client):
        """One estimating_view caller could otherwise hold a worker with 10,000 buildings."""
        branch = _seeded_branch(admin_client)
        many = [_building(f"B{i}", 5, branch) for i in range(51)]
        r = admin_client.post("/estimator/project-quote",
                              json=_payload(branch, many), headers=AUTH)
        assert r.status_code == 422

    def test_building_allocation_is_refused_until_the_fold_exists(self, admin_client):
        """It was accepted, echoed back, and priced as its own line — a silent no-op on money."""
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("Clubhouse", 30, branch)],
            project_items=[{"key": "addons", "label": "Sloped add-ons", "cost": 42050,
                            "allocation": "building:Clubhouse"}]), headers=AUTH)
        assert r.status_code == 422

    def test_duplicate_project_item_keys_refused(self, admin_client):
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("Clubhouse", 30, branch)],
            project_items=[{"key": "gc", "label": "A", "cost": 100},
                           {"key": "gc", "label": "B", "cost": 200}]), headers=AUTH)
        assert r.status_code == 422


class TestAProjectIsReadableAndReproducible:
    """The write half of slice 2 shipped with no reader. These are the seams slice 3 needs."""

    def test_estimates_list_exposes_the_project_join_and_a_total(self, admin_client):
        branch = _seeded_branch(admin_client)
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("Clubhouse", 30, branch), _building("Bus Stop", 3, branch)],
            persist=True), headers=AUTH)
        assert r.status_code == 200, r.text
        pid = r.json()["bid_project_id"]

        listed = admin_client.get("/estimator/estimates", headers=AUTH)
        assert listed.status_code == 200, listed.text
        rows = [e for e in listed.json() if e.get("bid_project_id") == pid]
        assert len(rows) == 2, "the project join must be visible in the estimates list"
        assert sorted(e["structure_name"] for e in rows) == ["Bus Stop", "Clubhouse"]
        # Quoting.tsx reads result_json.project_total; without it every building renders "—".
        for e in rows:
            assert e["result_json"].get("project_total") is not None

    def test_input_json_carries_what_the_price_depended_on(self, admin_client):
        """days and permit_count decide the floor and are not part of QuoteRequest.

        Without them a week-basis project cannot be recomputed from its own audit rows.
        """
        branch = _seeded_branch(admin_client)
        buildings = [dict(_building("Clubhouse", 30, branch), days=6),
                     dict(_building("Bus Stop", 3, branch), days=2)]
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, buildings, persist=True, permit_count=3), headers=AUTH)
        assert r.status_code == 200, r.text
        pid = r.json()["bid_project_id"]

        listed = admin_client.get("/estimator/estimates", headers=AUTH)
        rows = [e for e in listed.json() if e.get("bid_project_id") == pid]
        assert {e["input_json"]["structure_days"] for e in rows} == {6, 2}
        assert all(e["input_json"]["project_permit_count"] == 3 for e in rows)
        assert all(e["input_json"]["project_floor_basis"] == "project" for e in rows)
        assert all("tile_dumpster" in e["input_json"]["project_once_per_project"] for e in rows)


def test_add_on_blocks_price_like_general_conditions_but_persist_separately(admin_client):
    """Tim's bid keeps GC ($36,570) and add-ons ($42,050 + $31,000) as distinct quoted blocks.

    The column existed for this and was being written as [] with everything folded into
    general_conditions.
    """
    branch = _seeded_branch(admin_client)
    r = admin_client.post("/estimator/project-quote", json=_payload(
        branch, [_building("Clubhouse", 30, branch)], persist=True,
        project_items=[{"key": "gc", "label": "General Conditions", "cost": 31800,
                        "markup": 1.15}],
        add_on_blocks=[{"key": "sloped_addons", "label": "Sloped add-ons", "cost": 42050}],
    ), headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()

    keys = {i["key"] for i in data["project_items"]}
    assert {"gc", "sloped_addons"} <= keys, "both blocks must reach the priced roll-up"

    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        project = db.get(BidProject, data["bid_project_id"])
        assert [b["key"] for b in project.general_conditions] == ["gc"]
        assert [b["key"] for b in project.add_on_blocks] == ["sloped_addons"]
    finally:
        db.close()


def test_permit_count_defaults_to_the_building_count_through_the_route(admin_client):
    """Tim, 2026-08-02: one permit per building. A caller that sends nothing gets that, and the
    number it was charged for is echoed AND persisted — otherwise the proposal re-price and the
    quote would disagree about how many permits this bid bought."""
    branch = _seeded_branch(admin_client)
    r = admin_client.post("/estimator/project-quote", json=_payload(
        branch, [_building("Clubhouse", 30, branch), _building("Bus Stop", 3, branch),
                 _building("Gazebo", 5, branch)], persist=True), headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["permit_count"] == 3
    permit = next(f for f in data["project_fixed"] if f["key"] == "permit_processing")
    assert permit["amount"] == 3 * float(SAMPLE_CONFIG["permit_processing"])

    listed = admin_client.get("/estimator/estimates", headers=AUTH)
    rows = [e for e in listed.json() if e.get("bid_project_id") == data["bid_project_id"]]
    assert all(e["input_json"]["project_permit_count"] == 3 for e in rows)


def test_structure_addresses_persist_and_reach_the_roll_up(admin_client):
    """#6. The address moves no money; it has to survive to the proposal, so it is a COLUMN."""
    branch = _seeded_branch(admin_client)
    r = admin_client.post("/estimator/project-quote", json=_payload(
        branch, [_building("Clubhouse", 30, branch),
                 dict(_building("North Gate", 3, branch), address="1 Hood Rd")],
        persist=True), headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert [b["address"] for b in data["buildings"]] == [None, "1 Hood Rd"]

    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        rows = db.query(Estimate).filter(
            Estimate.bid_project_id == data["bid_project_id"]).order_by(Estimate.id).all()
        assert [e.structure_address for e in rows] == [None, "1 Hood Rd"]
    finally:
        db.close()


def test_a_gc_block_with_no_markup_takes_the_project_slider(admin_client):
    """Tim, 2026-08-02: "we have a slider for this". bid_projects.general_conditions_markup was
    written as a flat 1.0 that nothing read; now it is the default a block inherits, and the
    block is PERSISTED at the rate it was priced at so the proposal re-price reproduces it."""
    branch = _seeded_branch(admin_client)
    r = admin_client.post("/estimator/project-quote", json=_payload(
        branch, [_building("Clubhouse", 30, branch)], persist=True,
        general_conditions_markup=1.15,
        project_items=[{"key": "gc", "label": "General Conditions", "cost": 31800},
                       {"key": "own", "label": "Its own rate", "cost": 1000, "markup": 1.5}],
    ), headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()

    priced = {i["key"]: i for i in data["project_items"]}
    assert priced["gc"]["amount"] == 31800 * 1.15          # inherited
    assert priced["own"]["amount"] == 1000 * 1.5           # a block that named a rate keeps it

    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        project = db.get(BidProject, data["bid_project_id"])
        assert float(project.general_conditions_markup) == 1.15   # NUMERIC -> Decimal
        stored = {b["key"]: b["markup"] for b in project.general_conditions}
        assert stored == {"gc": 1.15, "own": 1.5}, "persist the EFFECTIVE markup, not the null"
    finally:
        db.close()


class TestProjectProposal:
    """POST /quoting/proposals/from-project — the slice-3 feature, end to end.

    Lives here rather than in the proposals suite because it needs a REAL persisted project:
    the route re-prices from stored inputs, so a hand-built fixture would prove nothing about
    whether what /estimator/project-quote writes is actually re-pricable.
    """

    def _customer_and_property(self, client):
        c = client.post("/quoting/customers",
                        json={"display_name": f"Cust-{uuid.uuid4().hex[:8]}",
                              "email": f"{uuid.uuid4().hex[:8]}@test.com"}, headers=AUTH)
        assert c.status_code == 200, c.text
        cid = c.json()["id"]
        p = client.post(f"/quoting/customers/{cid}/properties",
                        json={"street": f"{uuid.uuid4().hex[:6]} Oak Ave", "city": "Jupiter",
                              "state": "FL", "zip": "33478", "code_zone": "HVHZ"}, headers=AUTH)
        assert p.status_code == 200, p.text
        return cid, p.json()["id"]

    def test_a_persisted_project_becomes_one_coherent_proposal(self, admin_client):
        branch = _seeded_branch(admin_client)
        cid, pid = self._customer_and_property(admin_client)

        quoted = admin_client.post("/estimator/project-quote", json=_payload(
            branch,
            [_building("Clubhouse", 30, branch), _building("Bus Stop", 3, branch),
             _building("Gazebo", 5, branch)],
            persist=True,
            project_items=[{"key": "gc", "label": "General Conditions", "cost": 31800,
                            "markup": 1.15}],
        ), headers=AUTH)
        assert quoted.status_code == 200, quoted.text
        project_id = quoted.json()["bid_project_id"]

        r = admin_client.post(f"/quoting/proposals/from-project/{project_id}",
                              json={"customer_id": cid, "property_id": pid,
                                    "deposit_percent": 50}, headers=AUTH)
        assert r.status_code == 200, r.text
        prop = r.json()
        snap = prop["quote_snapshot"]

        assert prop["bid_project_id"] == project_id
        # A project covers N estimates; pointing at one would be the same category error as
        # re-quoting one.
        assert prop["estimate_id"] is None
        assert len(snap["buildings"]) == 3
        assert snap["project_totals"]["building_count"] == 3
        # The scalars must agree with the buildings — that is what the edit gate enforces.
        assert snap["num_squares"] == 38
        assert any(i["key"] == "gc" for i in snap["project_items"])
        assert snap["deposit_policy"]["mode"] == "percent"

    def test_the_proposal_reproduces_the_quoted_total_it_was_built_from(self, admin_client):
        """The re-price must land on the SAME number the customer was quoted.

        This is the seam the whole persist-then-re-price design rests on, and it has two live
        hazards that only show up here: the General Conditions markup is INHERITED from the project
        slider (so if the effective rate were not persisted, `float(b["markup"] or 1.0)` in
        create_proposal_from_project would quietly quote the block at cost), and permit_count now
        DEFAULTS to the building count (so if the stored count were not honoured, a bid quoted at
        one site permit would be re-proposed with three).
        """
        branch = _seeded_branch(admin_client)
        cid, pid = self._customer_and_property(admin_client)

        quoted = admin_client.post("/estimator/project-quote", json=_payload(
            branch,
            [_building("Clubhouse", 30, branch), _building("Bus Stop", 3, branch),
             _building("Gazebo", 5, branch)],
            persist=True,
            permit_count=1,                       # one site permit, against the 3-building default
            general_conditions_markup=1.15,
            project_items=[{"key": "gc", "label": "General Conditions", "cost": 31800}],
        ), headers=AUTH)
        assert quoted.status_code == 200, quoted.text
        quote = quoted.json()
        assert quote["permit_count"] == 1

        r = admin_client.post(f"/quoting/proposals/from-project/{quote['bid_project_id']}",
                              json={"customer_id": cid, "property_id": pid}, headers=AUTH)
        assert r.status_code == 200, r.text
        snap = r.json()["quote_snapshot"]

        assert snap["tiers"]["good"]["total"] == quote["project_total"], (
            "the proposal re-priced to a different number than the bid it reproduces")
        gc = next(i for i in snap["project_items"] if i["key"] == "gc")
        assert gc["amount"] == round(31800 * 1.15, 2)
        # project_snapshot folds project_fixed into project_items, so the permit line lands here.
        quoted_permit = next(f for f in quote["project_fixed"] if f["key"] == "permit_processing")
        permit = next(i for i in snap["project_items"] if i["key"] == "permit_processing")
        assert permit["amount"] == quoted_permit["amount"]
        assert "x3" not in permit["label"], "re-proposed with the default count, not the stored one"

    def test_the_generated_snapshot_passes_its_own_edit_gate(self, admin_client):
        """What we write must survive what we validate — otherwise the gate blocks our own output."""
        from core.proposal import validate_project_snapshot, validate_snapshot

        branch = _seeded_branch(admin_client)
        cid, pid = self._customer_and_property(admin_client)
        quoted = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("A", 20, branch), _building("B", 12, branch)], persist=True,
        ), headers=AUTH)
        project_id = quoted.json()["bid_project_id"]

        r = admin_client.post(f"/quoting/proposals/from-project/{project_id}",
                              json={"customer_id": cid, "property_id": pid}, headers=AUTH)
        assert r.status_code == 200, r.text
        snap = r.json()["quote_snapshot"]

        validate_project_snapshot(snap, snap)          # must not raise
        validate_snapshot({**snap, "sent_at_iso": "2026-08-01T00:00:00Z"})

    def test_a_project_with_no_estimates_is_refused(self, admin_client):
        branch = _seeded_branch(admin_client)
        cid, pid = self._customer_and_property(admin_client)
        quoted = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [_building("A", 20, branch)], persist=False), headers=AUTH)
        assert "bid_project_id" not in quoted.json()

        r = admin_client.post("/quoting/proposals/from-project/999999",
                              json={"customer_id": cid, "property_id": pid}, headers=AUTH)
        assert r.status_code == 404

    def test_input_json_records_the_slope_type_that_was_PRICED(self, admin_client):
        """A low-slope structure must persist slope_type='low_slope', not the body's 'sloped'.

        `/estimator/quote` and `/estimator/project-quote` coerce slope_type FROM the roof type
        (`effective_slope_type`), so a TPO structure prices down the low-slope path whatever the
        body said. The audit row stored the RAW body, and
        `/quoting/proposals/from-project` rebuilds a QuoteInput straight from that row — so the
        rebuilt quote priced the SLOPED path and died on
        `sloped_base_cost_lm[zone][<low-slope key>]`. An unhandled 500 on a customer-facing
        document, generated from a row that had priced perfectly well.

        Six such rows existed in prod (estimates 27-31 and 105); none had reached a bid project,
        so nothing shipped wrong. The row now records what was CHARGED, which is the same rule
        num_squares and flat_squares already followed.
        """
        branch, _cfg = _branch_that_prices_low_slope(admin_client)
        flat = _building("Clubhouse Flats", 28, branch,
                         roof_type="tpo", slope_type="sloped")
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [flat], persist=True), headers=AUTH)
        assert r.status_code == 200, r.text
        pid = r.json()["bid_project_id"]

        listed = admin_client.get("/estimator/estimates", headers=AUTH)
        rows = [e for e in listed.json() if e.get("bid_project_id") == pid]
        assert len(rows) == 1, rows
        assert rows[0]["input_json"]["slope_type"] == "low_slope", (
            "the audit row kept the raw 'sloped'; rebuilding it prices the wrong path")

    def test_a_stored_low_slope_row_can_be_repriced(self, admin_client):
        """The end the previous test protects: rebuild a QuoteInput from the stored row exactly
        as proposals.py does, and price it. This fails for a DIFFERENT reason than the assertion
        above — a row could carry the right slope_type and still not re-price."""
        from dataclasses import fields as _fields

        from core.estimator import QuoteInput, estimate
        from core.pricing_config import load_config

        branch, cfg = _branch_that_prices_low_slope(admin_client)
        flat = _building("Flats", 28, branch, roof_type="tpo", slope_type="sloped")
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [flat], persist=True), headers=AUTH)
        pid = r.json()["bid_project_id"]
        row = [e for e in admin_client.get("/estimator/estimates", headers=AUTH).json()
               if e.get("bid_project_id") == pid][0]

        stored = dict(row["input_json"])
        keep = {f.name for f in _fields(QuoteInput)}
        quote = QuoteInput(**{k: v for k, v in stored.items() if k in keep and v is not None})
        priced = estimate(load_config(cfg), quote)
        assert priced["project_total"] > 0

    def test_a_by_days_project_proposal_reprices_without_500(self, admin_client):
        """`daily_series` round-trips through JSON as DICTS, and QuoteInput wants
        DailyOverheadSeries. Left raw it reached price_project and raised
        `AttributeError: 'dict' object has no attribute 'days'` — an unhandled 500 on the
        customer-facing document, caught by neither handler in the rebuild path.

        Latent while the day cells were always blank (an empty list is harmless); the day
        suggestion pre-fill makes a populated daily_series the normal case, which is why this is
        now a gate.
        """
        branch, _cfg = _branch_that_prices_low_slope(admin_client)
        b = _building("Clubhouse", 30, branch)
        b["quote"]["overhead_mode"] = "daily"
        b["quote"]["daily_series"] = [{"series": "tile", "days": 4.5},
                                      {"series": "demo_dry_in_flat", "days": 2.0}]
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [b], persist=True), headers=AUTH)
        assert r.status_code == 200, r.text
        pid = r.json()["bid_project_id"]

        from tests.api.test_f3_proposals import _create_customer, _create_property
        cust = _create_customer(admin_client)
        prop_row = _create_property(admin_client, cust["id"])
        made = admin_client.post(
            f"/quoting/proposals/from-project/{pid}",
            json={"customer_id": cust["id"], "property_id": prop_row["id"]}, headers=AUTH)
        # Anything but a 500. A 422 with a reason is a valid outcome; an unhandled crash is not.
        assert made.status_code != 500, made.text
        assert made.status_code == 200, made.text
    def test_install_days_are_required_and_at_least_one(self, admin_client):
        """Tim, 2026-08-04: "no install days is an error, 1 min required" (demo may be 0).

        This closes a silent UNDER-BILL, not a typo: the engine derives days only when
        daily_series arrives EMPTY, so a caller who sent demo days alone got a quote with no
        install overhead at all and no warning. Measured on a 20 sq HVHZ tile roof, $25,090
        against the $27,050 the same job prices at when the days are derived — $1,960 missing,
        because "blank" was read as "zero" rather than "estimate it".
        """
        branch, _cfg = _branch_that_prices_low_slope(admin_client)
        demo_only = _building("Clubhouse", 30, branch)
        demo_only["quote"]["overhead_mode"] = "daily"
        demo_only["quote"]["daily_series"] = [{"series": "demo_dry_in_flat", "days": 2.0}]
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [demo_only]), headers=AUTH)
        assert r.status_code == 422, r.text
        assert "install days are required" in r.text

        # …and the same body with install days priced is accepted.
        ok = _building("Clubhouse", 30, branch)
        ok["quote"]["overhead_mode"] = "daily"
        ok["quote"]["daily_series"] = [{"series": "demo_dry_in_flat", "days": 2.0},
                                       {"series": "tile", "days": 4.5}]
        r2 = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [ok]), headers=AUTH)
        assert r2.status_code == 200, r2.text

    def test_demo_days_may_be_omitted_entirely(self, admin_client):
        """"0 is acceptable" for demo — new construction has no tear-off. Omitting the entry is
        how zero is expressed, since DailySeriesItem requires days > 0 per entry."""
        branch, _cfg = _branch_that_prices_low_slope(admin_client)
        b = _building("Clubhouse", 30, branch)
        b["quote"]["overhead_mode"] = "daily"
        b["quote"]["existing_roof"] = "none"
        b["quote"]["daily_series"] = [{"series": "tile", "days": 4.5}]
        r = admin_client.post("/estimator/project-quote", json=_payload(
            branch, [b]), headers=AUTH)
        assert r.status_code == 200, r.text
