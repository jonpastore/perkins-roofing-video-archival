"""Pure roofing-estimate engine — no I/O, deterministic. STUB (Phase-2).

Rebuilds the pricing logic from Tim Perkins' "Sloped Roof Price Calculator" workbook
(Google Sheet, owner tim@perkinsroofing.net) so real quote data can be passed in via the API.
The workbook has two REGION variants:
  - HVHZ  — High-Velocity Hurricane Zone (Miami-Dade + Broward)
  - FBC   — Florida Building Code baseline (Palm Beach / Lee / St. Lucie — Perkins' home counties)

This is a scaffold: rate tables are transcribed from the workbook as of 2026-07. The build-up
functions reproduce its per-square + project-total math. Points that the workbook leaves
ambiguous are marked `# VERIFY` and left as overridable inputs rather than guessed.

Model (1 square = 100 sqft):
    per_sq_total = base_cost_LM + overhead + profit + roof_cuts + roof_height
                   + tile_pointing + specialty_upgrade + pitch/demo adders
    project_total = per_sq_total * num_squares
                    + sum(project_fixed_costs) + sum(line_items) + pm_incentive

`profit` is a per-square SLIDING SCALE keyed to num_squares (economies of scale), NOT a %.
The workbook also back-checks realized margin against floors (profit >= 13%, profit+OH >= 33%).

NOTE — worked-example reconciliation: the sheet's KEY block sums base $430 + OH $115 +
profit $90 = $635/sq and, at 28 sq + fixed costs, yields the sheet's PROJECT TOTAL of $20,280
(see `_selfcheck`). Those KEY numbers are LOWER than the per-type lookup (13" tile base $780,
OH $270) — the KEY block is the editable "enter red cells only" input area, the right-hand
tables are the reference the estimator copies from. So the engine accepts EITHER explicit
per-sq components (to reproduce a hand-built quote) OR a roof_type to look them up. Which base
composition is canonical for automated quotes must be confirmed with Tim before go-live.  # VERIFY
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SQFT_PER_SQUARE = 100

RoofType = str  # "13_tile" | "barrel_tile" | "3tab_shingle" | "dimensional_shingle" | "standing_seam_metal"
Region = str    # "HVHZ" | "FBC"

# --------------------------------------------------------------------------------------
# Rate tables — transcribed from the workbook (HVHZ = "Tim" sheet, FBC = "Palm/Lee/St.Lucie")
# All per-square unless noted. FBC numbers differ from HVHZ where the sheet differs.
# --------------------------------------------------------------------------------------
BASE_COST_LM: dict[Region, dict[RoofType, float]] = {
    "HVHZ": {"13_tile": 780, "barrel_tile": 1455, "3tab_shingle": 395,
             "dimensional_shingle": 420, "standing_seam_metal": 1020},
    "FBC":  {"13_tile": 770, "barrel_tile": 1435, "3tab_shingle": 395,
             "dimensional_shingle": 420, "standing_seam_metal": 750},
}

OVERHEAD: dict[Region, dict[RoofType, float]] = {
    # dimensional_shingle uses the shingle OH charge.
    "HVHZ": {"3tab_shingle": 125, "dimensional_shingle": 125, "13_tile": 270,
             "barrel_tile": 420, "standing_seam_metal": 280},
    "FBC":  {"3tab_shingle": 105, "dimensional_shingle": 105, "13_tile": 185,
             "barrel_tile": 350, "standing_seam_metal": 205},
}

# Profit SLIDING SCALE (per square) by total squares — same tiers both regions.  # VERIFY (FBC copy)
# (max_squares_inclusive, profit_per_sq); last tier is the 30+ catch-all.
PROFIT_SCALE: list[tuple[float, float]] = [
    (1, 400), (4, 200), (7, 160), (14, 140), (20, 120), (29, 110), (float("inf"), 100),
]

ROOF_HEIGHT: dict[str, Optional[float]] = {
    "1_story": 0,             # ground/single story — no height charge (sheet KEY example)
    "2_stories": 50,          # "2 Stories" per sq
    "3_5_stories": None,      # sheet: "-" + min add $1,200 delivery & trash chute (project-level)
    "6_plus": None,           # sheet: "-" (needs a crane) — quote manually
}
ROOF_HEIGHT_3_5_FLAT_ADD = 1200  # delivery + trash chute when 3-5 stories

ROOF_CUTS: dict[str, float] = {"low": 0, "medium": 25, "high": 50}       # per sq
TILE_POINTING: dict[str, float] = {"no": 0, "yes": 200}                  # per sq

SPECIALTY_TILE_UPGRADE: dict[Region, dict[str, float]] = {  # per sq
    "HVHZ": {"santa_fe_clay_s": 160, "verea_caribbean_s": 120, "verea_s": 195},
    "FBC":  {"santa_fe_clay_s": 160, "terracottagres_s_rustic": 120, "verea_s": 195},
}

# Per-square adders (toggle/qty driven)
PITCH_7_12_ADD = 200        # tile, 7/12 pitch or steeper, per sq
TILE_DEMO_ADD = 40          # per sq
METAL_DEMO_ADD = 60         # per sq
SECONDARY_WATER_BARRIER_ADD = 75   # Polyglass XFR 80 mils, per sq
WINTERGUARD_ADD = 140       # CertainTeed WinterGuard, per sq

# Linear/each adders
STUCCO_METAL_PER_LF = 9
PENETRATION_EACH = 75

# Flat "random item" line items
LINE_ITEMS: dict[Region, dict[str, float]] = {
    "HVHZ": {"blown_in_iso_r19": 135, "turbine_vents": 257.50, "solar_vents": 1339.00},
    "FBC":  {"blown_in_iso_r19": 135, "turbine_vents": 257.50, "solar_vents": 1489.00},
}
RIDGE_VENTS_PER_LF = 9.79   # shingle ridge vents (unfiltered)

# Project-level fixed costs
DELIVERY_PLYWOOD_VENTS = 650
NEW_BONUS_VALUES = 1350     # VERIFY — sheet labels this "New Bonus Values"; meaning unclear
PERMIT_PROCESSING = 500
PERMIT_COMMERCIAL_ADD = 500
TILE_DUMPSTER = 300         # applies when tile roof AND squares > 15

PM_INCENTIVE: dict[str, float] = {"residential": 150, "commercial": 300}  # flat, added to TOTAL

# Margin floors the workbook enforces
PROFIT_FLOOR_PCT = 0.13
PROFIT_PLUS_OH_FLOOR_PCT = 0.33
COMMISSION_PCT = 0.15       # estimated commission = 15% of profit dollars


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------
@dataclass
class QuoteInput:
    region: Region                       # "HVHZ" | "FBC"
    roof_type: RoofType
    num_squares: float
    roof_cuts: str = "low"               # low | medium | high
    roof_height: str = "1_story"         # 1_story | 2_stories | 3_5_stories | 6_plus
    tile_pointing: str = "no"            # no | yes
    specialty_tile: Optional[str] = None
    project_kind: str = "residential"    # residential | commercial
    pitch_7_12: bool = False
    demo: bool = False                   # tear-off/demo of existing roof
    secondary_water_barrier: bool = False
    winterguard: bool = False
    stucco_metal_lf: float = 0
    penetrations: int = 0
    extra_line_items: list[str] = field(default_factory=list)  # keys into LINE_ITEMS[region]
    ridge_vent_lf: float = 0
    include_dumpster: bool = False       # sheet lists tile dumpster (>15 sq) as a SEPARATE add,
    #                                      not auto-rolled into PROJECT TOTAL — opt in explicitly.  # VERIFY
    # Explicit overrides — pass these to reproduce a hand-built quote (KEY-block numbers).
    override_base_cost: Optional[float] = None
    override_overhead: Optional[float] = None
    override_profit_per_sq: Optional[float] = None


# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------
def profit_per_sq(num_squares: float) -> float:
    """Per-square profit from the sliding scale (economies of scale)."""
    for max_sq, profit in PROFIT_SCALE:
        if num_squares <= max_sq:
            return profit
    return PROFIT_SCALE[-1][1]  # pragma: no cover  (unreachable: last tier is +inf)


def _is_tile(roof_type: RoofType) -> bool:
    return roof_type in ("13_tile", "barrel_tile")


def _is_metal(roof_type: RoofType) -> bool:
    return roof_type == "standing_seam_metal"


def per_square_total(q: QuoteInput) -> float:
    """Build up the per-square price. Uses explicit overrides when given, else lookup tables."""
    region, rt = q.region, q.roof_type
    base = q.override_base_cost if q.override_base_cost is not None else BASE_COST_LM[region][rt]
    oh = q.override_overhead if q.override_overhead is not None else OVERHEAD[region][rt]
    profit = q.override_profit_per_sq if q.override_profit_per_sq is not None else profit_per_sq(q.num_squares)

    total = base + oh + profit
    total += ROOF_CUTS[q.roof_cuts]
    height = ROOF_HEIGHT.get(q.roof_height)
    if height:
        total += height
    total += TILE_POINTING[q.tile_pointing]
    if q.specialty_tile:
        total += SPECIALTY_TILE_UPGRADE[region][q.specialty_tile]
    if q.pitch_7_12 and _is_tile(rt):
        total += PITCH_7_12_ADD
    if q.demo:
        total += METAL_DEMO_ADD if _is_metal(rt) else (TILE_DEMO_ADD if _is_tile(rt) else 0)
    if q.secondary_water_barrier:
        total += SECONDARY_WATER_BARRIER_ADD
    if q.winterguard:
        total += WINTERGUARD_ADD
    return total


def project_fixed_costs(q: QuoteInput) -> dict[str, float]:
    costs = {
        "delivery_plywood_vents": DELIVERY_PLYWOOD_VENTS,
        "new_bonus_values": NEW_BONUS_VALUES,
        "permit_processing": PERMIT_PROCESSING + (PERMIT_COMMERCIAL_ADD if q.project_kind == "commercial" else 0),
    }
    if q.include_dumpster and _is_tile(q.roof_type):
        costs["tile_dumpster"] = TILE_DUMPSTER
    if q.roof_height == "3_5_stories":
        costs["stories_3_5_delivery_chute"] = ROOF_HEIGHT_3_5_FLAT_ADD
    return costs


def line_item_costs(q: QuoteInput) -> dict[str, float]:
    items = {k: LINE_ITEMS[q.region][k] for k in q.extra_line_items if k in LINE_ITEMS[q.region]}
    if q.stucco_metal_lf:
        items["stucco_metal"] = q.stucco_metal_lf * STUCCO_METAL_PER_LF
    if q.penetrations:
        items["penetrations"] = q.penetrations * PENETRATION_EACH
    if q.ridge_vent_lf:
        items["ridge_vents"] = q.ridge_vent_lf * RIDGE_VENTS_PER_LF
    return items


def estimate(q: QuoteInput) -> dict:
    """Full quote build-up → itemized dict. This is the single entry point the API calls."""
    per_sq = per_square_total(q)
    squares_subtotal = per_sq * q.num_squares
    fixed = project_fixed_costs(q)
    lines = line_item_costs(q)
    pm_incentive = PM_INCENTIVE.get(q.project_kind, 0)

    project_total = squares_subtotal + sum(fixed.values()) + sum(lines.values()) + pm_incentive

    # Margin back-check (profit dollars are per-sq profit × squares).
    profit_component = (q.override_profit_per_sq if q.override_profit_per_sq is not None
                        else profit_per_sq(q.num_squares))
    profit_dollars = profit_component * q.num_squares
    profit_pct = profit_dollars / project_total if project_total else 0.0

    return {
        "region": q.region,
        "roof_type": q.roof_type,
        "num_squares": q.num_squares,
        "per_square_total": round(per_sq, 2),
        "squares_subtotal": round(squares_subtotal, 2),
        "project_fixed_costs": {k: round(v, 2) for k, v in fixed.items()},
        "line_items": {k: round(v, 2) for k, v in lines.items()},
        "pm_incentive": pm_incentive,
        "project_total": round(project_total, 2),
        "profit_dollars": round(profit_dollars, 2),
        "profit_pct": round(profit_pct, 4),
        "estimated_commission": round(profit_dollars * COMMISSION_PCT, 2),
        "margin_ok": profit_pct >= PROFIT_FLOOR_PCT,   # OH floor check needs OH$ — TODO once base split confirmed
        "_stub_notes": [
            "Rate tables transcribed from Sloped Roof Price Calculator workbook (2026-07).",
            "Confirm canonical base-cost composition with Tim (KEY block vs per-type lookup).",
            "profit+OH>=33% floor not yet enforced — needs OH$ breakdown.",
        ],
    }


def _selfcheck() -> None:
    """Reproduce the workbook's own worked example: 28 sq @ $635/sq → PROJECT TOTAL $20,280.

    The KEY block uses base $430 + OH $115 + profit $90 = $635/sq (no cuts/height/pointing),
    plus delivery $650 + new-bonus $1,350 + permit $500 = $20,280. We drive it via overrides
    so the check pins the project-total math, independent of which lookup base is canonical.
    """
    q = QuoteInput(
        region="HVHZ", roof_type="13_tile", num_squares=28,
        override_base_cost=430, override_overhead=115, override_profit_per_sq=90,
        roof_cuts="low", roof_height="1_story", tile_pointing="no",
        project_kind="residential",
    )
    r = estimate(q)
    assert r["per_square_total"] == 635, r["per_square_total"]
    # 28*635=17780 +650+1350+500=20280, +150 PM incentive = 20430.
    # The sheet's "$20,280" is PRE-incentive; incentive is added as a separate PM line.
    assert r["squares_subtotal"] == 17780, r["squares_subtotal"]
    pre_incentive = r["project_total"] - r["pm_incentive"]
    assert pre_incentive == 20280, pre_incentive
    # sliding-scale spot checks
    assert profit_per_sq(1) == 400 and profit_per_sq(3) == 200 and profit_per_sq(30) == 100
    print("estimator self-check OK:", {k: r[k] for k in ("per_square_total", "project_total")})


if __name__ == "__main__":  # pragma: no cover
    _selfcheck()
