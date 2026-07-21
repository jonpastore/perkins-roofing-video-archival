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
from dataclasses import dataclass, field
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


def compute_profit_guidance(
    config: PricingConfig,
    series: list[DailyOverheadSeries],
    flat_profit: Optional[float] = None,
) -> dict[str, Any]:
    """Compute profit guidance fields for the flat-dollar profit mode (v2).

    When series is non-empty:
        on_site_weeks = ceil(total_days / 5) — scheduling-window model (configurable).
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
    if rounding == "floor":
        on_site_weeks = max(1, math.floor(total_days / 5))
    else:
        on_site_weeks = math.ceil(total_days / 5)

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
    roof_cuts: str = "low"               # low | medium | high
    roof_height: str = "1_story"         # 1_story | 2_stories | 3_5_stories | 6_plus
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
    include_tapered: bool = False

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

    # Gutters — Tim's style-based price list (email 2026-07-17): per-LF price includes the
    # matching downspouts; 2-story is a per-LF uplift; elbows/leaf guards/leaderheads/removal
    # are separate. Rates live in config["gutters"]; missing/null rates raise ConfigError only
    # when a quote actually uses them.
    gutter_style: Optional[str] = None   # key into config["gutters"]["styles"], e.g. "k6_alum"
    gutter_lf: float = 0
    gutter_two_story: bool = False
    gutter_elbows: int = 0
    gutter_removal_lf: float = 0
    leaf_guard: str = "none"             # none | std | upgraded
    leaderheads_res: int = 0
    leaderheads_comm: int = 0

    # v2: Day-based overhead mode
    overhead_mode: str = "per_sq"        # "per_sq" (default, existing) | "daily"
    daily_series: list[DailyOverheadSeries] = field(default_factory=list)

    # v2: Profit mode
    profit_mode: str = "scale"           # "scale" (default, sliding scale) | "flat"
    flat_profit_dollars: Optional[float] = None   # used when profit_mode="flat"

    # Commission lever: basis = "profit" (% of profit dollars) or "job" (% of project total).
    # commission_rate_override is a fraction (e.g. 0.30); None falls back to the config rate.
    commission_basis: str = "profit"
    commission_rate_override: Optional[float] = None

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
                }
                for li in self.line_items_detail
            ],
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
        cut_base = compute_cut_adjusted_base(config, q, zone, rt)
        if cut_base is not None:
            base = cut_base
    items.append(LineItem("base_cost_lm", "Base Cost (L+M)", base * sq, tags["base_cost_lm"], base))

    # Overhead — per_sq mode (default) or day-based mode (v2)
    if q.overhead_mode == "daily" and q.daily_series:
        oh_total, oh_per_sq = compute_daily_overhead(config, q.daily_series, sq)
        items.append(LineItem("overhead", "Overhead", oh_total, tags["overhead"], oh_per_sq))
    else:
        oh = q.override_overhead if q.override_overhead is not None else config.sloped_overhead(zone, rt)
        items.append(LineItem("overhead", "Overhead", oh * sq, tags["overhead"], oh))

    # Profit — scale mode (default) or flat-dollar mode (v2)
    if q.profit_mode == "flat" and q.flat_profit_dollars is not None:
        pft_total = q.flat_profit_dollars
        pft_per_sq = pft_total / sq
        items.append(LineItem("profit", "Profit", pft_total, tags["profit"], pft_per_sq))
    else:
        pft = q.override_profit_per_sq if q.override_profit_per_sq is not None else config.profit_per_sq(sq)
        items.append(LineItem("profit", "Profit", pft * sq, tags["profit"], pft))

    cuts_val = config.raw["roof_cuts"][q.roof_cuts]
    if cuts_val:
        items.append(LineItem("roof_cuts", "Roof Cuts", cuts_val * sq, tags["roof_cuts"], cuts_val))

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
        p712 = config.raw["pitch_7_12_add"]
        items.append(LineItem("pitch_7_12_add", "7/12 Pitch Add", p712 * sq, tags["pitch_7_12_add"], p712))

    # Demo adds key off what's being TORN OFF when known; legacy callers (existing_roof
    # unset) keep the old behavior of keying off the NEW roof type.
    ex = q.existing_roof
    if ex is None:
        ex = ("metal" if _is_metal(rt) else "tile" if _is_tile(rt) else "other") if q.demo else "none"
    if ex == "metal":
        md = config.raw["metal_demo_add"]
        items.append(LineItem("metal_demo", "Metal Demo", md * sq, tags["metal_demo"], md))
    elif ex == "tile":
        td = config.raw["tile_demo_add"]
        items.append(LineItem("tile_demo", "Tile Demo", td * sq, tags["tile_demo"], td))

    if q.secondary_water_barrier:
        swb = config.raw["secondary_water_barrier_add"]
        tag = tags["secondary_water_barrier"]
        items.append(LineItem("secondary_water_barrier", "Secondary Water Barrier", swb * sq, tag, swb))

    if q.winterguard:
        wg = config.raw["winterguard_add"]
        items.append(LineItem("winterguard", "WinterGuard", wg * sq, tags["winterguard"], wg))

    return items


# -------------------------------------------------------------------------
# Project-level fixed costs
# -------------------------------------------------------------------------
def _build_fixed(config: PricingConfig, q: QuoteInput, zone: str) -> list[LineItem]:
    tags = config.raw["cost_category_tags"]
    items: list[LineItem] = []

    dpv = config.raw["delivery_plywood_vents"]
    items.append(LineItem("delivery_plywood_vents", "Delivery / Plywood / Vents", dpv, tags["delivery_plywood_vents"]))

    nbv = config.raw["new_bonus_values"]
    items.append(LineItem("new_bonus_values", "New Bonus Values", nbv, tags["new_bonus_values"]))

    permit = config.raw["permit_processing"]
    if q.project_kind == "commercial":
        permit += config.raw["permit_commercial_add"]
    items.append(LineItem("permit_processing", "Permit Processing", permit, tags["permit_processing"]))

    # Tile dumpster — automatic when tile is involved on either side of the job:
    # new tile roofs need it, and tearing OFF tile generates the dump loads regardless
    # of what goes on (Zoom [33:20]: one tile dump truck ≈ $1,200).
    if (_is_tile(q.roof_type) or q.existing_roof == "tile") and q.num_squares > 0:
        count = config.tile_dumpster_count(q.num_squares, zone)
        dumpster_cost = count * config.raw["tile_dumpster_cost"]
        items.append(LineItem("tile_dumpster", "Tile Dumpster", dumpster_cost, tags["tile_dumpster"]))

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

    if q.ridge_vent_lf:
        rate = config.raw["ridge_vent_per_lf"]
        items.append(LineItem("ridge_vents", "Ridge Vents", q.ridge_vent_lf * rate, tags["ridge_vents"]))

    if q.gutter_lf or q.gutter_removal_lf or q.leaderheads_res or q.leaderheads_comm:
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

    # eligible_base = total − Profit lines − floor-excluded lines
    total = sum(li.amount for li in items)
    excluded_amount = sum(
        li.amount for li in items
        if li.key in floor_excl or li.category == "Profit"
    )
    eligible_base = total - excluded_amount

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
    result = _estimate_config(config, q).to_dict()

    # Attach profit_guidance when any v2 mode is active
    if q.overhead_mode == "daily" or q.profit_mode == "flat":
        flat_profit = q.flat_profit_dollars if q.profit_mode == "flat" else None
        result["profit_guidance"] = compute_profit_guidance(config, q.daily_series, flat_profit)

    return result


def _estimate_config(config: PricingConfig, q: QuoteInput) -> EstimateResult:
    """Core estimation logic — config-injected, fully categorized."""
    zone = q.code_zone

    if q.slope_type == "sloped":
        per_sq_items = _build_sloped(config, q)
    else:
        per_sq_items = _build_low_slope(config, q)

    fixed_items = _build_fixed(config, q, zone)
    optional_items = _build_optional(config, q, zone)

    # PM incentive
    tags = config.raw["cost_category_tags"]
    warnings: list[str] = []
    try:
        pm_val = config.pm_incentive(zone, q.project_kind, q.num_squares)
    except ConfigError as exc:
        pm_val = 0.0
        warnings.append(
            f"pm_incentive_missing: {exc}. Estimate was calculated with PM Incentive = $0; "
            "confirm the correct PM incentive band with Tim."
        )
    pm_item = LineItem("pm_incentive", "PM Incentive", pm_val, tags["pm_incentive"])

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

    project_total = sum(li.amount for li in all_items)

    # Per-square subtotal (sum of per-sq items only)
    per_sq_total_val = sum(
        li.amount / q.num_squares
        for li in per_sq_items
        if li.per_sq is not None and q.num_squares > 0
    )
    squares_subtotal = sum(li.amount for li in per_sq_items)

    # v2: compute effective floor for flat-profit margin check
    flat_floor: Optional[float] = None
    if q.profit_mode == "flat" and q.flat_profit_dollars is not None:
        guidance = compute_profit_guidance(config, q.daily_series, q.flat_profit_dollars)
        flat_floor = guidance["effective_floor"]

    margin = _compute_margin(config, all_items, q.slope_type, zone, flat_floor)

    comm_rate = (q.commission_rate_override if q.commission_rate_override is not None
                 else config.commission_rate(q.slope_type, zone))
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
            effective_oh = oh + wood_adder
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
        tear_off = config.low_slope_tear_off_cost()
        items.append(LineItem("tear_off", "Tear-Off", tear_off * q.layers_to_remove * sq, "Labor"))

    if q.deck_type and q.deck_type != "existing_concrete":
        deck_cost = config.low_slope_deck_cost(q.deck_type)
        items.append(LineItem("deck_type", "Deck Replacement", deck_cost * sq, "Materials"))

    if q.include_insulation:
        ins_cost = config.low_slope_insulation_cost(sq)
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
