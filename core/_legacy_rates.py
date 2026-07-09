"""Legacy rate tables and estimate function — TEST-ONLY. Do not import from api/ routes.

The F2 engine uses estimate(config, input). Old tests call estimate(q) with override_*
fields. This module handles the old path so those tests keep passing without modification.

CONSTRAINT: This module must never be imported from api/ routes for live request handling.
All production code paths must use core.pricing_config + core.estimator with an active
PricingConfig. If api/ routes need these constants, migrate them to the config schema
(see TODO(config-migrate) markers). This module will be deleted when old tests are migrated.
"""
from __future__ import annotations

from typing import Optional

# Rate tables — exact copy from pre-F2 estimator.py
BASE_COST_LM = {
    "HVHZ": {"13_tile": 780, "barrel_tile": 1455, "3tab_shingle": 395,
             "dimensional_shingle": 420, "standing_seam_metal": 1020},
    "FBC":  {"13_tile": 770, "barrel_tile": 1435, "3tab_shingle": 395,
             "dimensional_shingle": 420, "standing_seam_metal": 750},
}

OVERHEAD = {
    "HVHZ": {"3tab_shingle": 125, "dimensional_shingle": 125, "13_tile": 270,
             "barrel_tile": 420, "standing_seam_metal": 280},
    "FBC":  {"3tab_shingle": 105, "dimensional_shingle": 105, "13_tile": 185,
             "barrel_tile": 350, "standing_seam_metal": 205},
}

PROFIT_SCALE = [
    (1, 400), (4, 200), (7, 160), (14, 140), (20, 120), (29, 110), (float("inf"), 100),
]

ROOF_HEIGHT: dict[str, Optional[float]] = {
    "1_story": 0, "2_stories": 50, "3_5_stories": None, "6_plus": None,
}
ROOF_HEIGHT_3_5_FLAT_ADD = 1200

ROOF_CUTS = {"low": 0, "medium": 25, "high": 50}
TILE_POINTING = {"no": 0, "yes": 200}

SPECIALTY_TILE_UPGRADE = {
    "HVHZ": {"santa_fe_clay_s": 160, "verea_caribbean_s": 120, "verea_s": 195},
    "FBC":  {"santa_fe_clay_s": 160, "terracottagres_s_rustic": 120, "verea_s": 195},
}

PITCH_7_12_ADD = 200
TILE_DEMO_ADD = 40
METAL_DEMO_ADD = 60
SECONDARY_WATER_BARRIER_ADD = 75
WINTERGUARD_ADD = 140

STUCCO_METAL_PER_LF = 9
PENETRATION_EACH = 75

LINE_ITEMS = {
    "HVHZ": {"blown_in_iso_r19": 135, "turbine_vents": 257.50, "solar_vents": 1339.00},
    "FBC":  {"blown_in_iso_r19": 135, "turbine_vents": 257.50, "solar_vents": 1489.00},
}
RIDGE_VENTS_PER_LF = 9.79

DELIVERY_PLYWOOD_VENTS = 650
NEW_BONUS_VALUES = 1350
PERMIT_PROCESSING = 500
PERMIT_COMMERCIAL_ADD = 500
TILE_DUMPSTER = 300

PM_INCENTIVE = {"residential": 150, "commercial": 300}

PROFIT_FLOOR_PCT = 0.13
PROFIT_PLUS_OH_FLOOR_PCT = 0.33
COMMISSION_PCT = 0.15


def _profit_per_sq(num_squares: float) -> float:
    for max_sq, profit in PROFIT_SCALE:
        if num_squares <= max_sq:
            return profit
    return PROFIT_SCALE[-1][1]  # pragma: no cover


def _is_tile(roof_type: str) -> bool:
    return roof_type in ("13_tile", "barrel_tile")


def _is_metal(roof_type: str) -> bool:
    return roof_type == "standing_seam_metal"


def estimate_legacy(q) -> dict:
    """Full legacy quote build-up — mirrors pre-F2 estimate() exactly."""
    region = q.code_zone
    rt = q.roof_type
    base = q.override_base_cost if q.override_base_cost is not None else BASE_COST_LM[region][rt]
    oh = q.override_overhead if q.override_overhead is not None else OVERHEAD[region][rt]
    profit = q.override_profit_per_sq if q.override_profit_per_sq is not None else _profit_per_sq(q.num_squares)

    per_sq = base + oh + profit
    per_sq += ROOF_CUTS[q.roof_cuts]
    height = ROOF_HEIGHT.get(q.roof_height)
    if height:
        per_sq += height
    per_sq += TILE_POINTING[q.tile_pointing]
    if q.specialty_tile:
        per_sq += SPECIALTY_TILE_UPGRADE[region][q.specialty_tile]
    if q.pitch_7_12 and _is_tile(rt):
        per_sq += PITCH_7_12_ADD
    if q.demo:
        per_sq += METAL_DEMO_ADD if _is_metal(rt) else (TILE_DEMO_ADD if _is_tile(rt) else 0)
    if q.secondary_water_barrier:
        per_sq += SECONDARY_WATER_BARRIER_ADD
    if q.winterguard:
        per_sq += WINTERGUARD_ADD

    squares_subtotal = per_sq * q.num_squares

    fixed = {
        "delivery_plywood_vents": DELIVERY_PLYWOOD_VENTS,
        "new_bonus_values": NEW_BONUS_VALUES,
        "permit_processing": PERMIT_PROCESSING + (PERMIT_COMMERCIAL_ADD if q.project_kind == "commercial" else 0),
    }
    include_dumpster = getattr(q, "include_dumpster", False)
    if include_dumpster and _is_tile(rt):
        fixed["tile_dumpster"] = TILE_DUMPSTER
    if q.roof_height == "3_5_stories":
        fixed["stories_3_5_delivery_chute"] = ROOF_HEIGHT_3_5_FLAT_ADD

    lines: dict[str, float] = {}
    extra_line_items = getattr(q, "extra_line_items", [])
    lines.update({k: LINE_ITEMS[region][k] for k in extra_line_items if k in LINE_ITEMS[region]})
    if q.stucco_metal_lf:
        lines["stucco_metal"] = q.stucco_metal_lf * STUCCO_METAL_PER_LF
    if q.penetrations:
        lines["penetrations"] = q.penetrations * PENETRATION_EACH
    if q.ridge_vent_lf:
        lines["ridge_vents"] = q.ridge_vent_lf * RIDGE_VENTS_PER_LF

    pm_incentive = PM_INCENTIVE.get(q.project_kind, 0)
    project_total = squares_subtotal + sum(fixed.values()) + sum(lines.values()) + pm_incentive

    profit_dollars = profit * q.num_squares
    profit_pct = profit_dollars / project_total if project_total else 0.0

    return {
        "region": region,
        "roof_type": rt,
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
        "margin_ok": profit_pct >= PROFIT_FLOOR_PCT,
        "_stub_notes": [
            "Rate tables transcribed from Sloped Roof Price Calculator workbook (2026-07).",
        ],
    }
