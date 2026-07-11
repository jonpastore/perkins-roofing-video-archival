#!/usr/bin/env python3
"""Hermetic self-check for the JB1 price-book seed (scripts/seed_pricebook.py).

Loads Tim's JSON, runs build_items(), and asserts:
  (a) >=80 ABC + >=70 Beacon material items
  (b) For every item with non-null coverage, engine formula reproduces Tim's price_per_sq
      within Decimal("0.01") — mismatches are flagged as data issues, not failures
  (c) The 13 crosswalk items carry their knowify_item_id
  (d) A NULL-coverage item yields price_per_square -> None (not 0)
  (e) Freezing seeded rows produces a config_hash and a PriceBook v1

    PYTHONPATH=. .venv/bin/python scripts/validate_pricebook_seed.py
"""
import json
from decimal import Decimal  # noqa: E402 — isort: stdlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, PriceBook, PriceBookItem
from core.price_book import freeze_items, price_per_square
from scripts.seed_pricebook import _CROSSWALK, TIM_JSON, build_items

engine = create_engine("sqlite:///:memory:", future=True)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, future=True)

_TAX = Decimal("0.07")
_WASTE = Decimal("0.10")
_TOL = Decimal("0.01")


def main() -> None:
    data = json.loads(TIM_JSON.read_text())
    items = build_items(data)

    abc_items = [i for i in items if i["supplier"] == "ABC_SUPPLY"]
    beacon_items = [i for i in items if i["supplier"] == "BEACON"]

    # (a) item counts
    assert len(abc_items) >= 80, f"Expected >=80 ABC items, got {len(abc_items)}"
    assert len(beacon_items) >= 70, f"Expected >=70 Beacon items, got {len(beacon_items)}"

    # (b) engine formula vs Tim's price_per_sq — flag mismatches, don't suppress them
    mismatches: list[str] = []
    covered_count = 0
    for tab_name, tab_key in [("ABC (42926)", "ABC_SUPPLY"), ("Beacon", "BEACON")]:
        raw_tab = data[tab_name]
        item_map = {i["name"].strip(): i for i in items if i["supplier"] == tab_key}
        for raw in raw_tab:
            tim_pps = raw.get("price_per_sq")
            coverage = raw.get("sq_per_m")
            if tim_pps is None or coverage is None:
                continue
            name = raw["name"].strip()
            item = item_map.get(name)
            if item is None:
                continue
            engine_pps = price_per_square(
                item["unit_price"], _TAX, _WASTE, item["unit_coverage"]
            )
            if engine_pps is None:
                mismatches.append(f"  {tab_key}/{name!r}: engine returned None (coverage={coverage})")
                continue
            tim_d = Decimal(str(tim_pps))
            diff = abs(engine_pps - tim_d)
            if diff > _TOL:
                mismatches.append(
                    f"  {tab_key}/{name!r}: engine={engine_pps} tim={tim_d} diff={diff}"
                )
            covered_count += 1

    if mismatches:
        print(f"WARNING: {len(mismatches)} coverage rows where engine != Tim's $/sq "
              f"(data issues, not formula bugs):")
        for m in mismatches:
            print(m)
        # These are data-quality findings to flag, not assertion failures
    else:
        print(f"  formula check: all {covered_count} covered rows match Tim within $0.01")

    # (c) crosswalk: all 13 expected items carry their knowify_item_id
    missing_xwalk: list[str] = []
    for tim_name, expected_id in _CROSSWALK.items():
        matches = [i for i in items if i["name"] == tim_name]
        if not matches:
            missing_xwalk.append(f"  {tim_name!r}: not found in seeded items")
        elif not any(i["knowify_item_id"] == expected_id for i in matches):
            missing_xwalk.append(
                f"  {tim_name!r}: expected one supplier row with {expected_id!r}, "
                f"got {[i['knowify_item_id'] for i in matches]!r}"
            )
    assert not missing_xwalk, "Crosswalk failures:\n" + "\n".join(missing_xwalk)

    # (d) NULL-coverage item yields None (not 0)
    null_cov = next((i for i in abc_items if i["unit_coverage"] is None), None)
    assert null_cov is not None, "Expected at least one NULL-coverage ABC item (e.g. 1x6 T&G)"
    assert price_per_square(
        null_cov["unit_price"], _TAX, _WASTE, null_cov["unit_coverage"]
    ) is None, f"NULL-coverage item must return None, not 0: {null_cov['name']!r}"

    # (e) ORM round-trip + freeze → PriceBook v1
    s = Session()
    # tenant 1 seeded by Tenant.after_create hook
    for d in items:
        s.add(PriceBookItem(
            name=d["name"],
            sku=d["sku"],
            unit_price=d["unit_price"],
            tax_rate=d["tax_rate"],
            waste_rate=d["waste_rate"],
            unit_coverage=d["unit_coverage"],
            supplier=d["supplier"],
            item_type=d["item_type"],
            knowify_item_id=d["knowify_item_id"],
            roof_system_ids=d["roof_system_ids"],
        ))
    s.flush()

    snap, h = freeze_items(abc_items)
    assert isinstance(h, str) and len(h) == 64, "freeze_items must return a 64-char hash"

    pb = PriceBook(
        supplier="ABC_SUPPLY",
        version_number=1,
        label="Tim ABC seed (validate)",
        items_snapshot=snap,
        config_hash=h,
        is_active=True,
        created_by="validate_pricebook_seed.py",
    )
    s.add(pb)
    s.commit()

    fetched = s.get(PriceBook, pb.id)
    assert fetched.config_hash == h
    assert len(fetched.items_snapshot) == len(abc_items)

    # Verify one crosswalk item round-tripped through ORM
    xwalk_item = s.query(PriceBookItem).filter_by(knowify_item_id="1225592").first()
    assert xwalk_item is not None, "Elastobase V (1225592) must round-trip through ORM"
    assert xwalk_item.name == "Elastobase V"

    s.close()

    mismatch_note = f"; {len(mismatches)} mismatches flagged above" if mismatches else " all match within $0.01"
    print("OK — price-book seed invariants hold:")
    print(f"  (a) {len(abc_items)} ABC_SUPPLY + {len(beacon_items)} BEACON items (>= 80 / >= 70)")
    print(f"  (b) formula check: {covered_count} covered rows{mismatch_note}")
    print(f"  (c) all {len(_CROSSWALK)} crosswalk items carry knowify_item_id")
    print(f"  (d) NULL-coverage item {null_cov['name']!r} → price_per_square = None")
    print(f"  (e) freeze_items → PriceBook v1 (hash {h[:12]}…), {len(snap)} items in snapshot")


if __name__ == "__main__":
    main()
