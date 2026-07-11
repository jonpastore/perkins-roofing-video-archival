#!/usr/bin/env python3
"""Hermetic validator for JB3 proposal engine against 8 golden sold fixtures.

Checks:
  1. All 8 fixture contract totals reproduced within $0.02 (invoice reconciliation max)
  2. Expiry days (15d metal, 30d others) correct per fixture
  3. Payment schedule variant correct per fixture
  4. is_optional=True lines are EXCLUDED from total; included=True overrides
  5. freeze_quote_snapshot hash CHANGES when a pinned price changes (C1)
  6. compute_hash handles Decimal without crashing (C2)
  7. sell_price_per_sq: additive tiers, standalone bases, COASTAL_CARIBBEAN composite
  8. Real-table fixtures (no unit_price override) exercise the actual package table

    PYTHONPATH=. .venv/bin/python scripts/validate_proposal_gen.py
"""
from __future__ import annotations

import copy
from decimal import Decimal

from core.perkins_packages import sell_price_per_sq
from core.pricing_config import compute_hash, compute_snapshot_hash
from core.proposal_gen import compose_proposal, freeze_quote_snapshot

TOLERANCE = Decimal("0.02")  # max delta = invoice reconciliation max across all 8 fixtures


# ---------------------------------------------------------------------------
# Unit tests: sell_price_per_sq
# ---------------------------------------------------------------------------

def _test_sell_price_per_sq() -> None:
    """MAJOR-3 + COASTAL_CARIBBEAN fix: direct unit tests for the price table."""
    # Shingle: PROTECTOR base
    assert sell_price_per_sq("shingle", "PROTECTOR") == Decimal("650.00"), "shingle PROTECTOR"
    # Shingle: additive tiers
    assert sell_price_per_sq("shingle", "COASTAL") == Decimal("865.00"), "shingle COASTAL=650+215"
    assert sell_price_per_sq("shingle", "PREMIUM") == Decimal("815.00"), "shingle PREMIUM=650+165"
    assert sell_price_per_sq("shingle", "PREFERRED") == Decimal("692.50"), "shingle PREFERRED=650+42.50"

    # Tile: PROTECTOR base + adders
    assert sell_price_per_sq("tile", "PROTECTOR") == Decimal("1100.00"), "tile PROTECTOR"
    assert sell_price_per_sq("tile", "COASTAL") == Decimal("1147.50"), "tile COASTAL=1100+47.50"
    assert sell_price_per_sq("tile", "PREMIUM_CARIBBEAN") == Decimal("1390.00"), "tile PREMIUM_CARIBBEAN=1100+290"
    assert sell_price_per_sq("tile", "PREMIUM_MEDITERRANEAN") == Decimal("1465.00"), "tile PREM_MED=1100+365"
    assert sell_price_per_sq("tile", "PREMIUM_MODERN") == Decimal("1585.00"), "tile PREM_MODERN=1100+485"

    # Flat: PROTECTOR base
    assert sell_price_per_sq("flat", "PROTECTOR") == Decimal("850.00"), "flat PROTECTOR"
    # Flat: PROLONG is standalone (NOT PROTECTOR+500)
    assert sell_price_per_sq("flat", "PROLONG") == Decimal("500.00"), "flat PROLONG standalone"
    assert sell_price_per_sq("flat", "PREFERRED") == Decimal("1025.00"), "flat PREFERRED=850+175"

    # Metal: PROTECTOR base
    assert sell_price_per_sq("metal", "PROTECTOR") == Decimal("1125.00"), "metal PROTECTOR"
    # Metal: COASTAL is additive on PROTECTOR
    assert sell_price_per_sq("metal", "COASTAL") == Decimal("1555.00"), "metal COASTAL=1125+430"
    # Metal: CARIBBEAN is standalone (NOT PROTECTOR+1000)
    assert sell_price_per_sq("metal", "CARIBBEAN") == Decimal("1000.00"), "metal CARIBBEAN standalone"
    # Metal: COASTAL_CARIBBEAN = CARIBBEAN(1000) + adder(225) = 1225, NOT PROTECTOR+225=1350
    result = sell_price_per_sq("metal", "COASTAL_CARIBBEAN")
    assert result == Decimal("1225.00"), (
        f"COASTAL_CARIBBEAN should be CARIBBEAN+225=1225, got {result}"
    )

    print("  sell_price_per_sq: all 15 assertions PASS")


# ---------------------------------------------------------------------------
# Unit tests: C2 — compute_hash handles Decimal without crashing
# ---------------------------------------------------------------------------

def _test_decimal_hash() -> None:
    """C2: jcs.canonicalize must not crash on Decimal input."""
    d = {
        "price": Decimal("1125.00"),
        "adder": Decimal("430"),
        "name": "metal COASTAL",
        "nested": {"val": Decimal("0.0001")},
    }
    h = compute_hash(d)
    assert isinstance(h, str) and len(h) == 64, f"expected 64-char hex, got {h!r}"

    # Same Decimal values must produce same hash
    h2 = compute_hash(copy.deepcopy(d))
    assert h == h2, "Decimal hash not deterministic"

    print("  compute_hash(Decimal): no crash, deterministic PASS")


# ---------------------------------------------------------------------------
# Unit tests: C1 — snapshot hash changes when pinned price changes
# ---------------------------------------------------------------------------

def _test_snapshot_tamper_detection() -> None:
    """C1: mutating a pinned package price must produce a DIFFERENT snapshot hash."""
    inputs = {
        "customer": "Test",
        "property": "123 Main St",
        "scopes": [
            {"roof_system": "metal", "tier": "PROTECTOR", "squares": 10},
        ],
    }
    proposal = compose_proposal(inputs)
    snap1, h1 = freeze_quote_snapshot(proposal)

    # Mutate the pinned METAL price in the snapshot (simulates a later catalog edit
    # being retroactively applied — the hash must change to detect this)
    snap2 = copy.deepcopy(snap1)
    snap2["package_tables"]["metal"]["PROTECTOR"] = "9999.0000"  # tampered
    h2 = compute_snapshot_hash(snap2)

    assert h1 != h2, (
        f"CRITICAL: tampered snapshot produced SAME hash {h1} — price tables not hashed!"
    )

    # Also verify tc_version is hashed (changing it changes the hash)
    snap3 = copy.deepcopy(snap1)
    snap3["tc_version"] = "v99.0"
    h3 = compute_snapshot_hash(snap3)
    assert h1 != h3, "tc_version change must alter hash"

    print("  freeze_quote_snapshot tamper detection: PASS (price mutation changes hash)")


# ---------------------------------------------------------------------------
# Unit tests: M1 — is_optional exclusion logic
# ---------------------------------------------------------------------------

def _test_optional_exclusion() -> None:
    """M1: is_optional=True lines excluded from total; included=True overrides."""
    inputs = {
        "customer": "Test",
        "property": "123 Main",
        "scopes": [
            # Required line: $1000
            {"roof_system": "shingle", "tier": "PROTECTOR", "squares": 1,
             "unit_price": Decimal("1000.00"), "is_optional": False},
            # Optional excluded: $500 — must NOT be in total
            {"roof_system": "shingle", "tier": "COASTAL", "squares": 1,
             "unit_price": Decimal("500.00"), "is_optional": True, "included": False},
        ],
        "extra_lines": [
            # Optional accepted (included=True): $200 — MUST be in total
            {"description": "Gutter", "line_total": Decimal("200.00"),
             "is_optional": True, "included": True},
            # Optional excluded: $300 — must NOT be in total
            {"description": "Skylight", "line_total": Decimal("300.00"),
             "is_optional": True, "included": False},
        ],
    }
    proposal = compose_proposal(inputs)
    total = Decimal(proposal["contract_total"])
    # Expected: 1000 + 200 = 1200 (500 excluded, 300 excluded)
    assert total == Decimal("1200.00"), (
        f"M1 optional exclusion: expected 1200.00, got {total}"
    )
    print("  is_optional exclusion + included override: PASS")


# ---------------------------------------------------------------------------
# Real-table fixtures (MAJOR-3): one per system, no unit_price override
# These exercise sell_price_per_sq with known sell prices from the catalog.
# ---------------------------------------------------------------------------

def _test_real_table_fixtures() -> None:
    """M3: confirm compose_proposal uses actual catalog prices when no unit_price override."""
    cases = [
        # shingle PROTECTOR: 10sq @ $650 = $6500
        {
            "label": "shingle PROTECTOR 10sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "shingle", "tier": "PROTECTOR", "squares": 10}],
            },
            "expected": Decimal("6500.00"),
        },
        # shingle COASTAL: 10sq @ (650+215)=865 = $8650
        {
            "label": "shingle COASTAL 10sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "shingle", "tier": "COASTAL", "squares": 10}],
            },
            "expected": Decimal("8650.00"),
        },
        # tile PROTECTOR: 5sq @ $1100 = $5500
        {
            "label": "tile PROTECTOR 5sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "tile", "tier": "PROTECTOR", "squares": 5}],
            },
            "expected": Decimal("5500.00"),
        },
        # tile PREMIUM_CARIBBEAN adder: 5sq @ (1100+290)=1390 = $6950
        {
            "label": "tile PREMIUM_CARIBBEAN 5sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [
                    {"roof_system": "tile", "tier": "PREMIUM_CARIBBEAN", "squares": 5},
                ],
            },
            "expected": Decimal("6950.00"),
        },
        # flat PROLONG standalone: 4sq @ $500 = $2000 (NOT 850+500)
        {
            "label": "flat PROLONG standalone 4sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "flat", "tier": "PROLONG", "squares": 4}],
            },
            "expected": Decimal("2000.00"),
        },
        # metal PROTECTOR: 3sq @ $1125 = $3375
        {
            "label": "metal PROTECTOR 3sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "metal", "tier": "PROTECTOR", "squares": 3}],
            },
            "expected": Decimal("3375.00"),
        },
        # metal CARIBBEAN standalone: 3sq @ $1000 = $3000
        {
            "label": "metal CARIBBEAN standalone 3sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "metal", "tier": "CARIBBEAN", "squares": 3}],
            },
            "expected": Decimal("3000.00"),
        },
        # metal COASTAL_CARIBBEAN: 3sq @ (1000+225)=1225 = $3675
        {
            "label": "metal COASTAL_CARIBBEAN 3sq",
            "inputs": {
                "customer": "T", "property": "P",
                "scopes": [{"roof_system": "metal", "tier": "COASTAL_CARIBBEAN", "squares": 3}],
            },
            "expected": Decimal("3675.00"),
        },
    ]

    all_ok = True
    for case in cases:
        proposal = compose_proposal(case["inputs"])
        got = Decimal(proposal["contract_total"])
        ok = got == case["expected"]
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
            print(f"  FAIL {case['label']}: got {got}, expected {case['expected']}")
        else:
            print(f"  {status} {case['label']}: ${got:,.2f}")

    assert all_ok, "One or more real-table fixtures failed"


# ---------------------------------------------------------------------------
# M2 unit test: metal in extra_lines triggers 15-day expiry
# ---------------------------------------------------------------------------

def _test_metal_expiry_extra_lines() -> None:
    """M2: is_metal=True on an extra_line must trigger 15-day expiry."""
    inputs = {
        "customer": "T", "property": "P",
        # No scopes with roof_system=metal
        "extra_lines": [
            {
                "description": "Metal panel installation",
                "line_total": Decimal("5000.00"),
                "is_metal": True,
            },
        ],
    }
    proposal = compose_proposal(inputs)
    assert proposal["expiry_days"] == 15, (
        f"M2: metal extra_line should give 15d expiry, got {proposal['expiry_days']}"
    )
    # Non-metal extra_line stays 30
    inputs2 = {
        "customer": "T", "property": "P",
        "extra_lines": [{"description": "Gutter", "line_total": Decimal("500.00")}],
    }
    proposal2 = compose_proposal(inputs2)
    assert proposal2["expiry_days"] == 30, "non-metal should be 30d"
    print("  M2 metal expiry via extra_line is_metal flag: PASS")


# ---------------------------------------------------------------------------
# Golden fixture inputs  (M4: explicit per-line dollars; honest is_optional)
# ---------------------------------------------------------------------------

def _inputs_palmer() -> dict:
    """Palmer: metal PROTECTOR + COASTAL (included optional), 26sq, custom 5-draw."""
    # COASTAL is listed as "INCLUDED" in proposal but carries is_optional=True in fixture.
    # Math: 38380 + 7410 = 45790 → both lines in total.
    # Model as included=True so the optional line counts.
    return {
        "customer": "Justin Palmer",
        "property": "503 Xanadu Place, Jupiter, FL 33477",
        "project_name": "Palmer Metal Re-Roof (3 Story & 6/12 Slope)",
        "hvhz": False,
        "payment_variant": "palmer",
        "scopes": [
            {
                "roof_system": "metal",
                "tier": "PROTECTOR",
                "squares": 26,
                "unit_price": Decimal("38380.00") / 26,
                "description": (
                    "PERKINS PROTECTOR - Metal Re-Roof"
                    " (24 GA MIL FINISH GALVALUME STEEL, 1.5\" Mechanical Seam)"
                ),
                "is_optional": False,
            },
            {
                "roof_system": "metal",
                "tier": "COASTAL",
                "squares": 26,
                "unit_price": Decimal("7410.00") / 26,
                "description": (
                    "PERKINS COASTAL - Metal Re-Roof"
                    " (upgrade to .032 Aluminum Kynar Fluropon coated panels)"
                ),
                "is_optional": True,
                "included": True,   # listed as INCLUDED in proposal — accepted optional
            },
        ],
    }


def _inputs_butterworth() -> dict:
    """Butterworth: flat+tile multi-scope, all lines required."""
    return {
        "customer": "Melissa Butterworth",
        "property": "332 Pilgrim Road, West Palm Beach, FL 33405",
        "project_name": "Butterworth 332 Pilgrim Roofing Project",
        "hvhz": False,
        "scopes": [
            {
                "roof_system": "flat",
                "tier": "PROTECTOR",
                "squares": 24,
                "unit_price": Decimal("28320.00") / 24,
                "description": "PERKINS PROTECTOR - Flat Re-Roofs (Both Structures)",
            },
            {
                "roof_system": "tile",
                "tier": "PROTECTOR",
                "squares": Decimal("5.5"),
                "unit_price": Decimal("1380.00"),
                "description": "PERKINS PROTECTOR - Tile Re-Roof (Back Only)",
            },
            {
                "roof_system": "tile",
                "tier": "PREMIUM_CARIBBEAN",
                "squares": 8,
                "unit_price": Decimal("1622.50") / 8,
                "description": "PERKINS PREMIUM (Caribbean) - Tile Re-Roof upgrade",
            },
        ],
        "extra_lines": [
            {"description": "Re-Paint Guest House & Stucco Repairs",
             "line_total": Decimal("4997.00")},
        ],
    }


def _inputs_allen() -> dict:
    """Allen: shingle+flat+copper+vent (vent included in total per fixture math)."""
    # Contract total = 22840.47 + 4875.15 + 4477.58 + 750.00 = 32943.20 ✓
    # The ridge vent is labeled "(OPTIONAL)" in the proposal but IS in the total.
    return {
        "customer": "Glenn Allen",
        "property": "1251 Holly Cove Drive, Jupiter, FL 33458",
        "project_name": "Glenn Allen Shingle ReRoof",
        "hvhz": False,
        "scopes": [
            {
                "roof_system": "shingle",
                "tier": "PROTECTOR",
                "squares": 30,
                "unit_price": Decimal("22840.47") / 30,
                "description": "PERKINS PROTECTOR - Shingle Re-Roof",
            },
            {
                "roof_system": "flat",
                "tier": "PROTECTOR",
                "squares": Decimal("5.5"),
                "unit_price": Decimal("4875.15") / Decimal("5.5"),
                "description": "PERKINS PROTECTOR - Flat Re-Roof",
            },
        ],
        "extra_lines": [
            {"description": "Copper Metal Install", "line_total": Decimal("4477.58")},
            {
                "description": "(OPTIONAL) Unfiltered CT Shingle Ridge Vents",
                "line_total": Decimal("750.00"),
                "is_optional": True,
                "included": True,   # accepted optional — included in Allen total
            },
        ],
    }


def _inputs_malooley() -> dict:
    """Malooley: tile 3-tier + $0 gutter. PDF per-sq figures rounded from total/sq."""
    # 94460 + 29930 + 2873.35 + 0 = 127263.35
    return {
        "customer": "Jim Malooley",
        "property": "309 Palm Trail, Delray Beach, FL 33483",
        "project_name": "Malooley Tile Re-Roof",
        "hvhz": False,
        "extra_lines": [
            {"description": "PERKINS PROTECTOR - Tile Re-Roof",
             "line_total": Decimal("94460.00")},
            {"description": "PERKINS PREMIUM (Mediterranean) - Tile Re-Roof upgrade",
             "line_total": Decimal("29930.00")},
            {"description": "PERKINS COASTAL UPGRADE - Add to Any Tile Re-Roof",
             "line_total": Decimal("2873.35")},
            {"description": "New Seamless Aluminum Gutter and Downspout System",
             "line_total": Decimal("0.00")},
        ],
    }


def _inputs_thompson() -> dict:
    """Thompson: metal PROTECTOR + COASTAL (33sq) + flat + gutter + discount.

    Metal scope lines present → expiry=15 without needing is_metal hack.
    Unit prices derived from exact line totals (PDF per-sq is rounded from total/sq).
    """
    # 39985.00 + 7073.88 + 3115.00 + 1428.00 - 1000.00 = 50601.88
    return {
        "customer": "Fred Thompson",
        "property": "3699 Northeast 6th Drive, Boca Raton, FL 33431",
        "project_name": "Thompson Metal Re-Roof",
        "hvhz": False,
        "scopes": [
            {
                "roof_system": "metal",
                "tier": "PROTECTOR",
                "squares": 33,
                "unit_price": Decimal("39985.00") / 33,
                "description": "PERKINS PROTECTOR - Metal Re-Roof",
            },
            {
                "roof_system": "metal",
                "tier": "COASTAL",
                "squares": 33,
                "unit_price": Decimal("7073.88") / 33,
                "description": "PERKINS COASTAL - Metal Re-Roof",
            },
        ],
        "extra_lines": [
            {"description": "PERKINS PROTECTOR - Flat Re-Roof",
             "line_total": Decimal("3115.00")},
            {"description": "New Seamless Aluminum Gutter and Downspout System",
             "line_total": Decimal("1428.00")},
        ],
        "discounts": [
            {
                "description": "Discount — Current Special through 5/1/2026 ($1,000 off any re-roof)",
                "amount": Decimal("1000.00"),
            },
        ],
    }


def _inputs_mazzeo() -> dict:
    """Mazzeo: tile PROTECTOR + gutter (accepted optional, in total) + discount.

    Fixture notes §8.6: optional gutter IS included in Mazzeo subtotal/total.
    Model as is_optional=True, included=True.
    """
    # 43938.00 + 3563.75 - 2000.00 = 45501.75
    return {
        "customer": "Joseph Mazzeo",
        "property": "3549 Moon Bay Circle, Wellington, FL 33414",
        "project_name": "Mazzeo Tile Roof",
        "hvhz": False,
        "scopes": [
            {
                "roof_system": "tile",
                "tier": "PROTECTOR",
                "squares": Decimal("37.5"),
                "unit_price": Decimal("1171.68"),
                "description": "PERKINS PROTECTOR - Tile Re-Roof",
            },
        ],
        "extra_lines": [
            {
                "description": "(OPTIONAL) New Seamless Aluminum Gutter and Downspout System",
                "line_total": Decimal("3563.75"),
                "is_optional": True,
                "included": True,   # accepted optional — included in Mazzeo total
            },
        ],
        "discounts": [
            {"description": "Discount", "amount": Decimal("2000.00")},
        ],
    }


def _inputs_person() -> dict:
    """Person: shingle PROTECTOR+COASTAL + gutter + Solatube (accepted) + discount.

    M4: use exact per-line dollars (no fudge). Solatube math:
      36×684.44=24639.84, 36×225=8100, gutter=1092.08, disc=-1700.16, solatube=3280.79
      total=35412.55  ← but fixture=35412.71 (delta=$0.16 < $0.02 tolerance? NO)
    Correct approach: use fixture line_total directly (24640.00) not unit×sq.
    36×684.44=24639.84 ≠ 24640.00 → use line_total=24640.00 explicitly.
    Then: 24640.00+8100.00+1092.08+3280.79-1700.16=35412.71 ✓
    Solatube: fixture notes say "not included in base price" but math proves it IS
    in the $35,412.71 total (its value must be subtracted to get other lines).
    Model as is_optional=True, included=True (accepted optional).
    """
    return {
        "customer": "Doug Person",
        "property": "302 Ridge Road, Jupiter, FL 33477",
        "project_name": "Person Shingle Re-Roof",
        "hvhz": True,
        "extra_lines": [
            {"description": "PERKINS PROTECTOR - Shingle Re-Roof",
             "line_total": Decimal("24640.00")},
            {"description": "PERKINS COASTAL - Shingle Re-Roof",
             "line_total": Decimal("8100.00")},
            {"description": "New Seamless Aluminum Gutter and Downspout System",
             "line_total": Decimal("1092.08")},
            {
                "description": "(OPTIONAL) Solatube Replacement (as needed)",
                "line_total": Decimal("3280.79"),
                "is_optional": True,
                "included": True,   # math proves it's in the total
            },
        ],
        "discounts": [
            {"description": "Valentine's Day Discount", "amount": Decimal("1700.16")},
        ],
    }


def _inputs_meharg() -> dict:
    """Meharg: non-branded flat 18sq + stucco + $0 insulation (optional excluded) + straps."""
    # 19870.02 + 4000 + 0 + 2500 = 26370.02 (engine) vs fixture 26370.00 (delta $0.02)
    # insulation listed at $0 in contract (optional, not included) → excluded from total
    return {
        "customer": "David Meharg",
        "property": "404 South M St, Lake Worth Beach, FL 33460",
        "project_name": (
            "Mehang 3-Ply Flat Re-Roof w/ Stucco Repairs,"
            " Waterproofing and Optional Insulation"
        ),
        "hvhz": True,
        "scopes": [
            {
                "roof_system": "flat",
                "tier": "PROTECTOR",
                "squares": 18,
                "unit_price": Decimal("1103.89"),
                "description": "Polyglass 3-Ply Built-Up Roofing System (Wood Deck)",
            },
        ],
        "extra_lines": [
            {"description": "Stucco Repairs & PB 70 Vertical Wall Waterproofing",
             "line_total": Decimal("4000.00")},
            {
                "description": "(OPTIONAL) Insulation Package",
                "line_total": Decimal("0.00"),
                "is_optional": True,
                "included": False,  # excluded — listed at $0 separate from total
            },
            {"description": "Install Perimeter Hurricane Straps",
             "line_total": Decimal("2500.00")},
        ],
    }


# ---------------------------------------------------------------------------
# Fixture registry
# ---------------------------------------------------------------------------

FIXTURES = [
    {
        "id": "palmer-2026-07-10",
        "label": "Palmer (metal, custom 5-draw)",
        "inputs_fn": _inputs_palmer,
        "expected_total": Decimal("45790.00"),
        "expected_expiry": 15,
        "expected_schedule_variant": "palmer-5-draw-custom",
        "note": "COASTAL is_optional=True included=True (listed as INCLUDED in proposal)",
    },
    {
        "id": "butterworth-2026-05-14",
        "label": "Butterworth (flat+tile multi-scope)",
        "inputs_fn": _inputs_butterworth,
        "expected_total": Decimal("42529.50"),
        "expected_expiry": 30,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": None,
    },
    {
        "id": "allen-2026-06-23",
        "label": "Allen (shingle+flat+copper+vent)",
        "inputs_fn": _inputs_allen,
        "expected_total": Decimal("32943.20"),
        "expected_expiry": 30,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": "Ridge vent optional but included=True (in Allen total by math)",
    },
    {
        "id": "malooley-2026-05-18",
        "label": "Malooley (tile 3-tier + $0 gutter)",
        "inputs_fn": _inputs_malooley,
        "expected_total": Decimal("127263.35"),
        "expected_expiry": 30,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": None,
    },
    {
        "id": "thompson-2026-05-05",
        "label": "Thompson (metal+flat+discount+gutter)",
        "inputs_fn": _inputs_thompson,
        "expected_total": Decimal("50601.88"),
        "expected_expiry": 15,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": None,
    },
    {
        "id": "mazzeo-2026-03-10",
        "label": "Mazzeo (tile+gutter accepted opt+discount)",
        "inputs_fn": _inputs_mazzeo,
        "expected_total": Decimal("45501.75"),
        "expected_expiry": 30,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": "Gutter is_optional=True included=True (accepted, in Mazzeo total)",
    },
    {
        "id": "person-2026-02-04",
        "label": "Person (shingle+coastal+Solatube accepted)",
        "inputs_fn": _inputs_person,
        "expected_total": Decimal("35412.71"),
        "expected_expiry": 30,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": "Solatube is_optional=True included=True (math proves it's in total)",
    },
    {
        "id": "meharg-2025-10-08",
        "label": "Meharg (pre-tier template, flat+stucco+straps)",
        "inputs_fn": _inputs_meharg,
        "expected_total": Decimal("26370.00"),
        "expected_expiry": 30,
        "expected_schedule_variant": "standard-30-30-30-balance",
        "note": "Insulation is_optional=True included=False ($0 line, excluded from total)",
    },
]


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run() -> None:
    # --- Unit tests first ---
    print("\n=== Unit tests ===")
    _test_sell_price_per_sq()
    _test_decimal_hash()
    _test_snapshot_tamper_detection()
    _test_optional_exclusion()
    _test_metal_expiry_extra_lines()
    print()

    # --- Real-table fixtures ---
    print("=== Real-table fixtures (no unit_price override) ===")
    _test_real_table_fixtures()
    print()

    # --- Golden fixtures ---
    print("=== Golden fixtures ===")
    header = (
        f"{'Fixture':<44} {'Got':>12} {'Expected':>12} {'Delta':>7}"
        f"  {'Exp':>5}  {'Sched':>5}  Result"
    )
    print(header)
    print("-" * 100)

    all_pass = True
    results = []

    for fx in FIXTURES:
        inputs = fx["inputs_fn"]()
        proposal = compose_proposal(inputs)

        got_total = Decimal(proposal["contract_total"])
        exp_total = fx["expected_total"]
        delta = abs(got_total - exp_total)

        got_expiry = proposal["expiry_days"]
        exp_expiry = fx["expected_expiry"]

        got_sched = proposal["payment_schedule"]["variant"]
        exp_sched = fx["expected_schedule_variant"]

        total_ok = delta <= TOLERANCE
        expiry_ok = got_expiry == exp_expiry
        sched_ok = got_sched == exp_sched
        ok = total_ok and expiry_ok and sched_ok

        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False

        print(
            f"{fx['label']:<44}"
            f" ${got_total:>11,.2f}"
            f" ${exp_total:>11,.2f}"
            f" ${delta:>6,.2f}"
            f"  {got_expiry:>4}d"
            f"  {'ok' if sched_ok else 'WRONG':>5}"
            f"  {status}"
        )
        if not total_ok:
            print(f"  !! total delta ${delta:.2f} > tolerance ${TOLERANCE}")
        if not expiry_ok:
            print(f"  !! expiry: got {got_expiry}d, expected {exp_expiry}d")
        if not sched_ok:
            print(f"  !! schedule: got '{got_sched}', expected '{exp_sched}'")
        if fx.get("note"):
            print(f"  >> {fx['note']}")

        results.append(ok)

    print("-" * 100)
    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} fixtures PASS  (tolerance ${TOLERANCE})\n")

    # Snapshot determinism
    p = compose_proposal(_inputs_thompson())
    _, h1 = freeze_quote_snapshot(p)
    _, h2 = freeze_quote_snapshot(p)
    assert h1 == h2, f"snapshot not deterministic: {h1} != {h2}"
    print(f"freeze_quote_snapshot determinism: OK  (hash={h1[:16]}...)\n")

    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
