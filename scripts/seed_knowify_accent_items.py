#!/usr/bin/env python3
"""Add the accent items Tim named to `line_items`, priced from his own Knowify catalog.

Tim, 2026-07-27: *"including, like, adding a skylight or a solar vent or, like, doing a chimney,
whatever... I would scrape my notify just because I know it's more updated as far as, like, accent
items."*

`line_items` is a zone-keyed map of flat-price optional add-ons that fire ONLY when a quote names
the key (`core/estimator.py:1091` — `for key in q.extra_line_items: if key in zone_extras`). Adding
a key therefore CANNOT move an existing quote: nothing selects it until someone asks for it.

The convention is already established and prod-verified: `solar_vents` FBC $1,489.00 and
`turbine_vents` $257.50 match Tim's catalog entries "Install Solar Roof Vent (Self-Flashing)" and
"(OPTIONAL) Replace Turbine Roof Vent" TO THE CENT. These four are the same family, taken from the
same catalog, so they follow the same convention.

Source: Perkins Roofing JUPITER (Company 30586 / Tenant 28403), pulled 2026-07-28 over the MCP
after Tim granted admin — his tenant, not Josh's, whose copies of these are $0 placeholders last
touched 2024-10-23.

    (OPTIONAL) Impact Skylight Replacement                    $1,590.00  mod 2026-07-02
    (OPTIONAL) Install Curb Mounted Impact Glass Skylight      $2,860.00  mod 2026-07-02
    (OPTIONAL) Install Solar Roof Vent (Metal Roof)            $2,689.00  mod 2026-02-25
    (OPTIONAL) Chimney Cap Replacement                         $2,393.46  mod 2024-05-13

⚠️ HVHZ IS CARRIED FORWARD FROM FBC, NOT MEASURED. Jupiter is Palm Beach = FBC, so his catalog
prices ARE the FBC numbers. The one existing item that differs by zone goes the counter-intuitive
way (solar_vents FBC $1,489 vs HVHZ $1,339), so there is no rule to extrapolate — Miami has to
state its own. Carrying FBC's number is better than omitting the key, because a missing key is
skipped SILENTLY and the add-on would just vanish from an HVHZ quote. Ask Tim.

NOT CHANGED, deliberately: `ridge_vent_per_lf` is $9.79 here against $12.50/ft on his
"(OPTIONAL) Unfiltered CT Shingle Ridge Vents". That one is an EXISTING price on a different code
path (`core/estimator.py:1032`, qty x rate, cost-tagged), so moving it reprices live quotes and it
is not clear his per-foot retail is our per-foot input. Flagged in
docs/knowify-price-diff-2026-07-28.md, not touched here.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_knowify_accent_items.py [--apply]
"""
from __future__ import annotations

import argparse
import sys

BRANCH_ORDER = ("jupiter", "miami", "naples")

# key -> (price, Knowify catalog item it came from)
ACCENT = {
    "skylight_impact_replacement": (1590.00, "(OPTIONAL) Impact Skylight Replacement"),
    "skylight_curb_mounted_impact": (2860.00, "(OPTIONAL) Install Curb Mounted Impact Glass Skylight (Metal Roof)"),
    "solar_vents_metal_roof": (2689.00, "(OPTIONAL) Install Solar Roof Vent (Metal Roof)"),
    "chimney_cap_replacement": (2393.46, "(OPTIONAL) Chimney Cap Replacement"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (otherwise print and exit)")
    args = ap.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash

    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = [r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()]
    for branch in sorted(branches, key=lambda b: (BRANCH_ORDER + (b,)).index(b)):
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config", file=sys.stderr)
            continue

        before = dict(active.config)
        items = {z: dict(v) for z, v in (before.get("line_items") or {}).items()}
        if not items:
            print(f"{branch}: no line_items map — skipped", file=sys.stderr)
            continue

        added = []
        for zone in items:
            for key, (price, src) in ACCENT.items():
                if key in items[zone]:
                    continue
                items[zone][key] = price
                added.append((zone, key, price, src))
        if not added:
            print(f"{branch}: all accent items already present — skipped")
            continue

        cfg = dict(before)
        cfg["line_items"] = items
        cfg["_note_line_items_accent"] = (
            "skylight_impact_replacement / skylight_curb_mounted_impact / solar_vents_metal_roof / "
            "chimney_cap_replacement added 2026-07-28 from Tim's OWN Knowify catalog (Perkins "
            "Roofing Jupiter, Company 30586), which he asked us to scrape over Josh's: 'I would "
            "scrape my notify... it's more updated as far as, like, accent items' (2026-07-27). "
            "Prices are his FBC (Jupiter = Palm Beach) numbers. HVHZ CARRIES FBC FORWARD and is NOT "
            "measured — the one item that differs by zone goes the other way (solar_vents FBC 1489 "
            "vs HVHZ 1339), so there is no rule to extrapolate. Ask Tim for Miami's. These keys are "
            "inert until a quote names them in extra_line_items, so adding them repriced nothing."
        )

        print(f"\n{branch}: +{len(added)} entries across {len(items)} zones")
        for zone, key, price, src in added:
            print(f"    {zone:<5} {key:<32} ${price:>9,.2f}   <- {src}")

        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1,
            label="Knowify accent items (skylight / solar vent / chimney cap)",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_knowify_accent_items.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"  created + activated v{new.version} (id={new.id})")

    if args.apply:
        s.commit()
    else:
        s.rollback()
        print("\n(dry run — nothing written; pass --apply to commit)")
    s.close()


if __name__ == "__main__":
    main()
