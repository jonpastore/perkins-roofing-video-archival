"""Unit tests for the pure JB1 price-book engine."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from core.price_book import (
    _canon,
    compute_pricebook_hash,
    freeze_items,
    next_version,
    price_per_square,
)


def test_price_per_square_landed_cost_math():
    got = price_per_square(
        Decimal("100.00"),
        tax_rate=Decimal("0.07"),
        waste_rate=Decimal("0.10"),
        unit_coverage=Decimal("2"),
    )
    assert got == Decimal("58.8500")


def test_price_per_square_returns_none_for_missing_price_or_coverage():
    assert price_per_square(None, Decimal("0.07"), Decimal("0.10"), Decimal("2")) is None
    assert price_per_square(Decimal("100"), Decimal("0.07"), Decimal("0.10"), None) is None
    assert price_per_square(Decimal("100"), Decimal("0.07"), Decimal("0.10"), Decimal("0")) is None


def test_canon_normalizes_supported_types_recursively():
    raw = {
        "money": Decimal("45"),
        "float": 45.0,
        "date": date(2026, 7, 11),
        "dt": datetime(2026, 7, 11, 12, 30),
        "bool": True,
        "items": [Decimal("1.2"), {"x": Decimal("2.34567")}],
    }
    got = _canon(raw)
    assert got["money"] == "45.0000"
    assert got["float"] == "45.0000"
    assert got["date"] == "2026-07-11"
    assert got["dt"] == "2026-07-11T12:30:00"
    assert got["bool"] is True
    assert got["items"] == ["1.2000", {"x": "2.3457"}]


def test_pricebook_hash_is_order_stable_and_decimal_stable():
    a = [
        {"sku": "B", "name": "Beta", "unit_price": Decimal("45.0000")},
        {"sku": "A", "name": "Alpha", "unit_price": "12.3400"},
    ]
    b = [
        {"sku": "A", "name": "Alpha", "unit_price": Decimal("12.34")},
        {"sku": "B", "name": "Beta", "unit_price": 45.0},
    ]
    assert compute_pricebook_hash(a) == compute_pricebook_hash(b)


def test_pricebook_hash_changes_on_economic_edit():
    base = [{"sku": "A", "name": "Alpha", "unit_price": Decimal("12.34")}]
    changed = [{"sku": "A", "name": "Alpha", "unit_price": Decimal("12.35")}]
    assert compute_pricebook_hash(base) != compute_pricebook_hash(changed)


def test_next_version():
    assert next_version([]) == 1
    assert next_version([1, 7, 3]) == 8


def test_freeze_items_returns_canonical_json_snapshot_and_rehashes():
    items = [
        {"sku": "B", "name": "Beta", "unit_price": Decimal("45")},
        {"sku": "A", "name": "Alpha", "unit_price": Decimal("12.34")},
    ]
    snapshot, h = freeze_items(items)
    assert [i["sku"] for i in snapshot] == ["A", "B"]
    assert snapshot[0]["unit_price"] == "12.3400"
    assert snapshot[1]["unit_price"] == "45.0000"
    assert h == compute_pricebook_hash(snapshot)
