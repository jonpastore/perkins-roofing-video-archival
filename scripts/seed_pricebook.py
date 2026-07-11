#!/usr/bin/env python3
"""JB1 price-book seed from Tim's authoritative material list (ABC 4/29/26).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/seed_pricebook.py --dry-run
    PYTHONPATH=. .venv/bin/python scripts/seed_pricebook.py   # writes to DB (Postgres only)

Tim's sheet columns ARE the engine formula:
    price_per_sq = price * (1 + 0.07) * (1 + 0.10) / sq_per_m

Idempotent: re-running creates a new PriceBook version; never mutates existing rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

TIM_JSON = Path("/tmp/perkins_mail/tim_materials.json")

# Knowify crosswalk: Tim item name -> knowify_item_id
_CROSSWALK: dict[str, str] = {
    '5/8" CDX Plywood': "1227172",
    "Tin Tags": "1225507",
    "Elastobase V": "1225592",
    "SA V": "1223715",
    "SA P": "1223716",
    "SA V FR": "1223713",
    "SA P FR": "1223717",
    "TU Plus (80 mil)": "1227138",
    "TU Max (60 mil)": "1227142",
    "PG 500": "1223704",
    "PG 100 Asphalt Primer": "1225569",
    "Landmark Pro Arch. Shingles": "1227198",
    '1/4" SecuRock': "1225583",
}

_SUPPLIER_MAP = {
    "ABC (42926)": "ABC_SUPPLY",
    "Beacon": "BEACON",
}


def build_items(data: dict) -> list[dict]:
    """Pure function: parse Tim's JSON into PriceBookItem dicts.

    Skips items with price None/0. Deduplicates by (supplier, name) — last wins.

    Knowify crosswalk ids are globally unique in ``price_book_items`` by
    (tenant_id, knowify_item_id). Tim's ABC and Beacon tabs can both include the
    same material name, so both parsed supplier rows may initially map to the same
    Knowify catalog id. Keep the crosswalk on ONE canonical row (prefer ABC_SUPPLY,
    then first-seen) and clear duplicate supplier rows to NULL; the supplier row is
    still seeded, but there is a single canonical Knowify↔price-book crosswalk.
    """
    seen: dict[tuple[str, str], dict] = {}
    for tab, items in data.items():
        supplier = _SUPPLIER_MAP.get(tab, tab)
        for raw in items:
            price = raw.get("price")
            if not price:
                continue
            name = raw["name"].strip()
            coverage = raw.get("sq_per_m")
            item: dict = {
                "name": name,
                "sku": None,
                "unit_price": Decimal(str(price)),
                "tax_rate": Decimal("0.07"),
                "waste_rate": Decimal("0.10"),
                "unit_coverage": Decimal(str(coverage)) if coverage is not None else None,
                "supplier": supplier,
                "item_type": "material",
                "knowify_item_id": _CROSSWALK.get(name),
                "roof_system_ids": [],
            }
            seen[(supplier, name)] = item
    out = list(seen.values())

    # Enforce one non-null knowify_item_id per tenant-safe seed set. Prefer ABC
    # when both suppliers carry the same item name/crosswalk.
    out.sort(key=lambda i: (0 if i["supplier"] == "ABC_SUPPLY" else 1, i["supplier"], i["name"]))
    used_xwalk: set[str] = set()
    for item in out:
        kid = item.get("knowify_item_id")
        if not kid:
            continue
        if kid in used_xwalk:
            item["knowify_item_id"] = None
        else:
            used_xwalk.add(kid)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = json.loads(TIM_JSON.read_text())
    items = build_items(data)

    abc_items = [i for i in items if i["supplier"] == "ABC_SUPPLY"]
    beacon_items = [i for i in items if i["supplier"] == "BEACON"]

    if args.dry_run:
        sample = items[0]
        print(f"dry-run: {len(items)} items total "
              f"({len(abc_items)} ABC_SUPPLY, {len(beacon_items)} BEACON)")
        print(f"  sample: {sample['name']!r}  unit_price={sample['unit_price']}  "
              f"coverage={sample['unit_coverage']}  knowify={sample['knowify_item_id']}")
        crosswalk_hits = [i for i in items if i["knowify_item_id"]]
        print(f"  crosswalk hits: {len(crosswalk_hits)} / {len(_CROSSWALK)} expected")
        return

    # Write path — Postgres only (SQLite is dev/test; no-op there by dialect guard)
    from sqlalchemy import inspect as sa_inspect

    from app.models import PriceBook, PriceBookItem, SessionLocal
    from core.price_book import freeze_items, next_version

    s = SessionLocal()
    if sa_inspect(s.bind).dialect.name == "sqlite":
        print("seed: SQLite detected — skipping write (dev/test only)", file=sys.stderr)
        s.close()
        return

    # Upsert items for tenant 1 (no ON CONFLICT shortcut — SessionLocal is strict;
    # stamp tenant_id manually since we're in a script context, not a request).
    # ponytail: no stamping seam yet for scripts — use platform_scope bypass
    s.info["platform_scope"] = True  # RLS enforcement skipped; rows carry tenant_id=1

    # Insert all items (dedup already done in build_items)
    orm_items = []
    for d in items:
        obj = PriceBookItem(
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
            tenant_id=1,
        )
        s.add(obj)
        orm_items.append(obj)
    s.flush()

    # Freeze and create one PriceBook version per supplier
    for supplier, supplier_items in [("ABC_SUPPLY", abc_items), ("BEACON", beacon_items)]:
        existing = [
            r.version_number
            for r in s.query(PriceBook).filter_by(supplier=supplier, tenant_id=1).all()
        ]
        vnum = next_version(existing)
        snap, h = freeze_items(supplier_items)
        pb = PriceBook(
            supplier=supplier,
            version_number=vnum,
            label=f"Tim's {supplier} price list (ABC 4/29/26 seed)",
            items_snapshot=snap,
            config_hash=h,
            is_active=True,
            created_by="seed_pricebook.py",
            tenant_id=1,
        )
        s.add(pb)

    s.commit()
    s.close()
    print(f"seeded: {len(items)} PriceBookItems + 2 PriceBook versions (ABC_SUPPLY v1, BEACON v1)")


if __name__ == "__main__":
    main()
