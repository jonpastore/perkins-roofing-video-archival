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
