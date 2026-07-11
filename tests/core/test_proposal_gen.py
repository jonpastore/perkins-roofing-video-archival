"""Unit tests for the pure JB3 proposal-generation engine."""
from decimal import Decimal

from core.perkins_packages import package_prices_snapshot, sell_price_per_sq
from core.pricing_config import compute_hash, compute_snapshot_hash
from core.proposal_gen import (
    TC_VERSION,
    _build_payment_schedule,
    _has_metal,
    compose_proposal,
    freeze_quote_snapshot,
)


def test_build_payment_schedule_standard_balance_exact():
    sched = _build_payment_schedule(Decimal("1000.01"), "standard", None)
    assert sched["variant"] == "standard-30-30-30-balance"
    assert [d["pct"] for d in sched["draws"]] == [30, 30, 30, None]
    assert [d["amount"] for d in sched["draws"]] == ["300.00", "300.00", "300.00", "100.01"]
    assert sum(Decimal(d["amount"]) for d in sched["draws"]) == Decimal("1000.01")


def test_build_payment_schedule_palmer_and_custom():
    palmer = _build_payment_schedule(Decimal("1000"), "palmer", None)
    assert palmer["variant"] == "palmer-5-draw-custom"
    assert [d["pct"] for d in palmer["draws"]] == [15, 15, 30, 30, None]

    custom = _build_payment_schedule(
        Decimal("1000"),
        "standard",
        [
            {"sequence": 1, "label": "First", "pct": Decimal("0.25")},
            {"sequence": 2, "label": "Balance", "pct": None},
        ],
    )
    assert custom["variant"] == "custom"
    assert custom["draws"] == [
        {"sequence": 1, "label": "First", "pct": 25, "amount": "250.00"},
        {"sequence": 2, "label": "Balance", "pct": None, "amount": "750.00"},
    ]


def test_has_metal_only_for_metal_roof_system_or_explicit_flag():
    assert _has_metal([{"roof_system": "metal"}])
    assert _has_metal([{"description": "Accessory", "is_metal": True}])
    assert not _has_metal([{"description": "Copper Metal Flashing", "roof_system": None}])


def test_compose_proposal_totals_optionals_discounts_and_schedule():
    proposal = compose_proposal({
        "customer": "Jane",
        "property": "123 Main",
        "project_name": "Tile roof",
        "hvhz": True,
        "payment_variant": "standard",
        "scopes": [
            {"roof_system": "tile", "tier": "PROTECTOR", "squares": "10"},
            # optional excluded by default
            {"roof_system": "shingle", "tier": "PROTECTOR", "squares": "1", "is_optional": True},
            # included optional counts in total
            {"roof_system": "flat", "tier": "PROLONG", "squares": "2", "is_optional": True, "included": True},
        ],
        "extra_lines": [
            {"description": "Gutters", "qty": "100", "unit_price": "10", "line_total": "1000.00"},
        ],
        "discounts": [{"description": "Referral", "amount": "500.00"}],
    })

    tile = sell_price_per_sq("tile", "PROTECTOR") * Decimal("10")
    flat = sell_price_per_sq("flat", "PROLONG") * Decimal("2")
    expected_total = tile + flat + Decimal("1000.00") - Decimal("500.00")
    assert proposal["customer"] == "Jane"
    assert proposal["property"] == "123 Main"
    assert proposal["project_name"] == "Tile roof"
    assert proposal["hvhz"] is True
    assert proposal["tax"] == "0.00"
    assert proposal["contract_total"] == str(expected_total.quantize(Decimal("0.01")))
    assert proposal["expiry_days"] == 30
    expected_balance = (expected_total * Decimal("0.10")).quantize(Decimal("0.01"))
    assert proposal["payment_schedule"]["draws"][-1]["amount"] == str(expected_balance)
    assert proposal["tc_version"] == TC_VERSION
    assert proposal["scope_lines"][1]["is_optional"] is True
    assert proposal["scope_lines"][-1]["line_total"] == "-500.00"


def test_compose_proposal_explicit_unit_price_and_missing_squares():
    proposal = compose_proposal({
        "scopes": [
            {"roof_system": "shingle", "tier": "PROTECTOR", "squares": None, "unit_price": "999.00"},
        ],
        "extra_lines": [
            {"description": "Allowance", "line_total": "250.00"},
        ],
    })
    assert proposal["scope_lines"][0]["unit_price"] == "999.00"
    assert proposal["scope_lines"][0]["line_total"] == "0.00"
    assert proposal["scope_lines"][0]["squares"] is None
    assert proposal["scope_lines"][1]["unit_price"] is None
    assert proposal["scope_lines"][1]["squares"] is None
    assert proposal["contract_total"] == "250.00"


def test_compose_proposal_metal_roof_shortens_expiry():
    p1 = compose_proposal({"scopes": [{"roof_system": "metal", "tier": "PROTECTOR", "squares": "1"}]})
    assert p1["expiry_days"] == 15
    p2 = compose_proposal({"extra_lines": [{"description": "Metal roof", "line_total": "1", "is_metal": True}]})
    assert p2["expiry_days"] == 15


def test_freeze_quote_snapshot_pins_package_tables_price_book_and_hash():
    proposal = compose_proposal({
        "scopes": [
            {"roof_system": "tile", "tier": "PROTECTOR", "squares": "1"},
            {"roof_system": "metal", "tier": "CARIBBEAN", "squares": "1"},
        ],
    })
    price_book = {"items": [{"sku": "A", "unit_price": "1.00"}]}
    snapshot, h = freeze_quote_snapshot(proposal, price_book=price_book)
    assert snapshot is not proposal
    assert snapshot["package_tables"] == {
        "metal": package_prices_snapshot("metal"),
        "tile": package_prices_snapshot("tile"),
    }
    assert snapshot["price_book_hash"] == compute_hash(price_book)
    assert snapshot["tc_version"] == TC_VERSION
    assert h == compute_snapshot_hash(snapshot)


def test_freeze_quote_snapshot_uses_existing_price_book_hash():
    proposal = compose_proposal({"scopes": []})
    snapshot, _ = freeze_quote_snapshot(proposal, price_book={"config_hash": "abc", "items": []})
    assert snapshot["price_book_hash"] == "abc"


def test_freeze_quote_snapshot_without_price_book():
    proposal = compose_proposal({"scopes": []})
    snapshot, h = freeze_quote_snapshot(proposal)
    assert "price_book_hash" not in snapshot
    assert snapshot["package_tables"] == {}
    assert h == compute_snapshot_hash(snapshot)
