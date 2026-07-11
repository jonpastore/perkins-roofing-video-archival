#!/usr/bin/env python3
"""Behavioral self-check for the JB1 price-book schema and engine.

Hermetic: builds an isolated in-memory SQLite DB from the ORM metadata (does NOT
touch the app's real engine), then exercises the price-book invariants.

    PYTHONPATH=. .venv/bin/python scripts/validate_pricebook.py   # exits non-zero on failure

Note on tenant isolation (M2-e): RLS is a Postgres-only feature and is a no-op
under SQLite. Cross-tenant isolation is proven by the Postgres-backed
tests/tenancy/ suite, not here.
"""
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, PriceBook, PriceBookItem
from core.price_book import (
    compute_pricebook_hash,
    freeze_items,
    next_version,
    price_per_square,
)

engine = create_engine("sqlite:///:memory:", future=True)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, future=True)


def main():
    # --- price_per_square math ---
    # 1 roll covers 1.9 sq: 100 * 1.07 * 1.10 / 1.9 = 61.9474...
    result = price_per_square(
        unit_price=Decimal("100"),
        tax_rate=Decimal("0.07"),
        waste_rate=Decimal("0.10"),
        unit_coverage=Decimal("1.9"),
    )
    assert result is not None
    assert abs(result - Decimal("61.9474")) < Decimal("0.001"), (
        f"price_per_square wrong: {result}"
    )

    # NULL unit_price → None (not-stocked)
    assert price_per_square(None, Decimal("0.07"), Decimal("0.10"), Decimal("1.9")) is None

    # NULL coverage → None (not a per-sq item)
    assert price_per_square(Decimal("100"), Decimal("0.07"), Decimal("0.10"), None) is None

    # Zero coverage → None (guard against divide-by-zero)
    assert price_per_square(Decimal("100"), Decimal("0.07"), Decimal("0.10"), Decimal("0")) is None

    # --- M2(a): freeze_items on Decimal-valued dicts must not raise (C1 regression) ---
    decimal_items = [
        {
            "sku": "SH-30",
            "name": "30# felt",
            "unit_price": Decimal("45.00"),
            "unit_coverage": Decimal("2.0"),
            "tax_rate": Decimal("0.07"),
            "waste_rate": Decimal("0.10"),
        },
        {
            "sku": "OA-CAP",
            "name": "OA cap sheet",
            "unit_price": Decimal("120.00"),
            "unit_coverage": Decimal("1.0"),
            "tax_rate": Decimal("0.07"),
            "waste_rate": Decimal("0.10"),
        },
    ]
    snap_dec, h_dec = freeze_items(decimal_items)  # must not raise TypeError
    assert isinstance(h_dec, str) and len(h_dec) == 64, "freeze_items must return a 64-char hash"

    # --- M2(b): Decimal↔canonical-string equivalence ---
    # The same data expressed as 4dp strings must produce an identical hash.
    string_items = [
        {
            "sku": "SH-30",
            "name": "30# felt",
            "unit_price": "45.0000",
            "unit_coverage": "2.0000",
            "tax_rate": "0.0700",
            "waste_rate": "0.1000",
        },
        {
            "sku": "OA-CAP",
            "name": "OA cap sheet",
            "unit_price": "120.0000",
            "unit_coverage": "1.0000",
            "tax_rate": "0.0700",
            "waste_rate": "0.1000",
        },
    ]
    h_str = compute_pricebook_hash(string_items)
    assert h_dec == h_str, (
        f"Decimal items and canonical-string items must hash identically: "
        f"{h_dec!r} != {h_str!r}"
    )

    # --- version immutability / hash stability (using Decimal rows) ---
    snap1, h1 = freeze_items(decimal_items)

    # Mutate source list — snapshot must be independent (snap stores canonical strings).
    # freeze_items sorts by (sku,name) so snap1[0]="OA-CAP", snap1[1]="SH-30".
    decimal_items[0]["unit_price"] = Decimal("99.00")  # decimal_items[0] is SH-30
    sh30 = next(r for r in snap1 if r["sku"] == "SH-30")
    assert sh30["unit_price"] == "45.0000", (
        "freeze_items snapshot must be a canonical copy, not a reference"
    )

    # Changing a price changes the hash (snap1 has canonical strings; mutate SH-30)
    items_v2 = [dict(i) for i in snap1]
    next(r for r in items_v2 if r["sku"] == "SH-30")["unit_price"] = "50.0000"
    snap2, h2 = freeze_items(items_v2)
    assert h1 != h2, "different item prices must produce different hashes"

    # Identical content → identical hash (deterministic)
    _, h1_again = freeze_items([dict(i) for i in snap1])
    assert h1 == h1_again, "same items must always hash identically"

    # --- next_version ---
    assert next_version([]) == 1
    assert next_version([1]) == 2
    assert next_version([1, 3, 2]) == 4

    # --- ORM round-trip in SQLite ---
    s = Session()
    # tenant 1 is auto-seeded by Tenant.after_create hook on create_all

    # Persist live PriceBookItem rows with Decimal fields (mimics prod ORM hydration)
    live_item_a = PriceBookItem(
        sku="SH-30", name="30# felt", unit="roll",
        unit_price=Decimal("45.00"), unit_coverage=Decimal("2.0"),
        tax_rate=Decimal("0.07"), waste_rate=Decimal("0.10"),
        item_type="material",
    )
    live_item_b = PriceBookItem(
        sku="OA-CAP", name="OA cap sheet", unit="roll",
        unit_price=Decimal("120.00"), unit_coverage=Decimal("1.0"),
        tax_rate=Decimal("0.07"), waste_rate=Decimal("0.10"),
        item_type="material",
    )
    s.add_all([live_item_a, live_item_b])
    s.flush()

    # Build row-dicts with only the business fields the service layer would freeze
    # (not created_at/id/tenant_id/price_book_id — those are bookkeeping, not pricing).
    _PRICE_FIELDS = ("sku", "name", "unit", "unit_price", "unit_coverage",
                     "tax_rate", "waste_rate", "supplier", "item_type", "knowify_item_id")
    live_dicts = [
        {f: getattr(obj, f) for f in _PRICE_FIELDS}
        for obj in [live_item_a, live_item_b]
    ]

    # --- M2(c)/(d): freeze at v1; edit a live item; v1 snapshot unchanged ---
    snap_v1, h_v1 = freeze_items(live_dicts)

    # M2(d): hash at freeze time equals computing it fresh from the same dicts
    assert h_v1 == compute_pricebook_hash(live_dicts), (
        "config_hash must equal compute_pricebook_hash of the live dicts at freeze time"
    )

    pb1 = PriceBook(
        supplier="ABC_SUPPLY",
        version_number=1,
        label="July 2026 price run",
        items_snapshot=snap_v1,
        config_hash=h_v1,
        is_active=False,
        created_by="test",
    )
    s.add(pb1)
    s.flush()

    # Edit the live item (simulates a price update between versions)
    live_item_a.unit_price = Decimal("50.00")
    s.flush()

    # Re-read the v1 PriceBook row — snapshot and hash must be byte-identical
    s.expire(pb1)
    pb1_reread = s.get(PriceBook, pb1.id)
    assert pb1_reread.config_hash == h_v1, (
        "v1 config_hash must be unchanged after editing a live item"
    )
    # Find SH-30 in the snapshot and confirm it still holds the original price
    sh30_snap = next(r for r in pb1_reread.items_snapshot if r.get("sku") == "SH-30")
    # freeze_items stores the _canon form: Decimal("45.00") → "45.0000"
    assert sh30_snap["unit_price"] == "45.0000", (
        f"v1 snapshot unit_price must be canonical '45.0000', got {sh30_snap['unit_price']!r}"
    )

    # Persist v2 with updated prices
    live_dicts_v2 = [
        {f: getattr(obj, f) for f in _PRICE_FIELDS}
        for obj in [live_item_a, live_item_b]
    ]
    snap_v2, h_v2 = freeze_items(live_dicts_v2)
    assert h_v1 != h_v2, "price change must produce a new hash"

    pb2 = PriceBook(
        supplier="ABC_SUPPLY",
        version_number=2,
        label="July 2026 price run v2",
        items_snapshot=snap_v2,
        config_hash=h_v2,
        is_active=True,
        created_by="test",
    )
    s.add(pb2)
    s.flush()
    assert pb1.version_number == 1 and pb2.version_number == 2

    # --- knowify_item_id crosswalk round-trip ---
    item = PriceBookItem(
        name="OA cap sheet",
        sku="OA-CAP",
        unit="roll",
        unit_coverage=Decimal("1.0"),
        unit_price=Decimal("120.00"),
        knowify_item_id="kwfy-item-9988",
        item_type="material",
    )
    s.add(item)
    s.commit()

    fetched = s.query(PriceBookItem).filter_by(knowify_item_id="kwfy-item-9988").one()
    assert fetched.knowify_item_id == "kwfy-item-9988", "knowify_item_id crosswalk must round-trip"
    assert fetched.name == "OA cap sheet"

    print("OK — price-book invariants hold:")
    print(f"  price_per_square: 1 roll @ $100, 7% tax, 10% waste, 1.9 sq/roll = ${result}/sq")
    print("  NULL unit_price → None (not-stocked, never zeroed)")
    print("  NULL/0 coverage → None (not a per-sq item)")
    print("  M2(a): freeze_items on Decimal ORM rows does not raise (C1 fix verified)")
    print(f"  M2(b): Decimal items hash == canonical-string items hash ({h_dec[:12]}…)")
    print("  freeze_items produces an independent copy; price edit changes hash")
    print(f"  hash v1={h1[:12]}… != v2={h2[:12]}…  (content-addressed)")
    print(f"  M2(c): v1 snapshot byte-identical after live item edit (hash {h_v1[:8]}… unchanged)")
    print("  M2(d): config_hash == compute_pricebook_hash at freeze time")
    print("  ORM: PriceBook v1/v2 version_numbers correct; knowify_item_id round-trips")


if __name__ == "__main__":
    main()
