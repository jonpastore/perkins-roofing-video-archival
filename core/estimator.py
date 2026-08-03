"""Pure roofing-estimate engine — no I/O, deterministic. F2.

Public API:
    estimate(config: PricingConfig, input: QuoteInput) -> EstimateResult
    compute_daily_overhead(config, series, num_squares) -> (oh_total, per_sq_oh)
    compute_profit_guidance(config, series, flat_profit=None) -> dict

All rates come from the injected PricingConfig; zero hard-coded constants.
Every line item carries a cost_category tag for floor and grouping math.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from core._legacy_rates import _profit_per_sq as profit_per_sq  # noqa: F401 — re-exported for backward compat
from core.pricing_config import ConfigError, PricingConfig

SQFT_PER_SQUARE = 100

RoofType = str   # "13_tile" | "barrel_tile" | "3tab_shingle" | "dimensional_shingle" | "standing_seam_metal"
Zone = str       # "HVHZ" | "FBC"
SlopeType = str  # "sloped" | "low_slope"


# -------------------------------------------------------------------------
# v2: Day-based overhead
# -------------------------------------------------------------------------
@dataclass
class DailyOverheadSeries:
    """One work series with its day count for the day-based OH mode (v2).

    days must be a positive multiple of 0.5 (half-day increments per spec).
    """
    series: str
    days: float

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError(f"DailyOverheadSeries.days must be positive; got {self.days!r}")
        remainder = round(self.days % 0.5, 10)
        if remainder != 0.0:
            raise ValueError(
                f"DailyOverheadSeries.days must be a multiple of 0.5 (half-day increments); "
                f"got {self.days!r}"
            )


# -------------------------------------------------------------------------
# Exceptions
# -------------------------------------------------------------------------
class QuoteRequiresManualReview(Exception):
    """Raised when job characteristics require a manual quote (e.g. 6+ stories)."""


# -------------------------------------------------------------------------
# v2: Day-based overhead public helpers
# -------------------------------------------------------------------------
def compute_daily_overhead(
    config: PricingConfig,
    series: list[DailyOverheadSeries],
    num_squares: float,
) -> tuple[float, float]:
    """Compute total overhead and per-square overhead from a list of day-series.

    Returns (oh_total, per_sq_oh).
    Raises ConfigError for unknown series names.
    Raises ValueError if num_squares <= 0.
    """
    if num_squares <= 0:
        raise ValueError(f"num_squares must be positive; got {num_squares!r}")

    if config.overhead_basis() == "branch":
        # ONE number for the branch, times the days the job runs. What the crew is doing that day
        # does not change what the office costs to keep open — so no per-activity rate, and
        # office_men / office_oh_basis_reference play no part: that crew-size scaling exists only
        # to reconcile the per-series rates and is dead weight here.
        daily = config.office_daily_overhead()
        if not daily:
            raise ConfigError(
                "overhead_basis is 'branch' but office_daily_overhead is unset for this branch. "
                "Set it to the monthly fixed overhead divided by the working days in a month "
                "(Tim, 2026-07-27: Jupiter $28,000/20 = $1,400; Miami $85,000/20 = $4,250)."
            )
        # The branch burn is per CALENDAR day, not per job-day. When two crews are out, both jobs
        # charging a full day collects the office twice. `concurrent_crews` divides the burn across
        # the jobs that share the day. Default 1.0 = every job owns the day (the conservative
        # floor, and what shipped before this key existed), so an unset config prices identically.
        oh_total = sum(s.days for s in series) * float(daily) / config.concurrent_crews()
        return oh_total, oh_total / num_squares

    rates = config.daily_overhead_rates()
    oh_total = 0.0
    for s in series:
        if s.series not in rates:
            raise ConfigError(
                f"daily_overhead_rates has no entry for series '{s.series}'. "
                "Valid series: " + ", ".join(sorted(rates)) + ". "
                "Add the series to daily_overhead_rates in the pricing config."
            )
        oh_total += s.days * float(rates[s.series])
    per_sq_oh = oh_total / num_squares
    return oh_total, per_sq_oh


# Terms the geometry model may use. Each series carries only the ones that earned their place in
# its own fit, so "eaves" appearing here does not mean every series uses it — measured on Tim's 29
# homes, eaves lifts DEMO from 0.363 to 0.662 leave-one-out (tear-off and haul-away scale with the
# eave line) while making tile and metal slightly worse, so only demo carries an eaves coefficient.
_GEOMETRY_TERMS = ("squares", "hips", "valleys", "ridges", "rakes", "wall_flash", "eaves")
#: The full regressor list. `access` is a MODEL term but deliberately NOT a GEOMETRY term: the
#: has_geometry test below asks "does this quote carry cut measurements?", and a hard-access roof
#: with no cut LFs must still fall back to the squares-only fit rather than evaluate the geometry
#: model with every complexity term at zero (which reads as the simplest possible roof).
#: #436, measured on Tim's 29 homes with the feature set FROZEN and coefficients + steep rule
#: refit inside each fold: geometry only 83% within a day, +access 90% (MAE 0.672 -> 0.586).
_MODEL_TERMS = (*_GEOMETRY_TERMS, "access")

#: roof_height band -> the SMALLEST storey count consistent with it. A band cannot answer "how
#: many storeys", so anything that needs a count (crane threshold, trash-chute sections) takes the
#: floor and says so. Choosing the floor means an unknown never over-bills.
_STOREY_FLOOR = {"1_story": 1, "2_stories": 2, "3_5_stories": 3, "6_plus": 6}


def derive_daily_series(config: PricingConfig, q: "QuoteInput") -> list[DailyOverheadSeries]:
    """Auto-fill labor days per series, preferring the ROOF GEOMETRY model.

    Tim, 2026-07-17 Zoom [10:12]: "two houses that are both 30 squares but one got towers and all
    kinds of crazy shit going on ... this one is going to take two days and the one with all the
    crazy shit going on could take five or six days". Days therefore track COMPLEXITY, not area,
    so when the quote carries RoofR cut measurements we use

        days = intercept + c_sq*SQ + c_hips*hips_lf + c_valleys*valleys_lf
                         + c_ridges*ridges_lf + c_rakes*rakes_lf + c_wall*wall_flashing_lf

    fitted per series over his 30-home log with non-negative coefficients (see
    scripts/fit_days_from_roofr.py; leave-one-out R2 tile 0.82, metal 0.90, demo 0.69,
    shingle 0.53 — versus 0.64/0.63/0.30/0.30 for squares alone).

    Falls back to the squares-only `setup + rate x SQ` fit when the quote has no cut measurements
    or the branch config carries no geometry model. Both live in
    config["daily_overhead_day_model"] so they stay tunable without a code change.

    A tear-off adds the demo series on top of the install series (summed when both resolve to the
    same series). Days round to the nearest 0.5 the DailyOverheadSeries contract requires.

    Returns [] when the roof type has no fitted model (low-slope systems, unconfigured
    branches) — the caller then keeps the per-square overhead it would have used anyway.
    """
    model = config.daily_overhead_day_model()
    fits = model.get("series") or {}
    geometry = model.get("geometry_model") or {}
    rates = config.daily_overhead_rates()
    if q.num_squares <= 0 or (not fits and not geometry):
        return []

    geom_inputs = {
        "squares": q.num_squares, "hips": q.hips_lf, "valleys": q.valleys_lf,
        "ridges": q.ridges_lf, "rakes": q.rakes_lf, "wall_flash": q.wall_flashings_lf,
        "eaves": q.eaves_lf,
        # Tim, 2026-07-27: "if there's a back roof that has very poor access ... you're going to
        # work slower". Fitted per series — tile +0.75 d, demo +0.51, metal +0.34, shingle +0.23,
        # which orders exactly by how much material has to be carried.
        "access": 1.0 if q.access_difficult else 0.0,
    }
    # Geometry only applies when the quote actually carries cut measurements; squares alone
    # would silently evaluate the geometry model with every complexity term at zero, which
    # reads as "the simplest possible roof" and under-quotes the days.
    has_geometry = any(geom_inputs[t] for t in _GEOMETRY_TERMS if t != "squares")

    def days_for(name: str) -> Optional[float]:
        if name not in rates:
            return None
        coef = geometry.get(name)
        # A series whose fit leans on ONE measurement is worthless without it: demo is
        # 1.11 + 0.006*eaves, so a quote missing eaves_lf silently returns ~1.1 days instead of
        # 2-5 and under-bills the tear-off. "requires" names the inputs that must be present, and
        # the squares-only fit takes over when they are not.
        needed = (coef or {}).get("requires") or []
        if coef and any(not geom_inputs.get(t) for t in needed):
            coef = None
        if has_geometry and coef:
            raw = float(coef.get("intercept", 0.0)) + sum(
                float(coef.get(term, 0.0) or 0.0) * float(geom_inputs[term])
                for term in _MODEL_TERMS)
        else:
            fit = fits.get(name)
            if not fit:
                return None
            raw = float(fit["setup"]) + float(fit["rate"]) * q.num_squares
        return max(0.5, round(raw * 2) / 2)

    # ponytail: one demo fit for every tear-off type — Tim's sheet logs Demo as a single
    # column. Split per existing_roof when he logs tile vs shingle tear-off apart.
    has_tear_off = q.demo if q.existing_roof is None else q.existing_roof != "none"
    demo_series = model.get("demo_series")
    install_series = (model.get("install_series_by_roof_type") or {}).get(q.roof_type)

    # No fitted INSTALL model → derive nothing. Demo days alone would replace the per-square
    # overhead with a fraction of it, quoting the job under cost.
    install_days = days_for(install_series) if install_series else None
    if install_days is None:
        return []

    # Steep-roof day adder. Measured on Tim's 29 homes, the leftover error after the geometry
    # model tracks pitch monotonically: -0.29 days at <=4/12, +0.03 at 5/12, +0.64 at >=6/12
    # (he books more time than we predict on steep roofs). Tim already prices steepness on the
    # material side ($305/sq for 7/12 tile); this is the same idea on the time side.
    # Deliberately a THRESHOLD RULE, not a fitted coefficient: with only 7 steep homes, adding
    # pitch as a 7th regressor made every install series worse out-of-sample (tile 0.825 -> 0.778)
    # while this rule takes the library from 86% to 93% of homes within a day of Tim and moves the
    # bias from -0.10 to +0.02. Config-driven so it can be retuned or removed without a deploy.
    adder = model.get("pitch_day_adder") or {}
    if adder and q.pitch_primary and float(q.pitch_primary) >= float(adder.get("threshold", 99)):
        install_days = max(0.5, round((install_days + float(adder.get("days", 0))) * 2) / 2)

    totals: dict[str, float] = {install_series: install_days}
    if has_tear_off and demo_series:
        demo_days = days_for(demo_series)
        if demo_days is not None:
            totals[demo_series] = totals.get(demo_series, 0.0) + demo_days
    return [DailyOverheadSeries(series=n, days=d) for n, d in totals.items()]


def compute_profit_guidance(
    config: PricingConfig,
    series: list[DailyOverheadSeries],
    flat_profit: Optional[float] = None,
) -> dict[str, Any]:
    """Compute profit guidance fields for the flat-dollar profit mode (v2).

    When series is non-empty:
        on_site_weeks = max(1, ceil(total_days / profit_floor_days_per_week)) — 5-day week.
        effective_floor = max(job_profit_floor, on_site_weeks × weekly_profit_floor).
        implied_weekly_profit returned when flat_profit is supplied.

    When series is empty (flat profit mode without daily OH):
        on_site_weeks = None; effective_floor = job_profit_floor (absolute floor only).
        implied_weekly_profit is omitted.

    Returns a dict with: total_series_days, on_site_weeks, weekly_floor,
    profit_floor_guidance, absolute_floor, effective_floor, and optionally
    implied_weekly_profit.
    """
    absolute_floor = config.job_profit_floor()
    weekly_floor = config.weekly_profit_floor()

    if not series:
        return {
            "total_series_days": 0.0,
            "on_site_weeks": None,
            "weekly_floor": weekly_floor,
            "profit_floor_guidance": None,
            "absolute_floor": absolute_floor,
            "effective_floor": absolute_floor,
        }

    total_days = sum(s.days for s in series)
    rounding = config.daily_oh_weeks_rounding()
    # Days per working week — 5, config-driven. Not an assumption any more: Tim's 2026-07-10
    # email works the arithmetic himself — "7 days of work ... I would charge closer to $5,000 at
    # a min. for profit, because it's still taking up 2 weeks" — and ceil(7/5) = 2. His Miramar
    # commercial calculator also states "5 days per week" twice. An earlier pass moved this to 6
    # to stop over-counting weeks; the real fix was the basis, not the divisor.
    per_week = config.profit_floor_days_per_week()
    if rounding == "floor":
        on_site_weeks = max(1, math.floor(total_days / per_week))
    else:
        # Tim, 2026-07-17 Zoom [08:52]: "i like to make 2500 bucks a week that we're on the job
        # ... and if it's one day it still counts as one week and i'm still gonna charge 2500
        # bucks minimum on re-roofs". A one-day job is one week, so never round down to zero.
        on_site_weeks = max(1, math.ceil(total_days / per_week))

    weekly_guidance = on_site_weeks * weekly_floor
    effective_floor = max(absolute_floor, weekly_guidance)

    result: dict[str, Any] = {
        "total_series_days": total_days,
        "on_site_weeks": on_site_weeks,
        "weekly_floor": weekly_floor,
        "profit_floor_guidance": weekly_guidance,
        "absolute_floor": absolute_floor,
        "effective_floor": effective_floor,
    }
    if flat_profit is not None:
        result["implied_weekly_profit"] = flat_profit / on_site_weeks
    return result


@dataclass
class RepairInput:
    """Inputs for a time-based repair/maintenance quote — an alternative to a full
    replacement estimate. "Repair" and "Maintenance" are the SAME calculation, one path
    (Tim/Jon, 2026-07-27: overruled a proposed 3-way split) — this is a label only.

    Simple calculation (Tim, Zoom 2026-07-20 [37:04]/[38:05]/[45:31]), now with profit
    added on top (Jarvis #434 — Tim, 2026-07-27 call: "That's the cost, though. That's
    without profit, right? ... we'll add a profit slider into that"):
        cost = labor_cost + material_cost, where labor_cost = days * daily_labor_rate(crew_size)
        profit = max(percent_profit_pct * cost, repair.min_profit_dollars)
        project_total = max(cost + profit, repair.min_service_call_dollars)
    """
    roof_type: str          # "shingle" | "tile" | "metal" | "flat" — validated against config.repair_roof_types()
    days: float
    crew_size: int = 1      # 1 (one-man rate) or 2 (two-man rate)
    material_cost: float = 0.0
    # Same mechanism and fraction convention as QuoteInput.percent_profit_pct (Jarvis #432,
    # commit 78f3557) — "let's not have duplicate mechanisms" (Tim, 2026-07-27). 0.20 = 20%.
    # None/omitted is treated as 0.0: the pct term drops out but the min_profit_dollars and
    # min_service_call_dollars floors below still apply — Tim wants those on every repair,
    # not opt-in ("what is the minimum profit ... we have a minimum of a $500 charge").
    percent_profit_pct: Optional[float] = None

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError(f"RepairInput.days must be positive; got {self.days!r}")
        if self.crew_size not in (1, 2):
            raise ValueError(f"RepairInput.crew_size must be 1 or 2; got {self.crew_size!r}")
        if self.material_cost < 0:
            raise ValueError(f"RepairInput.material_cost must be >= 0; got {self.material_cost!r}")
        if self.percent_profit_pct is not None and self.percent_profit_pct < 0:
            raise ValueError(
                f"RepairInput.percent_profit_pct must be >= 0; got {self.percent_profit_pct!r}"
            )


def estimate_repair(config: PricingConfig, r: RepairInput) -> dict[str, Any]:
    """Compute a time-based repair/maintenance quote: cost + profit, both floored.

    cost = days x daily labor rate + material cost
    profit = max(percent_profit_pct x cost, repair.min_profit_dollars)
    project_total = max(cost + profit, repair.min_service_call_dollars)

    NOTE this is a behavior change (Jarvis #434): every repair quote now carries at least
    repair.min_profit_dollars of profit and a repair.min_service_call_dollars floor on the
    total, even when percent_profit_pct is omitted — the engine previously returned pure
    cost with zero profit, which is the defect Tim caught live on the 2026-07-27 call.

    Raises ConfigError when roof_type isn't a configured repair category, or when the
    daily labor rate for the requested crew size is missing from the config.
    """
    valid_types = config.repair_roof_types()
    if r.roof_type not in valid_types:
        raise ConfigError(
            f"repair.roof_types has no entry for {r.roof_type!r}. "
            f"Valid: {sorted(valid_types)}"
        )
    rate = config.repair_daily_labor_rate(r.crew_size)
    labor_cost = r.days * rate
    cost = labor_cost + r.material_cost

    pct = r.percent_profit_pct or 0.0
    pct_profit = pct * cost
    min_profit = config.repair_min_profit_dollars()
    profit = max(pct_profit, min_profit)

    pre_floor_total = cost + profit
    min_service_call = config.repair_min_service_call_dollars()
    project_total = max(pre_floor_total, min_service_call)

    warnings: list[str] = []
    if pct_profit < min_profit:
        warnings.append(
            f"repair_min_profit_applied: profit raised from ${pct_profit:,.2f} to "
            f"${min_profit:,.2f} (repair minimum profit)"
        )
    if pre_floor_total < min_service_call:
        warnings.append(
            f"repair_min_service_call_applied: total raised from ${pre_floor_total:,.2f} to "
            f"${min_service_call:,.2f} (minimum service call)"
        )

    return {
        "roof_type": r.roof_type,
        "days": r.days,
        "crew_size": r.crew_size,
        "daily_labor_rate": rate,
        "labor_cost": round(labor_cost, 2),
        "material_cost": round(r.material_cost, 2),
        "repair_cost": round(cost, 2),
        "percent_profit_pct": pct,
        "profit_dollars": round(profit, 2),
        "project_total": round(project_total, 2),
        "warnings": warnings,
    }


def compute_cut_adjusted_base(
    config: PricingConfig, q: "QuoteInput", zone: str, roof_type: str,
) -> Optional[float]:
    """Geometry-adjusted base $/sq from RoofR cut LFs (Tim's Custom Tile Calc, decoded 2026-07-17).

    Returns None — and the caller falls back to the flat sloped_base — when the calc does not
    apply: no cuts_calc in the config, no cut measurements, num_squares <= 0, or the zone has no
    calibrated fixed block (e.g. HVHZ, which needs its own base detail).

    13" tile is computed directly from the geometry (round each cut LF UP to material-piece
    lengths, then price the metal/tile lines). Other roof types scale their flat base by the tile
    custom/standard ratio — Tim's "one calculator, same % difference" rule (Zoom [05:33]).
    See docs/plans/2026-07-17-cut-calculator-spec.md for the full derivation.
    """
    cc = config.cuts_calc()
    if not cc or not q.has_cut_measurements() or q.num_squares <= 0:
        return None
    fixed = (cc.get("fixed_per_sq") or {}).get(zone)
    if fixed is None:
        return None
    r, co = cc["rounding"], cc["coeff"]
    # Base tile brand selects the field/rake tile cost (Eagle default); falls back to the
    # single standard_tile block for configs that predate tile_brands.
    st = (cc.get("tile_brands") or {}).get(q.base_tile_brand) or cc["standard_tile"]

    def _ceil(x: Any, m: float) -> float:
        x = float(x or 0)
        return math.ceil(x / m) * m if x > 0 else 0.0

    eaves_r = _ceil(q.eaves_lf, r["eaves"])
    hipridge_r = _ceil((q.hips_lf or 0) + (q.ridges_lf or 0), r["hips_ridges"])
    valleys_r = _ceil(q.valleys_lf, r["valleys"])
    rakes_r = _ceil(q.rakes_lf, r["rakes"])
    wall_r = _ceil(q.wall_flashings_lf, r["wall_flashings"])
    sq = float(q.num_squares)

    # Some brands (e.g. newly-added Verea/Other rows) may have a confirmed rake unit but no
    # field-tile cost yet — raise a clear ConfigError instead of a bare TypeError on None + int.
    field_cost = st.get("field")
    if field_cost is None:
        raise ConfigError(
            f"cuts_calc.tile_brands[{q.base_tile_brand!r}] has no 'field' cost — "
            "Tim must confirm the field-tile price before this brand can drive the cut calculator."
        )

    drip = ((eaves_r + rakes_r) * co["drip_a"]
            + (eaves_r + rakes_r + wall_r) * co["drip_b"]) / sq
    valley = ((valleys_r / co["valley_a_div"]) * co["valley_a_rate"]
              + (valleys_r / co["valley_b_div"]) * co["valley_b_rate"]) / sq
    field = field_cost + co["field_tiles_addon"]
    hipridge = (hipridge_r * co["hipridge_tile_rate"]
                + (rakes_r + hipridge_r) * st["rake"]) / sq
    eave = (eaves_r * co["eave_closure_rate"]) / sq
    tile_base = float(fixed) + drip + valley + field + hipridge + eave

    if roof_type == "13_tile":
        return tile_base
    std_tile = config.sloped_base(zone, "13_tile")
    if not std_tile:
        return None
    return config.sloped_base(zone, roof_type) * (tile_base / std_tile)


# -------------------------------------------------------------------------
# Input / Output dataclasses
# -------------------------------------------------------------------------
@dataclass
class QuoteInput:
    """All inputs for a single estimate. No DB references — pure value object.

    F2 callers use code_zone. Legacy callers may pass region= (deprecated alias).
    Either code_zone or region must be provided; code_zone takes precedence when both set.
    """
    roof_type: RoofType
    num_squares: float
    code_zone: Optional[Zone] = None      # "HVHZ" | "FBC" — preferred field name (F2)
    slope_type: SlopeType = "sloped"      # "sloped" | "low_slope"
    county: Optional[str] = None          # "miami_dade" | "broward" | "palm_beach" | "lee" | "st_lucie"
    # A roof with both a sloped and a flat section is one job, not two. Tim's own sheet has a
    # "Squares (Flat)" column alongside the sloped one and prices them together.
    flat_squares: float = 0.0
    flat_roof_type: Optional[str] = None   # a low_slope.base_cost_lm key, e.g. polyglass_sav_sap
    roof_cuts: str = "low"               # low | medium | high (the guide)
    roof_cuts_per_sq: Optional[float] = None   # explicit $/sq; overrides the categorical pick
    # Accessibility, Tim's email 2026-07-27 20:36: "just manual inputs for additional labor and
    # delivery. There isn't a set price, it all depends on SF in the area and what the delivery
    # company or subs will charge for handloading and/or hand-demo." So it is a MANUAL dollar
    # figure, never a tier. The PER-SQUARE half already existed as roof_cuts_per_sq (his own
    # worked example: $45/sq to hand-load a rear roof a truck cannot reach). This is the other
    # half — a flat quoted charge from the delivery company or sub, which no per-sq rate expresses.
    accessibility_flat: Optional[float] = None
    # Waterfront/salinity gate for the COASTAL tier (his email 20:24). The tier itself already
    # exists on tile, shingle AND metal in core/perkins_packages.py; what was missing is anything
    # that says WHEN to reach for it.
    waterfront: bool = False
    roof_height: str = "1_story"         # 1_story | 2_stories | 3_5_stories | 6_plus
    #: Poor access to some part of the roof — a back slope the truck cannot reach, a tight lot.
    #: Feeds the DAY model only (never a price adder; accessibility_flat is the money field).
    #: The single feature that moved the day model most in #436.
    access_difficult: bool = False
    tile_pointing: str = "no"            # no | yes
    specialty_tile: Optional[str] = None
    project_kind: str = "residential"    # residential | commercial
    pitch_7_12: bool = False
    demo: bool = False
    # What's being torn OFF (Zoom 2026-07-17 [13:03-14:46]): demo cost follows the EXISTING
    # roof, not the new one (tile demo ≫ shingle). None = legacy callers (demo bool + new
    # roof_type decide, preserving old behavior); "none" = new construction (no demo).
    existing_roof: Optional[str] = None  # none | shingle | tile | metal | flat
    secondary_water_barrier: bool = False
    winterguard: bool = False
    stucco_metal_lf: float = 0
    penetrations: int = 0
    extra_line_items: list[str] = field(default_factory=list)
    ridge_vent_lf: float = 0
    layers_to_remove: int = 0
    deck_type: Optional[str] = None
    include_insulation: bool = False
    insulation_thickness: str = "1in"    # 1in | 1_5in | 2in — Tim prices board by thickness
    include_tapered: bool = False
    #: Pressure cleaning as an add-on (sheet O1/O2: $30/sq flat, $40/sq sloped). Applies to BOTH
    #: roof kinds — the rates live under low_slope only because that is the sheet block they were
    #: transcribed from. Off by default: it is a line Tim adds, not one every job carries.
    include_pressure_cleaning: bool = False
    #: Polyglass warranty upgrade key (see low_slope.polyglass_warranty_upgrades) — 20/25/30-year
    #: systems, priced as a per-square adder over the base. None = the base warranty.
    warranty_upgrade: Optional[str] = None
    #: Actual storey count. roof_height is a BAND ("3_5_stories"), which cannot answer "how many
    #: trash-chute sections". None = fall back to the band's floor and say so in a warning.
    stories: Optional[int] = None
    #: Silicone add-on keys (see low_slope.silicone_addons) — granules, traffic coat, TPO primer.
    silicone_addons: list[str] = field(default_factory=list)
    #: Extra silicone coats beyond the quoted system. Priced at L27's $100/sq (L, OH & P) PLUS
    #: `extra_coat_material_per_sq`, which the caller must supply — see silicone_extra_coat_lop
    #: for why the material half cannot be a constant.
    extra_coats: int = 0
    extra_coat_material_per_sq: Optional[float] = None
    #: Detail-item key -> quantity, in the sheet's own unit (each / 10' piece / square / LF).
    #: See low_slope.detail_items.
    detail_items: dict[str, float] = field(default_factory=dict)
    # Plywood deck replacement — Tim's Lumber Schedule prices this per SHEET, not per square,
    # and it applies to ANY roof type (his golden proposal attaching it is a TILE re-roof), so
    # it is a fixed item, not a low_slope.deck_types entry (OI-5). The first
    # plywood_replacement.sheets_included sheets are free per his proposal scope language.
    plywood_sheets: float = 0
    plywood_thickness: str = "5_8in"     # 5_8in | 1_2in | 3_4in

    # RoofR cut linear-footages — drive Tim's custom cut calculator. When any is set and the
    # config carries cuts_calc for the zone, the base_cost line is recomputed from the geometry
    # instead of the flat sloped_base (Zoom 2026-07-17; docs/plans/2026-07-17-cut-calculator-spec.md).
    eaves_lf: float = 0
    hips_lf: float = 0
    ridges_lf: float = 0
    valleys_lf: float = 0
    rakes_lf: float = 0
    wall_flashings_lf: float = 0
    base_tile_brand: Optional[str] = None  # key into cuts_calc.tile_brands; None = config default
    # Cut LFs have TWO independent uses: they can recompute the base from geometry (the cut
    # calculator) and they drive the geometry day model. The headline quote wants the second
    # without the first — Tim prices standard roofs off the flat base but his DAYS still track
    # how cut-up the roof is. Set False to feed cuts to the day model only.
    apply_cut_calc_to_base: bool = True
    # Predominant pitch as rise-per-12 from the RoofR report (5.0 = 5/12). Distinct from the
    # pitch_7_12 flag, which drives Tim's $305/sq tile MATERIAL adder — this one feeds the
    # steep-roof day adder, because a steep roof takes longer to walk regardless of material.
    pitch_primary: Optional[float] = None
    # Estimate-debug: return the formula, variables and values behind every priced line, plus
    # the section roll-ups, so a quote can be audited rather than trusted. Admin-gated.
    debug: bool = False

    # Gutters — Tim's style-based price list (email 2026-07-17): per-LF price includes the
    # matching downspouts; 2-story is a per-LF uplift; elbows/leaf guards/leaderheads/removal
    # are separate. Rates live in config["gutters"]; missing/null rates raise ConfigError only
    # when a quote actually uses them.
    gutter_style: Optional[str] = None   # key into config["gutters"]["styles"], e.g. "k6_alum"
    gutter_lf: float = 0
    gutter_two_story: bool = False
    gutter_elbows: int = 0
    gutter_removal_lf: float = 0
    downspout_lf: float = 0              # 4x5 downspout, per-LF, itemized SEPARATELY from the
                                         # gutter per-LF rate (which historically bundled downspouts)
    leaf_guard: str = "none"             # none | std | upgraded
    leaderheads_res: int = 0
    leaderheads_comm: int = 0

    # v2: Day-based overhead mode
    # NOTE: the dataclass default stays per_sq while the API default is "daily". Deliberate, and
    # ugly. Flipping this too reprices the golden regression fixtures, which pin totals computed
    # under per_sq — they are the baseline, so they must not move underneath a mode change. The
    # divergence is tracked against the open question of whether "daily" should be the default at
    # all: it reproduces Tim's stated METHOD but quotes ~10% under his actual SOLD prices, where
    # per_sq is within 0.8%. Resolve the mode question first, then make the two agree.
    overhead_mode: str = "per_sq"        # "per_sq" | "daily" (the API defaults to daily)
    daily_series: list[DailyOverheadSeries] = field(default_factory=list)

    # v2: Profit mode
    # "scale" is LEGACY as of 2026-07-27 (Tim, Jarvis #432 call): "that profit thing per square
    # is like an old thing that I used to use before I really nailed it down ... I would just
    # eliminate it for simplification ... you have the profit sliding scale on there now, so if
    # we are using the days to figure overhead ... we can just use the slider for profit
    # percentage with a minimum 2,500". profit_scale / config.profit_per_sq() stay wired ONLY so
    # a stored old-proposal snapshot still re-renders its original number — new quoting should
    # use "percent" instead. "flat" is an operator-typed dollar amount (unaffected by this call).
    profit_mode: str = "scale"           # "scale" (default; legacy scale table) | "flat" | "percent"
    flat_profit_dollars: Optional[float] = None   # used when profit_mode="flat"
    percent_profit_pct: Optional[float] = None    # used when profit_mode="percent"; a fraction
    # Operator "Min $" from the Quoting slider. Raises the config profit floor for this job only.
    min_profit_dollars: Optional[float] = None
                                                   # of eligible_base, e.g. 0.20 for 20% — NOT 20

    # Commission lever: basis = "profit" (% of profit dollars) or "job" (% of project total).
    # commission_rate_override is a fraction (e.g. 0.30); None falls back to the config rate.
    commission_basis: str = "profit"
    commission_rate_override: Optional[float] = None

    # --- multi-building bids (#430/#449) --------------------------------------------------
    # A building inside a BID PROJECT is not a standalone job, and two things that are correct
    # once per job become wrong once per building. Both default to the single-job behaviour, so
    # an ordinary quote is bit-for-bit unchanged; only core.bid_project sets them.
    #
    # profit_floor_scope="project": this building does NOT pay its own floor — the roll-up owns
    #   one floor for the whole bid. Guidance is still computed and returned, so the per-building
    #   card can say what it WOULD have been floored to standalone.
    # suppress_fixed_keys: fixed fees the project charges once and adds itself. Suppressed on
    #   EVERY building and re-added by the roll-up, which is what lets the dumpster count be
    #   recomputed over the summed squares instead of rounding up once per building.
    profit_floor_scope: str = "job"                  # "job" | "project"
    suppress_fixed_keys: frozenset[str] = frozenset()

    # Legacy override fields — preserved for old "KEY block" tests using explicit per-sq values.
    override_base_cost: Optional[float] = None
    override_overhead: Optional[float] = None
    override_profit_per_sq: Optional[float] = None

    # Legacy field aliases for old tests
    region: Optional[Zone] = None         # deprecated alias for code_zone
    include_dumpster: bool = False        # deprecated: dumpster is now automatic for tile roofs

    def __post_init__(self) -> None:
        # Resolve code_zone from region when code_zone not explicitly set
        if self.code_zone is None:
            if self.region is not None:
                self.code_zone = self.region
            else:
                raise ValueError("Either code_zone or region must be provided.")
        # Keep region in sync for legacy callers that read it back
        if self.region is None:
            self.region = self.code_zone

    def has_cut_measurements(self) -> bool:
        """True when any RoofR cut LF is provided (triggers the cut calculator)."""
        return any((
            self.eaves_lf, self.hips_lf, self.ridges_lf,
            self.valleys_lf, self.rakes_lf, self.wall_flashings_lf,
        ))


@dataclass
class LineItem:
    key: str
    label: str
    amount: float
    category: str       # "Labor" | "Materials" | "Equipment" | "Sub" | "Misc" | "OH" | "Profit"
    per_sq: Optional[float] = None
    floor_excluded: list[str] = field(default_factory=list)  # categories excluded from floor denom
    # How this number was reached: {"formula": str, "inputs": {name: value}}. Set it only where
    # the arithmetic is NOT the usual per_sq x squares — _explain() derives that shape for free,
    # so annotating every call site would be noise.
    explain: Optional[dict] = None


def _explain(li: "LineItem", sq: float) -> dict:
    """Show the caller how a line item got its number: formula, variables, values, result.

    Most items are a rate times the roof area, so that is derived rather than hand-written at
    each construction site. Anything with genuinely different arithmetic (overhead from days,
    profit off the sliding scale, commission, dumpster counts) attaches its own `explain`.
    """
    if li.explain:
        return {**li.explain, "result": round(li.amount, 2)}
    if li.per_sq is not None:
        return {
            "formula": "per_sq x squares",
            "inputs": {"per_sq": round(li.per_sq, 2), "squares": sq},
            "result": round(li.amount, 2),
        }
    return {"formula": "fixed amount", "inputs": {}, "result": round(li.amount, 2)}


@dataclass
class MarginInfo:
    profit_dollars: float
    oh_dollars: float
    eligible_base: float
    profit_pct: float
    combined_pct: float
    profit_floor_ok: bool
    combined_floor_ok: bool
    margin_warnings: list[str]


@dataclass
class EstimateResult:
    code_zone: Zone
    roof_type: RoofType
    num_squares: float
    per_square_total: float
    squares_subtotal: float
    project_total: float
    line_items_detail: list[LineItem]
    margin: MarginInfo
    commission: float
    # Legacy flat dicts for backward-compat with existing API / tests
    project_fixed_costs: dict[str, float] = field(default_factory=dict)
    line_items: dict[str, float] = field(default_factory=dict)
    pm_incentive: float = 0.0
    profit_dollars: float = 0.0
    profit_pct: float = 0.0
    estimated_commission: float = 0.0
    margin_ok: bool = True
    margin_warnings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Estimate-debug toggle: attach the formula, variables and values behind every priced line
    # so an estimator can audit a quote instead of trusting it. Off by default — the payload
    # roughly doubles, and the trace names internal config keys.
    debug: bool = False

    def _trace(self) -> list[dict]:
        """Section-level roll-ups: how the per-square lines become the project total.

        Mirrors Tim's own sheet so an estimator can check us against it line for line —
        `TOTAL PER SQ =SUM(B2:B8)` then `PROJECT TOTAL =(B17*B18)+SUM(B19:B21)`.
        """
        per_sq_items = [li for li in self.line_items_detail if li.per_sq is not None]
        fixed_items = [li for li in self.line_items_detail if li.per_sq is None]
        return [
            {
                "section": "Per-square total",
                "formula": "sum of every per-square rate  (Tim's B9 =SUM(B2:B8))",
                "inputs": {li.key: round(li.per_sq, 2) for li in per_sq_items},
                "result": round(self.per_square_total, 2),
            },
            {
                "section": "Squares subtotal",
                "formula": "per_square_total x squares  (Tim's B17*B18)",
                "inputs": {"per_square_total": round(self.per_square_total, 2),
                           "squares": self.num_squares},
                "result": round(self.squares_subtotal, 2),
            },
            {
                "section": "Project fixed costs",
                "formula": "sum of the non-per-square items  (Tim's SUM(B19:B21))",
                "inputs": {li.key: round(li.amount, 2) for li in fixed_items},
                "result": round(self.project_total - self.squares_subtotal, 2),
            },
            {
                "section": "Project total",
                "formula": "squares_subtotal + fixed costs  (Tim's B22)",
                "inputs": {"squares_subtotal": round(self.squares_subtotal, 2),
                           "fixed": round(self.project_total - self.squares_subtotal, 2)},
                "result": round(self.project_total, 2),
            },
            {
                "section": "Margin check",
                "formula": "profit / eligible_base, and (profit + OH) / eligible_base "
                           "(Tim's B25 and B26; floors 13% and 33%)",
                "inputs": {"profit_dollars": round(self.margin.profit_dollars, 2),
                           "oh_dollars": round(self.margin.oh_dollars, 2),
                           "eligible_base": round(self.margin.eligible_base, 2)},
                "result": {"profit_pct": round(self.margin.profit_pct, 4),
                           "combined_pct": round(self.margin.combined_pct, 4),
                           "profit_floor_ok": self.margin.profit_floor_ok,
                           "combined_floor_ok": self.margin.combined_floor_ok},
            },
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_zone": self.code_zone,
            "roof_type": self.roof_type,
            "num_squares": self.num_squares,
            "per_square_total": round(self.per_square_total, 2),
            "squares_subtotal": round(self.squares_subtotal, 2),
            "project_total": round(self.project_total, 2),
            "line_items_detail": [
                {
                    "key": li.key,
                    "label": li.label,
                    "amount": round(li.amount, 2),
                    "category": li.category,
                    "per_sq": round(li.per_sq, 2) if li.per_sq is not None else None,
                    **({"explain": _explain(li, self.num_squares)} if self.debug else {}),
                }
                for li in self.line_items_detail
            ],
            **({"calculation_trace": self._trace()} if self.debug else {}),
            "margin": {
                "profit_dollars": round(self.margin.profit_dollars, 2),
                "oh_dollars": round(self.margin.oh_dollars, 2),
                "eligible_base": round(self.margin.eligible_base, 2),
                "profit_pct": round(self.margin.profit_pct, 4),
                "combined_pct": round(self.margin.combined_pct, 4),
                "profit_floor_ok": self.margin.profit_floor_ok,
                "combined_floor_ok": self.margin.combined_floor_ok,
                "margin_warnings": self.margin.margin_warnings,
            },
            "commission": round(self.commission, 2),
            # Legacy fields
            "project_fixed_costs": {k: round(v, 2) for k, v in self.project_fixed_costs.items()},
            "line_items": {k: round(v, 2) for k, v in self.line_items.items()},
            "pm_incentive": self.pm_incentive,
            "profit_dollars": round(self.profit_dollars, 2),
            "profit_pct": round(self.profit_pct, 4),
            "estimated_commission": round(self.estimated_commission, 2),
            "margin_ok": self.margin_ok,
            "margin_warnings": self.margin_warnings,
            "warnings": self.warnings,
        }


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _is_tile(roof_type: RoofType) -> bool:
    return roof_type in ("13_tile", "barrel_tile")


def _is_metal(roof_type: RoofType) -> bool:
    return roof_type == "standing_seam_metal"


def _label(key: str) -> str:
    return key.replace("_", " ").title()


# -------------------------------------------------------------------------
# Sloped engine
# -------------------------------------------------------------------------
def _apply_min_margin(
    config: PricingConfig, items: list[LineItem], sq: float, explicit_profit: bool = False,
    effective_floor: float = 0.0, on_site_weeks: Optional[int] = None,
    commission_rate: Optional[float] = None,
    profit_floor_scope: str = "job",
) -> Optional[str]:
    """Raise the profit line to the week-based floor. Returns a warning code if it fired.

    Tim, 2026-07-17 Zoom [08:52]: "i like to make 2500 bucks a week that we're on the job ...
    and if it's one day it still counts as one week and i'm still gonna charge 2500 bucks
    minimum on re-roofs". So the floor is weeks-on-THIS-job x weekly_profit_floor, with a
    one-week minimum — a one-day job owes the full $2,500, and five one-day jobs owe $2,500
    each. Nothing pools across jobs or across a calendar week.

    Applies to PROFIT alone, not profit-plus-overhead: recovering the office's daily cost is
    break-even, not margin, so a job carrying $1,400 of overhead still owes the floor on top.

    Mutates the profit LineItem in place because the floor has to move the quoted number, not
    just annotate it — the whole point is that the customer sees the floored price.
    """
    # "job" basis (the default): one flat floor however long the job runs. The weekly figure is
    # still computed and returned as guidance, it just doesn't move the price. Enforcing the
    # weekly multiple instead repriced 17 of Tim's 29 homes upward — most of his re-roofs run
    # 7-10 days, so a 2-week floor of $5,000 beats his own sliding scale on nearly every tile
    # job. He said "$2,500 a week"; he never said "$5,000 on a two-week job". Pending his answer.
    # A building inside a bid project does NOT pay its own floor — one floor covers the site, and
    # core.bid_project applies it over the summed days. Charging it per building is what took
    # Evergrene's seven small structures to $2,500 of profit EACH, against Tim's $433 on the bus
    # stop. compute_profit_guidance still runs upstream, so the per-building card can still show
    # what this roof would have been floored to on its own.
    if profit_floor_scope == "project":
        return None
    if config.profit_floor_basis() == "weekly":
        floor = effective_floor
    else:
        floor = config.job_profit_floor()
        on_site_weeks = 1
    if not config.enforce_profit_floor() or not floor or sq <= 0:
        return None
    profit = next((li for li in items if li.key == "profit"), None)
    if profit is None or profit.amount >= floor:
        return None
    if explicit_profit:
        # An operator who typed a number owns it. Overriding a flat profit or a per-square
        # override here would ALSO suppress the guardrail built to catch exactly that: the
        # flat_profit_floor check runs later, off the profit line, so raising it first makes
        # that check pass silently and the margin badge go green on a price nobody approved.
        # Those paths have their own floor guidance; leave them to it.
        return None

    was = profit.amount
    weeks = on_site_weeks or 1
    profit.amount = float(floor)
    profit.per_sq = float(floor) / sq
    basis = config.profit_floor_basis()
    how = (f"{weeks}-week minimum at ${config.weekly_profit_floor():,.0f}/week on the job"
           if basis == "weekly" else "flat minimum per job")
    profit.explain = {
        "formula": f"profit floor applied — the sliding scale gave ${was:,.2f}, below the "
                   f"${float(floor):,.2f} {how}",
        "inputs": {"scale_profit": round(was, 2), "effective_floor": float(floor),
                   "profit_floor_basis": basis, "on_site_weeks": weeks,
                   "weekly_profit_floor": config.weekly_profit_floor(),
                   "job_profit_floor": config.job_profit_floor(),
                   "days_per_week": config.profit_floor_days_per_week(),
                   "squares": sq, "floored": True},
    }
    # #422 — the floor moves the PROFIT line, and on the "profit" basis commission is a percentage
    # OF that line (commission = margin.profit_dollars x rate). So protecting a small job also
    # raises the salesperson's commission on it: a 10 sq HVHZ tile job floored from $1,400 to
    # $2,500 takes commission from $700 to $1,250 at Tim's 50% of net. He has never said whether
    # his $2,500 is what he keeps BEFORE or AFTER commission. If after, the floor should be
    # 2500/(1-rate), not 2500 — and at 50% that is $5,000, so the question got twice as expensive
    # when the rate was corrected.
    #
    # We cannot answer that for him, and quietly picking one reading would bury a real question
    # inside a number he is asked to sign. So the quote says it.
    #
    # `commission_rate` is the rate that MOVES WITH the profit line — the caller passes None on the
    # "job" basis, where a commission on GROSS does not move when profit does and the note would be
    # describing an effect that isn't happening. It is the effective rate, override included, so
    # the note quotes the number this quote will actually pay rather than the config default.
    extra = ""
    try:
        rate = commission_rate
        if rate:
            net = float(floor) * (1.0 - float(rate))
            extra = (f" Commission rises with it (${was * float(rate):,.0f} -> "
                     f"${float(floor) * float(rate):,.0f} at {float(rate) * 100:.3g}%), so Tim "
                     f"nets ${net:,.0f} of the ${float(floor):,.0f} floor. If the floor is meant "
                     f"to be what he KEEPS, it should be ${float(floor) / (1 - float(rate)):,.0f} "
                     f"— pending Tim.")
    except Exception:  # noqa: BLE001 — the note is advisory; never break a quote over it
        extra = ""
    return (f"min_margin_applied: profit raised from ${was:,.2f} to ${float(floor):,.2f} "
            + (f"({weeks}-week minimum)" if basis == "weekly" else "(minimum per job)")
            + extra)


def _build_sloped(config: PricingConfig, q: QuoteInput) -> list[LineItem]:
    """Build line items for a sloped roof. Returns categorized list."""
    items: list[LineItem] = []
    zone = q.code_zone
    rt = q.roof_type
    sq = q.num_squares

    tags = config.raw["cost_category_tags"]

    # Per-square components. Base is the flat sloped_base unless RoofR cut LFs are supplied and
    # the config carries the cut calculator, in which case the base is recomputed from geometry.
    if q.override_base_cost is not None:
        base = q.override_base_cost
    else:
        base = config.sloped_base(zone, rt)
        # apply_cut_calc_to_base=False keeps Tim's flat standard base while still letting the cut
        # LFs drive the geometry day model — the headline quote's contract.
        cut_base = compute_cut_adjusted_base(config, q, zone, rt) if q.apply_cut_calc_to_base else None
        if cut_base is not None:
            base = cut_base
    items.append(LineItem("base_cost_lm", "Base Cost (L+M)", base * sq, tags["base_cost_lm"], base))

    # Overhead — per_sq mode (default) or day-based mode (v2)
    if q.overhead_mode == "daily" and q.daily_series:
        oh_total, oh_per_sq = compute_daily_overhead(config, q.daily_series, sq)
        branch_basis = config.overhead_basis() == "branch"
        # Under the branch basis every series bills the SAME number — the office costs what it
        # costs regardless of what the crew is doing that day — so the per-series lookup collapses
        # to one rate and the build-up still reads "5 days tile x $1,400 + 3 days demo x $1,400".
        # Under the branch basis the rate shown per series is the burn AFTER the concurrency
        # split, so the printed build-up multiplies out to the overhead actually charged.
        crews = config.concurrent_crews() if branch_basis else 1.0
        rates = ({s.series: (config.office_daily_overhead() or 0) / crews for s in q.daily_series}
                 if branch_basis else config.daily_overhead_rates())
        items.append(LineItem("overhead", "Overhead", oh_total, tags["overhead"], oh_per_sq, explain={
            "formula": ("total days x the branch's daily overhead (monthly fixed overhead / working "
                        "days)" + (" / concurrent_crews" if crews != 1.0 else "") + ", then / squares"
                        if branch_basis else
                        "sum(days x daily_rate) per series, then / squares. Daily rate is the "
                        "office's burn share: crew x (office_daily_overhead / office_men)."),
            "inputs": {
                **{f"{s.series}_days": s.days for s in q.daily_series},
                **{f"{s.series}_rate": rates.get(s.series) for s in q.daily_series},
                "overhead_basis": config.overhead_basis(),
                "total_days": sum(s.days for s in q.daily_series),
                "office_daily_overhead": config.raw.get("office_daily_overhead"),
                # concurrent_crews splits the branch burn across the jobs sharing a day; it is
                # inert under the series basis, where the rates are already per-crew-day.
                **({"concurrent_crews": crews} if branch_basis else
                   {"office_men": config.raw.get("office_men")}),
                "squares": sq,
            }}))
    else:
        oh = q.override_overhead if q.override_overhead is not None else config.sloped_overhead(zone, rt)
        items.append(LineItem("overhead", "Overhead", oh * sq, tags["overhead"], oh, explain={
            "formula": "override_overhead x squares" if q.override_overhead is not None
                       else "sloped_overhead[zone][roof_type] x squares  (Tim's published $/sq)",
            "inputs": {"per_sq": oh, "zone": zone, "roof_type": rt, "squares": sq,
                       "overridden": q.override_overhead is not None}}))

    # Profit — scale mode (default) or flat-dollar mode (v2)
    if q.profit_mode == "flat" and q.flat_profit_dollars is not None:
        pft_total = q.flat_profit_dollars
        pft_per_sq = pft_total / sq
        items.append(LineItem("profit", "Profit", pft_total, tags["profit"], pft_per_sq))
    else:
        pft = q.override_profit_per_sq if q.override_profit_per_sq is not None else config.profit_per_sq(sq)
        items.append(LineItem("profit", "Profit", pft * sq, tags["profit"], pft, explain={
            "formula": "override x squares" if q.override_profit_per_sq is not None
                       else "profit_scale band for this many squares, x squares  (Tim's sliding "
                            "scale: 1sq $400 / 2-4 $200 / 5-7 $160 / 8-14 $140 / 15-20 $120 / "
                            "20-29 $110 / 30+ $100)",
            "inputs": {"per_sq": pft, "squares": sq, "profit_scale": config.raw.get("profit_scale"),
                       "overridden": q.override_profit_per_sq is not None}}))

    # Tim uses this cell as a free-form dollar catch-all, not a three-way pick: his own worked
    # example was $45/sq to hand-load a rear roof a delivery truck cannot reach, and he describes
    # the field as "for roof cuts or for random stuff like extra delivery fee" (Zoom 2026-07-17
    # [03:29]). $45 is not expressible as low/medium/high ($0/$25/$50), so the categorical picker
    # stays as the guide and an explicit dollar amount overrides it.
    cuts_val = (q.roof_cuts_per_sq if q.roof_cuts_per_sq is not None
                else config.raw["roof_cuts"][q.roof_cuts])
    if cuts_val:
        items.append(LineItem("roof_cuts", "Roof Cuts / Access", cuts_val * sq,
                              tags["roof_cuts"], cuts_val))

    height_val = config.raw["roof_height"].get(q.roof_height)
    if q.roof_height == "6_plus":
        raise QuoteRequiresManualReview("6+ story jobs require manual quote (crane needed).")
    if q.roof_height == "3_5_stories":
        flat_add = config.raw["roof_height_3_5_flat_add"]
        items.append(LineItem("stories_3_5_delivery_chute", "3–5 Story Add", flat_add, tags["roof_height"]))
    elif height_val:
        items.append(LineItem("roof_height", "Roof Height", height_val * sq, tags["roof_height"], height_val))

    pointing_val = config.raw["tile_pointing"][q.tile_pointing]
    if pointing_val:
        items.append(LineItem("tile_pointing", "Tile Pointing", pointing_val * sq, tags["tile_pointing"], pointing_val))

    if q.specialty_tile:
        st_val = config.raw["specialty_tile_upgrade"][zone][q.specialty_tile]
        items.append(LineItem("specialty_tile", "Specialty Tile", st_val * sq, tags["specialty_tile"], st_val))

    if q.pitch_7_12 and _is_tile(rt):
        p712 = config.zoned_add("pitch_7_12_add", zone)
        items.append(LineItem("pitch_7_12_add", "7/12 Pitch Add", p712 * sq, tags["pitch_7_12_add"], p712))

    # Demo adds key off what's being TORN OFF when known; legacy callers (existing_roof
    # unset) keep the old behavior of keying off the NEW roof type.
    ex = q.existing_roof
    if ex is None:
        ex = ("metal" if _is_metal(rt) else "tile" if _is_tile(rt) else "other") if q.demo else "none"
    if ex == "metal":
        md = config.zoned_add("metal_demo_add", zone)
        items.append(LineItem("metal_demo", "Metal Demo", md * sq, tags["metal_demo"], md))
    elif ex == "tile":
        td = config.zoned_add("tile_demo_add", zone)
        items.append(LineItem("tile_demo", "Tile Demo", td * sq, tags["tile_demo"], td))

    if q.secondary_water_barrier:
        swb = config.raw["secondary_water_barrier_add"]
        tag = tags["secondary_water_barrier"]
        items.append(LineItem("secondary_water_barrier", "Secondary Water Barrier", swb * sq, tag, swb))

    if q.winterguard:
        wg = config.zoned_add("winterguard_add", zone)
        items.append(LineItem("winterguard", "WinterGuard", wg * sq, tags["winterguard"], wg))

    return items


# -------------------------------------------------------------------------
# Project-level fixed costs
# -------------------------------------------------------------------------
def _build_fixed(config: PricingConfig, q: QuoteInput, zone: str) -> list[LineItem]:
    """Fixed costs. "Fixed" here has always meant "added once per CALL", not "once per site".

    That distinction is invisible on a single-building quote and wrong on a multi-building bid:
    Tim's Evergrene site paid $3,000 of delivery + bonus values + permit against a 3-square bus
    stop, because the estimator has no way to know eight other roofs share the truck and the
    permit. `suppress_fixed_keys` is how core.bid_project takes them back.
    """
    tags = config.raw["cost_category_tags"]
    items: list[LineItem] = []
    skip = q.suppress_fixed_keys or frozenset()

    if "delivery_plywood_vents" not in skip:
        dpv = config.raw["delivery_plywood_vents"]
        items.append(LineItem("delivery_plywood_vents", "Delivery / Plywood / Vents", dpv,
                              tags["delivery_plywood_vents"]))

    if "new_bonus_values" not in skip:
        nbv = config.raw["new_bonus_values"]
        items.append(LineItem("new_bonus_values", "New Bonus Values", nbv,
                              tags["new_bonus_values"]))

    if "permit_processing" not in skip:
        permit = config.raw["permit_processing"]
        if q.project_kind == "commercial":
            permit += config.raw["permit_commercial_add"]
        items.append(LineItem("permit_processing", "Permit Processing", permit,
                              tags["permit_processing"]))

    # Tile dumpster — automatic when tile is involved on either side of the job:
    # new tile roofs need it, and tearing OFF tile generates the dump loads regardless
    # of what goes on (Zoom [33:20]: one tile dump truck ≈ $1,200).
    # ⚠️ tile_dumpster_count is a ceil(), so calling it once per building rounds UP once per
    # building: Evergrene's nine roofs bill 14 dumpsters where the site needs 10. A dump load is
    # a SITE quantity even though it is not a flat fee, so the project suppresses this too and
    # recomputes it over the summed squares.
    if (("tile_dumpster" not in skip)
            and (_is_tile(q.roof_type) or q.existing_roof == "tile") and q.num_squares > 0):
        count = config.tile_dumpster_count(q.num_squares, zone)
        dumpster_cost = count * config.raw["tile_dumpster_cost"]
        items.append(LineItem("tile_dumpster", "Tile Dumpster", dumpster_cost,
                              tags["tile_dumpster"], explain={
            "formula": "dumpsters x tile_dumpster_cost, one dumpster per threshold squares "
                       "(Tim's sheet: every 30 sq FBC, more than 15 sq HVHZ)",
            "inputs": {"dumpsters": count, "cost_each": config.raw["tile_dumpster_cost"],
                       "threshold": config.raw["tile_dumpster_threshold"][zone],
                       "squares": q.num_squares, "zone": zone,
                       "boundary_inclusive": config.raw.get("tile_dumpster_boundary_inclusive")}}))

    # Accessibility, flat half (Tim 2026-07-27 20:36) — a quoted delivery/hand-load charge that
    # no per-square rate expresses. In _build_fixed so it reaches low-slope too, not just sloped.
    if q.accessibility_flat:
        items.append(LineItem(
            "accessibility", "Accessibility (hand-load / delivery)", float(q.accessibility_flat),
            tags.get("roof_cuts", "Labor"), explain={
                "formula": "manual amount entered by the estimator",
                "inputs": {"accessibility_flat": float(q.accessibility_flat)}}))

    # Plywood deck replacement (OI-5) — priced per SHEET regardless of roof type, with the
    # first N sheets free per Tim's proposal scope language.
    if q.plywood_sheets:
        rate = config.plywood_sheet_rate(q.plywood_thickness)
        included = config.plywood_sheets_included()
        billable_sheets = max(0.0, q.plywood_sheets - included)
        if billable_sheets:
            items.append(LineItem(
                "plywood_replacement", "Plywood Deck Replacement", billable_sheets * rate,
                tags.get("plywood_replacement", "Materials"), explain={
                    "formula": "max(0, sheets - sheets_included) x per_sheet_rate[thickness]",
                    "inputs": {"sheets": q.plywood_sheets, "sheets_included": included,
                               "billable_sheets": billable_sheets,
                               "thickness": q.plywood_thickness, "rate": rate}}))

    return items


# -------------------------------------------------------------------------
# Optional line items (stucco, penetrations, ridge vents, zone extras)
# -------------------------------------------------------------------------
def _build_optional(config: PricingConfig, q: QuoteInput, zone: str) -> list[LineItem]:
    tags = config.raw["cost_category_tags"]
    items: list[LineItem] = []

    if q.stucco_metal_lf:
        rate = config.raw["stucco_metal_per_lf"]
        items.append(LineItem("stucco_metal", "Stucco Metal", q.stucco_metal_lf * rate, tags["stucco_metal"]))

    if q.penetrations:
        rate = config.raw["penetration_each"]
        items.append(LineItem("penetrations", "Penetrations", q.penetrations * rate, tags["penetrations"]))

    for _addon in q.silicone_addons:
        _rates = config.silicone_addons()
        _rate = _rates.get(_addon)
        if _rate is None:
            raise ConfigError(
                f"silicone add-on {_addon!r} is not priced for this config. "
                f"Known add-ons: {', '.join(sorted(_rates)) or 'none configured'}."
            )
        items.append(LineItem(f"silicone_addon_{_addon}", _addon.replace("_", " ").title(),
                              _rate * q.num_squares, tags.get("silicone_addons", "Materials"),
                              _rate))

    if q.extra_coats:
        _lop = config.silicone_extra_coat_lop()
        if not _lop:
            raise ConfigError(
                "extra_coats requested but low_slope.silicone_extra_coat_lop is not configured."
            )
        # Material is required, not defaulted to zero: a coat with no material is not a coat, and
        # billing L/OH/P alone would look like a complete price while under-charging every time.
        if q.extra_coat_material_per_sq is None:
            raise ConfigError(
                f"extra_coats={q.extra_coats} needs extra_coat_material_per_sq. L27 prices an "
                f"extra coat at ${_lop:g}/sq (L, OH & P) PLUS materials, and the material half "
                "varies by coat — Tim's own build-ups run $195/$220/$300 for 1/2/3 coats."
            )
        _per_sq = _lop + float(q.extra_coat_material_per_sq)
        items.append(LineItem(
            "silicone_extra_coats", f"Extra Silicone Coats (x{q.extra_coats})",
            _per_sq * q.num_squares * q.extra_coats,
            tags.get("silicone_addons", "Materials"), _per_sq,
        ))

    for _key, _qty in (q.detail_items or {}).items():
        if not _qty:
            continue
        _rates = config.low_slope_detail_items()
        _rate = _rates.get(_key)
        if _rate is None:
            raise ConfigError(
                f"detail item {_key!r} is not priced for this branch's config. "
                f"Known detail items: {', '.join(sorted(_rates)) or 'none configured'}."
            )
        items.append(LineItem(f"detail_{_key}", _key.replace("_", " ").title(),
                              _rate * _qty, tags.get("detail_items", "Materials")))

    if q.include_pressure_cleaning:
        # Rate follows the ROOF's slope, not the config block the value is stored in.
        pc_rate = config.pressure_cleaning_per_sq(q.slope_type)
        if pc_rate:
            items.append(LineItem(
                "pressure_cleaning", "Pressure Cleaning", pc_rate * q.num_squares,
                tags.get("pressure_cleaning", "Labor"), pc_rate,
            ))

    if q.ridge_vent_lf:
        rate = config.raw["ridge_vent_per_lf"]
        items.append(LineItem("ridge_vents", "Ridge Vents", q.ridge_vent_lf * rate, tags["ridge_vents"]))

    if q.gutter_lf or q.gutter_removal_lf or q.downspout_lf or q.leaderheads_res or q.leaderheads_comm:
        g = config.raw.get("gutters") or {}
        tag = tags.get("gutters", "Materials")

        def _grate(val: Any, name: str) -> float:
            if val is None:
                raise ConfigError(
                    f"gutters.{name} is missing — required by this quote. "
                    "Fill it in Admin → Estimating Config."
                )
            return float(val)

        if q.gutter_lf:
            styles = g.get("styles") or {}
            style = styles.get(q.gutter_style or "")
            if style is None:
                raise ConfigError(
                    f"gutters.styles.{q.gutter_style!r} is not configured — pick a configured "
                    "gutter style or add it in Admin → Estimating Config."
                )
            rate_key = "two_story_per_lf" if q.gutter_two_story else "per_lf"
            rate = _grate(style.get(rate_key), f"styles.{q.gutter_style}.{rate_key}")
            # Small jobs (under threshold LF) carry a per-LF surcharge (Tim: "+$2 or more")
            threshold = float(g.get("small_job_threshold_lf") or 0)
            if threshold and q.gutter_lf < threshold:
                rate += _grate(g.get("small_job_add_per_lf"), "small_job_add_per_lf")
            label = style.get("label") or q.gutter_style
            if q.gutter_two_story:
                label = f"{label} (2-story)"
            items.append(LineItem("gutters", label, q.gutter_lf * rate, tag, rate))
            if q.gutter_elbows:
                each = _grate(style.get("elbow_each", 0), f"styles.{q.gutter_style}.elbow_each")
                if each:
                    items.append(LineItem("gutter_elbows", "Gutter Elbows", q.gutter_elbows * each, tag))
            if q.leaf_guard != "none":
                lg_key = "leaf_guard_upgraded_per_lf" if q.leaf_guard == "upgraded" else "leaf_guard_std_per_lf"
                lg = _grate(g.get(lg_key), lg_key)
                lg_label = "Leaf Guard (upgraded)" if q.leaf_guard == "upgraded" else "Leaf Guard (standard)"
                items.append(LineItem("leaf_guard", lg_label, q.gutter_lf * lg, tag, lg))
        if q.gutter_removal_lf:
            rem = _grate(g.get("removal_per_lf"), "removal_per_lf")
            items.append(LineItem("gutter_removal", "Gutter Removal & Disposal",
                                  q.gutter_removal_lf * rem, tags.get("gutters", "Labor"), rem))
        if q.downspout_lf:
            ds_rate = _grate(g.get("downspout_per_lf"), "downspout_per_lf")
            items.append(LineItem("downspout", "Downspout (4x5)",
                                  q.downspout_lf * ds_rate, tag, ds_rate))
        if q.leaderheads_res:
            each = _grate(g.get("leaderhead_res_each"), "leaderhead_res_each")
            items.append(LineItem("leaderheads_res", "Leaderhead / Conductor Head (res.)",
                                  q.leaderheads_res * each, tag))
        if q.leaderheads_comm:
            each = _grate(g.get("leaderhead_comm_each"), "leaderhead_comm_each")
            items.append(LineItem("leaderheads_comm", "Leaderhead / Conductor Head (comm.)",
                                  q.leaderheads_comm * each, tag))

    zone_extras = config.raw["line_items"].get(zone, {})
    for key in q.extra_line_items:
        if key in zone_extras:
            items.append(LineItem(key, _label(key), zone_extras[key], "Materials"))

    return items


# -------------------------------------------------------------------------
# County overrides
# -------------------------------------------------------------------------
def _apply_county_overrides(
    config: PricingConfig,
    county: Optional[str],
    items: list[LineItem],
    zone: str,
    roof_type: str,
) -> list[LineItem]:
    """Apply county overrides: permit_fee_add, materials_tax_7pct_tile, extra_line_items."""
    if not county:
        return items

    overrides = config.raw["county_overrides"].get(county, {})
    result = list(items)

    # Permit fee add
    permit_add = overrides.get("permit_fee_add", 0) or 0
    if permit_add:
        for i, li in enumerate(result):
            if li.key == "permit_processing":
                result[i] = LineItem(
                    li.key, li.label, li.amount + permit_add,
                    li.category, li.per_sq, li.floor_excluded,
                )
                break

    # 7% materials tax on tile materials lines
    if overrides.get("materials_tax_7pct_tile") and _is_tile(roof_type):
        taxable_keys = {"base_cost_lm", "secondary_water_barrier", "winterguard",
                        "specialty_tile", "delivery_plywood_vents"}
        result = [
            LineItem(li.key, li.label, li.amount * 1.07, li.category, li.per_sq, li.floor_excluded)
            if li.key in taxable_keys and li.category == "Materials"
            else li
            for li in result
        ]

    # Extra county line items
    extra = overrides.get("extra_line_items") or {}
    for key, amount in extra.items():
        result.append(LineItem(key, _label(key), float(amount), "Misc"))

    return result


# -------------------------------------------------------------------------
# Margin floor computation
# -------------------------------------------------------------------------
def _eligible_base(config: PricingConfig, items: list[LineItem]) -> float:
    """total - Profit lines - floor-excluded lines.

    Shared by the margin badge (_compute_margin) and the percent-profit-mode line-item
    build (Jarvis #432) so an operator's typed percentage and the badge's profit_pct always
    describe the same base — computing it two different ways would make the badge lie about
    the number the operator just typed.
    """
    floor_excl = config.raw["floor_excluded_categories"]
    total = sum(li.amount for li in items)
    excluded_amount = sum(
        li.amount for li in items
        if li.key in floor_excl or li.category == "Profit"
    )
    return total - excluded_amount


def _compute_margin(
    config: PricingConfig,
    items: list[LineItem],
    slope_type: SlopeType,
    zone: Zone,
    flat_profit_effective_floor: Optional[float] = None,
) -> MarginInfo:
    """Compute margin metrics and floor warnings.

    flat_profit_effective_floor: when profit_mode='flat', pass the effective floor
        (max of job_profit_floor and weekly floor) so the margin badge reflects it.
        A flat profit below this floor adds 'flat_profit_floor' to margin_warnings
        and causes profit_floor_ok=False, keeping the hero badge and the inline
        warning consistent.
    """
    floor_excl = config.raw["floor_excluded_categories"]

    profit_dollars = sum(li.amount for li in items if li.category == "Profit")
    oh_dollars = sum(
        li.amount for li in items
        if li.category == "OH"
        and "OH" not in floor_excl.get(li.key, [])
    )

    eligible_base = _eligible_base(config, items)

    profit_pct = (profit_dollars / eligible_base) if eligible_base else 0.0
    combined_pct = ((profit_dollars + oh_dollars) / eligible_base) if eligible_base else 0.0

    warnings = []
    pf_ok = profit_pct >= config.raw["profit_floor_pct"]
    cf_ok = combined_pct >= config.raw["profit_plus_oh_floor_pct"]
    if not pf_ok:
        warnings.append("profit_floor")
    if not cf_ok:
        warnings.append("combined_floor")

    # v2: flat-profit dollar floor check (absolute + weekly minimum)
    if flat_profit_effective_floor is not None and profit_dollars < flat_profit_effective_floor:
        warnings.append("flat_profit_floor")
        pf_ok = False

    return MarginInfo(
        profit_dollars=profit_dollars,
        oh_dollars=oh_dollars,
        eligible_base=eligible_base,
        profit_pct=profit_pct,
        combined_pct=combined_pct,
        profit_floor_ok=pf_ok,
        combined_floor_ok=cf_ok,
        margin_warnings=warnings,
    )


# -------------------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------------------
def estimate(config_or_input, input_or_none=None) -> dict:
    """Compute a full estimate.

    Supports two call signatures for backward compatibility:
      estimate(config: PricingConfig, input: QuoteInput) -> dict   [F2 signature]
      estimate(q: QuoteInput) -> dict                               [legacy stub signature]

    Returns a plain dict (call .to_dict() on EstimateResult internally).

    v2 additions in the result dict (present when either v2 mode is active):
      profit_guidance — dict from compute_profit_guidance(), attached whenever
                        overhead_mode="daily" OR profit_mode="flat".
                        When series is empty (flat mode without daily OH):
                            on_site_weeks=None, effective_floor=job_profit_floor.
                        When series is non-empty: full weekly breakdown + implied $/week.
    """
    if input_or_none is None:
        # Legacy single-arg call: estimate(q)
        q: QuoteInput = config_or_input
        return _estimate_legacy(q)

    config: PricingConfig = config_or_input
    q: QuoteInput = input_or_none

    # Day-based OH with no days supplied: auto-fill them from squares instead of silently
    # falling back to per-square OH (the ~$2k PROTECTOR gap — Zoom 2026-07-17). Days the
    # caller typed always win.
    auto_days = False
    fell_back_to_per_sq = False
    if q.overhead_mode == "daily" and not q.daily_series:
        derived = derive_daily_series(config, q)
        if derived:
            q = replace(q, daily_series=derived)
            auto_days = True
        else:
            # No fitted day model for this roof type — `derive_daily_series` returns [] for every
            # low-slope system, because the fitted workbook is SLOPED ONLY. The estimate then
            # silently uses the per-square overhead table while the caller asked for days, and
            # nothing in the result said so. Tim, 2026-08-03: "Why is this still trying to use per
            # SQ prices on the OH? It's all going to be based on days" — a quote that quietly
            # ignores that reads exactly like one that honoured it.
            #
            # This is a GAP, not Tim's method. He prices low-slope by days too, and both
            # commercial workbooks show the per-square figure being DERIVED from days rather than
            # driving them: Miramar's overhead cell reads "$1,175 x 25 days & $765 x 30 days =
            # $52,325" against 142 squares (= the $370/sq it displays), and Evergrene's bid sheet
            # carries a TOTAL DAYS column whose "Clubhouse Flats (3)" row is 28 sq / 7 days /
            # $6,195 OH (= the $221.25/sq it displays). A per-square number that is an OUTPUT of a
            # day calculation must not be read as the input.
            fell_back_to_per_sq = True

    result = _estimate_config(config, q).to_dict()
    if fell_back_to_per_sq:
        result["overhead_basis_used"] = "per_sq"
        result["warnings"] = list(result.get("warnings") or []) + [
            f"overhead_fell_back_to_per_sq: daily overhead was requested, but {q.roof_type!r} has "
            "no fitted day series (the time-learning model covers sloped roofs only), so overhead "
            "came from the per-square table. Tim prices low-slope by DAYS as well — his commercial "
            "bids derive the per-square figure from a day count — so treat this as an unpriced gap "
            "and confirm the overhead against a day estimate before sending."
        ]
    elif q.overhead_mode == "daily" and q.daily_series:
        result["overhead_basis_used"] = "daily"
    if auto_days:
        # By-days OH lands well below the per-square OH on tile/metal, so an auto-filled
        # estimate must never look hand-checked. Say the days came from the model.
        days_txt = ", ".join(f"{s.series}={s.days}d" for s in q.daily_series)
        result["warnings"] = list(result.get("warnings") or []) + [
            f"daily_days_auto_filled: labor days were derived from {q.num_squares:g} squares "
            f"({days_txt}) using the time-learning model, not entered by the estimator. "
            "Confirm them against the crew schedule before sending."
        ]

    # Attach profit_guidance when any v2 mode is active
    if q.overhead_mode == "daily" or q.profit_mode == "flat":
        flat_profit = q.flat_profit_dollars if q.profit_mode == "flat" else None
        result["profit_guidance"] = compute_profit_guidance(config, q.daily_series, flat_profit)
    if q.overhead_mode == "daily":
        result["daily_series"] = [{"series": s.series, "days": s.days} for s in q.daily_series]

    return result


def _estimate_config(config: PricingConfig, q: QuoteInput) -> EstimateResult:
    """Core estimation logic — config-injected, fully categorized."""
    zone = q.code_zone

    if q.slope_type == "sloped":
        per_sq_items = _build_sloped(config, q)
    else:
        per_sq_items = _build_low_slope(config, q)

    # MIXED ROOFS. Tim's own 30-home sheet carries a "Squares (Flat)" column and a
    # "Flat (days) - if existing" column: 9 of those 30 homes have a flat section, up to 34% of the
    # roof. slope_type is exclusive, so before this the flat area was simply not quoted — $60,535 of
    # marginal value missing across 8 homes. The flat section contributes only its own PER-AREA
    # lines; everything whole-job (profit, roof height, trash chute) stays singular and is banded on
    # the COMBINED squares below.
    total_sq = q.num_squares + (q.flat_squares or 0.0)
    flat_items: list[LineItem] = []
    if q.slope_type == "sloped" and q.flat_squares and q.flat_squares > 0:
        # Every mixed-roof proposal in the golden set sells the flat section the same way —
        # "PERKINS PROTECTOR - Flat Re-Roof — Polyglass SAP modified bitumen", 3 of 3 — so default
        # to it rather than refusing to quote. Config-driven so it is not a constant in the engine.
        flat_rt = q.flat_roof_type or config.raw["low_slope"].get("default_flat_system")
        if not flat_rt:
            raise ConfigError(
                "flat_squares supplied without flat_roof_type and low_slope.default_flat_system "
                "is unset — a flat section cannot be priced without knowing its system."
            )
        flat_q = replace(q, slope_type="low_slope", roof_type=flat_rt,
                         num_squares=q.flat_squares)
        CARRIES_OVER = {"base_cost_lm", "overhead", "tear_off", "deck_type",
                        "insulation", "tapered"}
        for li in _build_low_slope(config, flat_q):
            if li.key not in CARRIES_OVER:
                continue
            flat_items.append(replace(li, key=f"flat_{li.key}", label=f"Flat roof — {li.label}"))
        per_sq_items = per_sq_items + flat_items

        # Profit bands on JOB SIZE, so a 32.5 + 17 roof is a 49.5-square job and must not be
        # priced at the 32.5-square band. Rebuild the single profit line on the combined squares.
        # (Skipped when the operator set profit explicitly — that is never overridden.)
        if q.profit_mode != "flat" and q.override_profit_per_sq is None:
            pft = config.profit_per_sq(total_sq)
            per_sq_items = [li for li in per_sq_items if li.key != "profit"] + [
                LineItem("profit", "Profit", pft * total_sq,
                         config.raw["cost_category_tags"]["profit"], pft, explain={
                             "formula": "profit_per_sq(sloped_sq + flat_sq) x (sloped_sq + flat_sq)",
                             "inputs": {"sloped_sq": q.num_squares, "flat_sq": q.flat_squares,
                                        "total_sq": total_sq, "per_sq": pft}})]

    fixed_items = _build_fixed(config, q, zone)
    optional_items = _build_optional(config, q, zone)

    # PM incentive
    tags = config.raw["cost_category_tags"]
    warnings: list[str] = []

    # Steepness is priced on BOTH sides and they overlap. The day model adds +0.5 install days at
    # >=6/12, and Tim's 7/12 material adder is $305/sq — whose own comment build-up is
    # "Demo L $70 + Tile L $70 + M $40 + OH $90 + P $35", i.e. it already contains $90/sq of
    # OVERHEAD. So a 7/12 roof pays for steep-roof overhead twice: once inside the adder and again
    # through the extra half day. Nobody noticed while pitch_7_12 was hardcoded false and never
    # fired; it fires now. We have ZERO 7/12+ homes in the 29 Tim sent, so there is no calibration
    # in the band where his own sheet says cost jumps — warn rather than silently pick a side.
    if q.pitch_7_12 and q.overhead_mode == "daily":
        model = config.raw.get("daily_overhead_day_model") or {}
        thr = (model.get("pitch_day_adder") or {}).get("threshold")
        if thr and q.pitch_primary and float(q.pitch_primary) >= float(thr):
            warnings.append(
                f"steepness_counted_twice: the {thr:g}/12+ day adder added labour days AND the "
                "7/12 material adder is applied, but that adder already includes $90/sq of "
                "overhead in Tim's own build-up. Steep-roof overhead is charged on both sides and "
                "no 7/12+ job exists in the calibration set. Review before sending — pending Tim."
            )

    # The day model was fitted on 29 homes that are ALL Palm Beach County / Treasure Coast —
    # zero Miami-Dade, zero Broward, zero Collier, therefore zero HVHZ. It is nonetheless shipped
    # to every branch. Cross-validation says the fit is real where it was fitted (honest LOO 83%
    # within a day against 34% for a constant-mean baseline, scripts/honest_day_model_cv.py), and
    # says nothing at all about a market it never saw. HVHZ roofs carry different detail, crews
    # and inspection load, so extrapolating a labour-day count there is an assumption, not a
    # measurement. Say so on the quote instead of letting the number look equally earned.
    if q.overhead_mode == "daily" and zone == "HVHZ" and (config.daily_overhead_day_model() or {}):
        warnings.append(
            "day_model_outside_calibration: labour days come from a geometry model fitted only on "
            "Palm Beach County / Treasure Coast roofs — no HVHZ job is in the calibration set. "
            "The day count here is an extrapolation, not a measurement. Review before sending."
        )

    # Commercial is REACHABLE now that project_kind is sent, but it is priced as residential end
    # to end: it differs by a permit adder and a PM band step, while profit still comes off the
    # residential per-square scale. Tim's own Miramar file prices commercial at 14-15% of COST, a
    # different basis entirely. Until profit carries a basis discriminator, a commercial quote is
    # a residential quote wearing a label — and it must not leave the building silently.
    if q.project_kind == "commercial":
        warnings.append(
            "commercial_profit_model_unverified: profit is taken from the RESIDENTIAL per-square "
            "scale. Tim's Miramar commercial file prices profit at 14-15% of cost, which is a "
            "different basis, so this total is unvalidated for commercial work — pending Tim."
        )

    # Low-slope tear-off: the repo holds $20 / $35 / $75 for what is arguably the same thing, and
    # the extras block's own note says "beyond first". Surface it rather than silently pick.
    if q.slope_type == "low_slope" and q.layers_to_remove:
        ls_cfg = config.raw["low_slope"]
        extras = ls_cfg.get("tear_off_extras") or {}
        summed = sum(v for k, v in extras.items()
                     if not k.startswith("_") and isinstance(v, (int, float))
                     and not isinstance(v, bool))
        if summed and abs(summed - float(ls_cfg.get("tear_off_per_layer_per_sq") or 0)) > 0.01:
            warnings.append(
                f"tear_off_basis_unconfirmed: billing ${ls_cfg['tear_off_per_layer_per_sq']:g}/sq "
                f"per layer, but tear_off_extras sums to ${summed:g}/sq and the comment audit "
                "records $35 for an additional layer of demo. Tim's note says the $75 is 'per "
                "additional layer beyond first'. Confirm the basis before sending — pending Tim."
            )

    if flat_items:
        warnings.append(
            f"mixed_roof_priced: {q.num_squares:g} sloped + {q.flat_squares:g} flat squares quoted "
            f"as ONE job. Profit, PM incentive and the profit floor band on the combined "
            f"{total_sq:g} squares; the flat section contributes its own base, overhead and "
            "tear-off only. Tim prices these together on his own sheet, but we have no sold mixed "
            "roof to check the split against — review before sending."
        )

    # Tim's sheet, note behind the coating block: "Coating Prices Based on 25+ squares (Demo not
    # included in price - add $100)". Deliberately unpriced: we know the published rate assumes a
    # 25-square job and excludes demo, but not what a 10-square coating should carry, and inventing
    # that number is how the last several pricing defects happened. Warn, and let Tim answer.
    if q.slope_type == "low_slope" and config.is_all_in(q.roof_type):
        min_sq = config.raw["low_slope"].get("coating_price_basis_min_sq") or 25
        if q.num_squares < min_sq:
            warnings.append(
                f"coating_below_price_basis: {q.roof_type} is published on a {min_sq:g}-square "
                f"basis but this job is {q.num_squares:g} squares, so the per-square price does not "
                "carry a smaller job's profit density. Review before sending — pending Tim."
            )
        if q.demo or q.layers_to_remove:
            warnings.append(
                f"coating_demo_not_in_price: {q.roof_type} is an all-in price that EXCLUDES demo "
                "(Tim's sheet says add $100/sq). Confirm the demo charge — pending Tim."
            )

    # Stockmeier's 12-square minimum (live sheet M29: "min. 12 SQ job (less than 12 SQ is $390 M
    # per SQ and T&M)"). Both config keys have existed since the low-slope wave and neither was
    # ever read, while the fixture note claimed this was "now enforced as a warning" — so an
    # 8-square job quoted the flat all-in rate with nothing said.
    #
    # Warn rather than price it: below the minimum Tim's basis changes from per-square to time-
    # and-materials, and T&M is not a number the engine can derive. $390 is his MATERIAL rate, not
    # a total, so substituting it would look like a price and be one input short of being one.
    if q.slope_type == "low_slope" and (q.roof_type or "").startswith("stockmeier"):
        _min_sq = config.stockmeier_min_sq()
        if _min_sq and q.num_squares < _min_sq:
            _mat = config.stockmeier_under_min_material_per_sq()
            warnings.append(
                f"stockmeier_below_minimum: {q.num_squares:g} squares is under Tim's {_min_sq:g}-square "
                f"Stockmeier minimum, where the job is TIME AND MATERIALS, not the per-square rate "
                f"quoted here"
                + (f" (his material figure below the minimum is ${_mat:g}/sq, materials only)"
                   if _mat else "")
                + ". This quote's basis is wrong, not just its total — price it T&M before sending."
            )

    # Stucco metal: Tim's sheet gives the SAME adder twice, an order of magnitude apart. D29 (the
    # polyglass block) says "Add $9 per LF for stucco metal / L flashing"; G26 (the TPO block) says
    # "$9 per 10 LF". We bill per LF, so if G26 is the right reading every stucco line is 10x over
    # — 200 LF bills $1,800 where it should bill $180. The comment audit recorded this as "neither
    # is implemented"; one of them very much is, which is why this warns instead of staying a note.
    # Not defaulted to the cheaper reading either: that would quietly cut a real charge by 90%.
    if q.stucco_metal_lf:
        _rate = config.raw.get("stucco_metal_per_lf")
        warnings.append(
            f"stucco_metal_basis_contradiction: billing {q.stucco_metal_lf:g} LF x ${_rate:g}/LF = "
            f"${q.stucco_metal_lf * float(_rate or 0):,.2f}. Tim's sheet states this adder twice and "
            f"disagrees with itself by 10x — D29 '$9 per LF' (polyglass block) vs G26 '$9 per 10 LF' "
            f"(TPO block). On the G26 reading this line should be "
            f"${q.stucco_metal_lf * float(_rate or 0) / 10:,.2f}. Confirm the basis before sending "
            "— pending Tim."
        )

    # Trash-chute sections were computed from a storey BAND, not a count (see _build_low_slope).
    if q.roof_height == "3_5_stories" and not q.stories:
        _per_story, _per_section = config.trash_chute_sections()
        if _per_story and _per_section:
            warnings.append(
                f"trash_chute_storeys_assumed: '3_5_stories' is a band, so the chute sections were "
                f"priced at {_STOREY_FLOOR['3_5_stories']:g} storeys — the smallest the band allows, "
                f"at ${_per_story * _per_section:g}/storey. A 5-storey job is under-billed by "
                f"${_per_story * _per_section * 2:g}. Set `stories` to bill the real count."
            )

    # Crane flag (Tim, email 2026-07-27 20:24: ">2.5 stories"). The hard manual-review raise stays
    # at 6+; a 3-5 storey job still quotes (trash chute / $1,200 flat add) and until now carried no
    # crane signal at all, because the configured threshold of 3 was never read by anything.
    _stories = q.stories or _STOREY_FLOOR.get(q.roof_height or "")
    if _stories is not None and _stories >= config.crane_threshold_stories():
        warnings.append(
            f"crane_likely: {q.roof_height.replace('_', ' ')} is at or above the "
            f"{config.crane_threshold_stories():g}-storey crane threshold. Price the crane or "
            "confirm the trash-chute approach reaches — Tim asked for this flag by email 7/27."
        )

    # Waterfront gate for the COASTAL tier (same email). The tier already exists on tile, shingle
    # and metal; nothing said WHEN to reach for it, so a salt-exposed home could be quoted on a
    # package whose own manufacturer warranty will not cover it.
    if q.waterfront:
        warnings.append(
            "waterfront_coastal_tier: this property was marked waterfront/salt-exposed. Quote the "
            "COASTAL package — non-coastal metals and fasteners carry manufacturer setback "
            "provisions that void near salt water. Tidal and brackish canals count."
        )

    # Not-HVHZ-legal deck systems (OI-11). Tim's sheet labels these explicitly; warn rather than
    # block because he sometimes overrides his own sheet.
    if q.slope_type == "low_slope" and zone == "HVHZ" and q.deck_type:
        restriction = config.low_slope_not_hvhz_deck_types().get(q.deck_type)
        if restriction:
            warnings.append(
                f"deck_type_not_hvhz: {q.deck_type} is marked 'not HVHZ' on Tim's sheet "
                f"({restriction}) but this job's zone is HVHZ. Tim overrides his own sheet "
                "sometimes — confirm before sending."
            )
    try:
        pm_val = config.pm_incentive(zone, q.project_kind, total_sq)
    except ConfigError as exc:
        pm_val = 0.0
        warnings.append(
            f"pm_incentive_missing: {exc}. Estimate was calculated with PM Incentive = $0; "
            "confirm the correct PM incentive band with Tim."
        )
    pm_item = LineItem("pm_incentive", "PM Incentive", pm_val, tags["pm_incentive"], explain={
        # Was a pending-Tim note claiming we mis-key this. Resolved 2026-07-26 (e20aa18): the two
        # zones genuinely use different axes and the config now matches his live sheet, so the
        # warning became false while still printing on every estimate-debug trace.
        "formula": "band lookup, keyed the way this zone's sheet keys it — Palm Beach by SIZE "
                   "(<20 $50 / 20-50 $100 / >50 $250, both residential and commercial), "
                   "Miami by PROJECT KIND (residential $150 / commercial $300, any size)",
        "inputs": {"squares": total_sq, "project_kind": q.project_kind, "zone": zone,
                   "pm_incentive_table": config.raw.get("pm_incentive")}})

    # Cut-calculator advisories. The geometry base and the categorical roof_cuts low/med/high
    # knob both price cut complexity; Tim keeps both (low=$0 default), so surface — not suppress —
    # the overlap. Also warn when cut LFs are supplied for a zone the calculator isn't calibrated
    # for (falls back to the flat base silently otherwise).
    if q.slope_type == "sloped" and q.has_cut_measurements():
        cut_base = compute_cut_adjusted_base(config, q, zone, q.roof_type)
        if cut_base is None:
            warnings.append(
                f"cut_calc_uncalibrated_zone: RoofR cut LFs supplied but the cut calculator is "
                f"not calibrated for zone '{zone}' — flat base used. Seed cuts_calc.fixed_per_sq['{zone}']."
            )
        elif config.raw.get("roof_cuts", {}).get(q.roof_cuts):
            warnings.append(
                f"roof_cuts_double_count: the geometry cut calculator already prices cut complexity "
                f"in the base; the categorical roof_cuts='{q.roof_cuts}' line adds on top. Use "
                "roof_cuts='low' unless an extra manual cut charge is intended."
            )

    all_items = per_sq_items + fixed_items + optional_items + [pm_item]

    # County overrides applied last
    all_items = _apply_county_overrides(config, q.county, all_items, zone, q.roof_type)

    # Percent profit mode (v2 — Jarvis #432). Tim, 2026-07-27: "I would just eliminate [the
    # scale] for simplification ... use the slider for profit percentage with a minimum 2,500".
    # The scale/flat placeholder profit line built inside _build_sloped/_build_low_slope can't
    # know eligible_base yet — fixed/optional/pm items and county overrides hadn't run. Same
    # shape as the mixed-roof profit rebuild above: strip the placeholder, recompute now that
    # all_items is final, re-add it. This runs uniformly for sloped AND low-slope (both land in
    # all_items by this point) and is a no-op when the roof type carries no profit line at all
    # (low-slope all-in systems bake profit into the base price, in every mode).
    if q.profit_mode == "percent" and q.percent_profit_pct is not None and any(
            li.key == "profit" for li in all_items):
        eligible_base = _eligible_base(config, all_items)
        pct = q.percent_profit_pct
        pft_total = pct * eligible_base
        all_items = [li for li in all_items if li.key != "profit"] + [LineItem(
            "profit", "Profit", pft_total, tags["profit"],
            (pft_total / total_sq) if total_sq else None,
            explain={
                "formula": "percent_profit_pct x eligible_base  (Tim, 2026-07-27: profit_scale "
                           "retired for simplification — operator sets a % of eligible_base, "
                           "still subject to the $2,500/on-site-week floor)",
                "inputs": {"percent_profit_pct": pct, "eligible_base": round(eligible_base, 2)},
            })]

    # Minimum margin. Tim's sliding scale is per-square, so a small job earns almost nothing —
    # a 1-square tile roof scales to $400 of profit while a day of Jupiter office overhead
    # alone is $1,400. He does not take that work at scale price; his own sheet flags one
    # square as "price as T&M". This lifts profit to the floor and says so, rather than
    # quoting a job that cannot carry itself.
    explicit_profit = (q.profit_mode == "flat" and q.flat_profit_dollars is not None) or (
        q.override_profit_per_sq is not None)
    guidance = compute_profit_guidance(config, q.daily_series or [])
    # An operator minimum RAISES the config floor, never lowers it — the Quoting slider's "Min $"
    # box is a "don't go under this on this job" input, not a way to quote below Tim's $2,500.
    effective_floor = max(guidance["effective_floor"], q.min_profit_dollars or 0.0)
    # The rate follows the BASIS, not the roof: 15% of gross or 50% of net (Tim, 2026-08-02).
    # An operator slider (commission_rate_override) still wins — that is where a negotiated
    # per-salesperson split lives. Computed here rather than at its point of use below because
    # the floor's #422 note needs it, and depends on nothing the floor produces.
    comm_rate = (q.commission_rate_override if q.commission_rate_override is not None
                 else config.commission_rate(q.commission_basis))
    floored = _apply_min_margin(
        config, all_items, total_sq, explicit_profit,
        effective_floor=effective_floor, on_site_weeks=guidance["on_site_weeks"],
        commission_rate=comm_rate if q.commission_basis == "profit" else None,
        profit_floor_scope=q.profit_floor_scope)
    if floored:
        warnings.append(floored)

    project_total = sum(li.amount for li in all_items)

    # Per-square subtotal (sum of per-sq items only)
    per_sq_total_val = sum(
        li.amount / total_sq
        for li in per_sq_items
        if li.per_sq is not None and total_sq > 0
    )
    squares_subtotal = sum(li.amount for li in per_sq_items)

    # v2: compute effective floor for flat-profit margin check
    flat_floor: Optional[float] = None
    if q.profit_mode == "flat" and q.flat_profit_dollars is not None:
        guidance = compute_profit_guidance(config, q.daily_series, q.flat_profit_dollars)
        flat_floor = guidance["effective_floor"]

    margin = _compute_margin(config, all_items, q.slope_type, zone, flat_floor)

    comm_base = project_total if q.commission_basis == "job" else margin.profit_dollars
    commission = comm_base * comm_rate

    # Build legacy flat dicts for backward compat
    fixed_keys = {"delivery_plywood_vents", "new_bonus_values", "permit_processing",
                  "tile_dumpster", "stories_3_5_delivery_chute"}
    project_fixed = {li.key: li.amount for li in all_items if li.key in fixed_keys}
    line_items_flat = {
        li.key: li.amount for li in all_items
        if li.key not in fixed_keys
        and li.key not in {"base_cost_lm", "overhead", "profit", "pm_incentive"}
        and li.key not in {
            "roof_cuts", "roof_height", "tile_pointing", "specialty_tile",
            "pitch_7_12_add", "tile_demo", "metal_demo", "secondary_water_barrier",
            "winterguard", "insulation", "tapered"
        }
    }

    return EstimateResult(
        code_zone=zone,
        roof_type=q.roof_type,
        num_squares=q.num_squares,
        per_square_total=per_sq_total_val,
        squares_subtotal=squares_subtotal,
        project_total=project_total,
        line_items_detail=all_items,
        margin=margin,
        commission=commission,
        project_fixed_costs=project_fixed,
        line_items=line_items_flat,
        pm_incentive=pm_val,
        profit_dollars=margin.profit_dollars,
        profit_pct=margin.profit_pct,
        estimated_commission=commission,
        margin_ok=margin.profit_floor_ok,
        margin_warnings=margin.margin_warnings,
        warnings=warnings,
        debug=q.debug,
    )


def _WOOD_DECK_TYPES() -> frozenset:
    """Deck type keys that are wood-based (trigger the $50/sq OH adder)."""
    return frozenset({
        "bur_wood_wb3000", "bur_wood_sav_flashing", "bur_wood_elastobase",
        "tpo_wood_versashield", "tpo_wood_densdeck_iso",
    })


def _low_slope_oh_key(rt: str) -> str:
    """Map a low-slope roof_type system name to the overhead config key."""
    if rt.startswith("tpo"):
        return "tpo_oh"
    if rt.startswith("pb_") or rt.startswith("stockmeier"):
        return "coatings_inhouse_oh"
    return "flat_oh"


def _build_low_slope(config: PricingConfig, q: QuoteInput) -> list[LineItem]:
    """Build line items for a low-slope roof.

    All-in systems (listed in low_slope.all_in_systems) have OH+profit baked into their
    base price — the engine emits only the base_cost_lm line and skips OH/profit lines.
    Non-all-in systems get OH and profit added on top, matching the sloped path shape.
    Wood deck types add a $50/sq OH adder (concrete is the baseline; no adder).
    """
    tags = config.raw["cost_category_tags"]
    items: list[LineItem] = []
    zone = q.code_zone
    rt = q.roof_type
    sq = q.num_squares

    base = config.low_slope_base(zone, rt)
    items.append(LineItem("base_cost_lm", "Base Cost (L+M)", base * sq, tags["base_cost_lm"], base))

    # Polyglass warranty upgrades (E26-E28): 20/25/30-year systems priced as per-square adders
    # over the base. Warranty length is a sales lever and until now it could not be quoted at all
    # — the config carried the upgrades as a prose note tagged "encode as adders when quoting (v2)".
    if q.warranty_upgrade:
        _ups = config.polyglass_warranty_upgrades()
        _add = _ups.get(q.warranty_upgrade)
        if _add is None:
            raise ConfigError(
                f"warranty_upgrade {q.warranty_upgrade!r} is not priced for this config. "
                f"Known upgrades: {', '.join(sorted(_ups)) or 'none configured'}."
            )
        items.append(LineItem("warranty_upgrade", "Warranty Upgrade", _add * sq,
                              tags.get("warranty_upgrade", tags["base_cost_lm"]), _add))


    if not config.is_all_in(rt):
        # Overhead — per_sq mode (default) or day-based mode (v2)
        if q.overhead_mode == "daily" and q.daily_series:
            oh_total, oh_per_sq = compute_daily_overhead(config, q.daily_series, sq)
            items.append(LineItem("overhead", "Overhead", oh_total, tags["overhead"], oh_per_sq))
        else:
            oh_key = _low_slope_oh_key(rt)
            oh = config.low_slope_overhead(zone, oh_key)
            # Wood deck type adds $50/sq to overhead (concrete deck is the baseline)
            wood_adder = config.wood_deck_oh_adder() if q.deck_type in _WOOD_DECK_TYPES() else 0.0
            # Cover board adds $40/sq OH on top (H17: "an ADDITIONAL $40 OH for any cover board").
            # The board's MATERIAL is already inside the deck-type rate; only its overhead was
            # lost, so this stacks with the wood adder rather than replacing it.
            cover_adder = (config.cover_board_oh_adder()
                           if q.deck_type in config.cover_board_deck_types() else 0.0)
            effective_oh = oh + wood_adder + cover_adder
            items.append(LineItem("overhead", "Overhead", effective_oh * sq, tags["overhead"], effective_oh))

        # Profit — scale mode (default) or flat-dollar mode (v2)
        if q.profit_mode == "flat" and q.flat_profit_dollars is not None:
            pft_total = q.flat_profit_dollars
            pft_per_sq = pft_total / sq
            items.append(LineItem("profit", "Profit", pft_total, tags["profit"], pft_per_sq))
        else:
            pft = config.profit_per_sq(sq)
            items.append(LineItem("profit", "Profit", pft * sq, tags["profit"], pft))

    if q.layers_to_remove:
        # REVERTED to the $20 scalar 2026-07-25 after R2. I had summed tear_off_extras to $75 and
        # billed it on every layer. The repo holds THREE different numbers and none of them is
        # unambiguously "the cost of the first layer":
        #   tear_off_per_layer_per_sq            $20
        #   tear_off_extras 20+20+35             $75, and its own note reads
        #                                        "+$75/sq per additional layer BEYOND FIRST"
        #   low-slope comment audit, "Additional layer of demo"   $35
        # `_note_tear_off` also says the extras block was recorded "for line-item reporting in v2",
        # not for pricing. Summing it moved a 30-square single-layer job from $600 to $2,250 (+275%)
        # on a misreading — and tear_off_extras.oh is OVERHEAD, which would have been billed inside
        # a Labor-tagged line while the overhead line is computed separately. That is the same
        # double-count shape as the 7/12 adder. Warn and ask Tim; do not pick a number.
        tear_off = config.low_slope_tear_off_cost()
        items.append(LineItem("tear_off", "Tear-Off", tear_off * q.layers_to_remove * sq, "Labor"))

    if q.deck_type and q.deck_type != "existing_concrete":
        deck_cost = config.low_slope_deck_cost(q.deck_type)
        items.append(LineItem("deck_type", "Deck Replacement", deck_cost * sq, "Materials"))

    if q.include_insulation:
        ins_cost = config.low_slope_insulation_cost(q.insulation_thickness)
        items.append(LineItem(
            "insulation", "Insulation", ins_cost * sq, tags["insulation"],
            floor_excluded=config.raw["floor_excluded_categories"].get("insulation", []),
        ))

    if q.include_tapered:
        tap_cost = config.low_slope_tapered_cost()
        items.append(LineItem(
            "tapered", "Tapered Insulation", tap_cost * sq, tags["tapered"],
            floor_excluded=config.raw["floor_excluded_categories"].get("tapered", []),
        ))

    if q.roof_height == "6_plus":
        raise QuoteRequiresManualReview("6+ story jobs require manual quote (crane needed).")

    if q.roof_height == "3_5_stories":
        flat_add = config.raw["low_slope"]["trash_chute_flat_add"]
        items.append(LineItem("trash_chute", "Trash Chute", flat_add, "Labor"))
        # E18 reads "$1,500 + sections"; its comment: "3 sections of trash chute per story —
        # charge $100 per section". Only the flat part was ever billed, so a 5-storey job paid a
        # 3-storey chute. Additive, per the cell's own "+".
        per_story, per_section = config.trash_chute_sections()
        if per_story and per_section:
            # roof_height is a BAND. Without an explicit count, use its floor — the smallest
            # number consistent with the band, so an unknown never over-bills. estimate() warns.
            storeys = q.stories if q.stories else _STOREY_FLOOR.get(q.roof_height, 3)
            items.append(LineItem(
                "trash_chute_sections", "Trash Chute Sections",
                per_story * per_section * storeys, "Labor",
            ))

    height_val = config.raw["roof_height"].get(q.roof_height)
    if height_val:
        items.append(LineItem("roof_height", "Roof Height", height_val * sq, tags["roof_height"], height_val))

    return items


# -------------------------------------------------------------------------
# Legacy single-arg estimate (backward compat for old tests)
# -------------------------------------------------------------------------
def _estimate_legacy(q: QuoteInput) -> dict:
    """Legacy estimate path: reads from module-level constant tables.

    Only used when estimate(q) is called without a config — i.e. existing
    tests that predate F2. These tests use override_base_cost / override_overhead
    / override_profit_per_sq to reproduce the old workbook examples.
    """
    from core import _legacy_rates as _lr
    return _lr.estimate_legacy(q)


# -------------------------------------------------------------------------
# Self-check (pinned to old KEY-block numbers; used by legacy test)
# -------------------------------------------------------------------------
def _selfcheck() -> None:
    """Reproduce the workbook's worked example: 28 sq @ $635/sq → $20,280 pre-incentive.

    Uses the legacy path with explicit overrides.
    """
    q = QuoteInput(
        code_zone="HVHZ", roof_type="13_tile", num_squares=28,
        override_base_cost=430, override_overhead=115, override_profit_per_sq=90,
        roof_cuts="low", roof_height="1_story", tile_pointing="no",
        project_kind="residential",
    )
    r = _estimate_legacy(q)
    assert r["per_square_total"] == 635, r["per_square_total"]
    assert r["squares_subtotal"] == 17780, r["squares_subtotal"]
    pre_incentive = r["project_total"] - r["pm_incentive"]
    assert pre_incentive == 20280, pre_incentive
    print("estimator self-check OK:", {k: r[k] for k in ("per_square_total", "project_total")})


if __name__ == "__main__":  # pragma: no cover
    _selfcheck()
