"""Pricing config schema, loader, and RFC 8785 hash computation.

PricingConfig is the single source of truth for all rates — zero hard-coded constants
in the engine. Loaded from JSONB (DB) or a fixture dict; never written back.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import jcs


class ConfigError(Exception):
    """Raised when a required config field is null/missing and the code path exercises it."""


class ConfigValidationError(ConfigError):
    """Raised when the config dict is structurally invalid (missing required keys)."""


# ---------------------------------------------------------------------------
# Required top-level keys (must be present and non-null at load time).
# Low-slope sub-keys are allowed to be null (they raise ConfigError at access).
# ---------------------------------------------------------------------------
_REQUIRED_KEYS = [
    "schema_version",
    "exhibit_version",
    "boundary_inclusive_lower",
    "boundary_exclusive_upper",
    "zones",
    "counties",
    "county_overrides",
    "sloped_base_cost_lm",
    "sloped_overhead",
    "profit_scale",
    "cost_category_tags",
    "profit_floor_pct",
    "profit_plus_oh_floor_pct",
    "floor_excluded_categories",
    "commission_pct",
    "pm_incentive",
    "roof_height",
    "roof_height_3_5_flat_add",
    "roof_cuts",
    "tile_pointing",
    "specialty_tile_upgrade",
    "pitch_7_12_add",
    "tile_demo_add",
    "metal_demo_add",
    "secondary_water_barrier_add",
    "winterguard_add",
    "stucco_metal_per_lf",
    "penetration_each",
    "ridge_vent_per_lf",
    "delivery_plywood_vents",
    "new_bonus_values",
    "permit_processing",
    "permit_commercial_add",
    "tile_dumpster_cost",
    "tile_dumpster_threshold",
    "tile_dumpster_boundary_inclusive",
    "line_items",
    "low_slope",
]


@dataclass
class PricingConfig:
    """Typed wrapper around the raw pricing config dict.

    All accessors return values directly from the raw dict so there is no
    translation layer that could silently absorb a future schema change.
    The raw dict is the single source of truth; this class is a thin validated
    wrapper with named accessor helpers.
    """

    raw: dict[str, Any]

    # Convenience shorthands populated at construction
    schema_version: int = field(init=False)
    exhibit_version: str = field(init=False)
    boundary_inclusive_lower: bool = field(init=False)
    boundary_exclusive_upper: bool = field(init=False)

    def __post_init__(self) -> None:
        self.schema_version = self.raw["schema_version"]
        self.exhibit_version = self.raw["exhibit_version"]
        self.boundary_inclusive_lower = self.raw["boundary_inclusive_lower"]
        self.boundary_exclusive_upper = self.raw["boundary_exclusive_upper"]

    # ------------------------------------------------------------------ #
    # Safe null-checking accessor                                          #
    # ------------------------------------------------------------------ #
    def get_or_raise(self, value: Any, context: str) -> Any:
        """Return value if non-null, else raise ConfigError naming the context."""
        if value is None:
            raise ConfigError(
                f"Config field is null and required for this code path: {context}. "
                "Supply a value or confirm with Tim (see tim_verify_open_items)."
            )
        return value

    # ------------------------------------------------------------------ #
    # Sloped rate accessors                                                #
    # ------------------------------------------------------------------ #
    def sloped_base(self, zone: str, roof_type: str) -> float:
        return self.raw["sloped_base_cost_lm"][zone][roof_type]

    def sloped_overhead(self, zone: str, roof_type: str) -> float:
        return self.raw["sloped_overhead"][zone][roof_type]

    def zoned_add(self, key: str, zone: str) -> float:
        """A per-square adder that Tim prices per office tab, tolerating the legacy scalar.

        These four shipped as bare scalars carrying the HVHZ (Miami) value while every price
        around them was zone-keyed, so FBC jobs silently took Miami's number — 7/12+ billed
        $200/sq where his FBC tab says $305. Verified against the live sheet 2026-07-25:

            7/12+ add    HVHZ $200   FBC $305
            tile demo    HVHZ  $40   FBC  $30
            metal demo   HVHZ  $60   FBC  $45
            WinterGuard  HVHZ $140   FBC $150

        Both shapes load so a config predating the split still prices (it just keeps the old
        single value for both zones) — no migration is required to deploy this.
        """
        val = self.raw[key]
        if not isinstance(val, dict):
            return float(val)
        if zone not in val:
            # An admin who edits this to a one-zone dict would otherwise KeyError at quote time,
            # and the route only maps (ValueError, ConfigError) — so it escaped as a bare 500
            # with no message. ConfigError is what the route turns into a readable 422.
            raise ConfigError(
                f"{key} has no entry for zone {zone!r} (has: {', '.join(sorted(val))}). "
                f"Add {zone} to {key} in the pricing config."
            )
        return float(val[zone])

    def cuts_calc(self) -> Optional[dict]:
        """Return the RoofR cut-calculator config (rounding/coeff/fixed/standard_tile), or None.

        Present only in configs seeded with Tim's Custom Tile Calc decode. When absent, the
        estimator falls back to the flat sloped_base — preserving legacy behavior.
        """
        return self.raw.get("cuts_calc")

    def profit_per_sq(self, num_squares: float) -> float:
        """Sliding-scale profit lookup using boundary_inclusive_lower / boundary_exclusive_upper.

        Tiers are pairs [max_sq, profit_per_sq] where max_sq is the upper bound of the tier
        (null = catch-all). The boundary flags control whether the boundary value falls in the
        tier BELOW (lower-inclusive/upper-exclusive default) or the tier ABOVE.

        With boundary_inclusive_lower=True, boundary_exclusive_upper=True (default):
          tier covers [prev_max, max_sq) — i.e. prev_max <= sq < max_sq
        """
        scale = self.raw["profit_scale"]
        lower_inc = self.boundary_inclusive_lower
        upper_exc = self.boundary_exclusive_upper

        prev_max_f: float = 0.0
        for entry in scale:
            max_sq, profit = entry[0], entry[1]
            if max_sq is None:
                # Catch-all tier: everything not yet matched
                return float(profit)
            max_sq_f = float(max_sq)

            # Lower bound check: prev_max_f is the start of this tier
            if lower_inc:
                lower_ok = num_squares >= prev_max_f
            else:
                lower_ok = num_squares > prev_max_f

            # Upper bound check
            if upper_exc:
                upper_ok = num_squares < max_sq_f
            else:
                upper_ok = num_squares <= max_sq_f

            if lower_ok and upper_ok:
                return float(profit)

            prev_max_f = max_sq_f

        # Unreachable when config is well-formed (null catch-all tier always matches).
        return float(scale[-1][1])  # pragma: no cover

    # ------------------------------------------------------------------ #
    # Commission                                                           #
    # ------------------------------------------------------------------ #
    def commission_rate(self, slope_type: str, zone: str) -> float:
        """Return commission rate for the given slope_type and zone.

        slope_type: "sloped" | "low_slope"
        zone: "HVHZ" | "FBC"

        sloped_HVHZ is an open item; defaults to sloped (0.10) until Tim confirms.
        """
        cp = self.raw["commission_pct"]
        if slope_type == "low_slope":
            return float(cp["low_slope"])
        # sloped — check for sloped_hvhz override
        sloped_hvhz = cp.get("sloped_hvhz")
        if slope_type == "sloped" and zone == "HVHZ" and sloped_hvhz is not None:
            return float(sloped_hvhz)
        return float(cp["sloped"])

    # ------------------------------------------------------------------ #
    # PM incentive                                                         #
    # ------------------------------------------------------------------ #
    def pm_incentive(self, zone: str, project_kind: str, num_squares: float) -> float:
        """Return the PM incentive, keyed the way Tim's LIVE sheet keys it — per zone.

        The two zones use DIFFERENT axes, and reading them as one matrix is what produced the
        earlier defect where a 35-square residential Palm Beach job took $50 instead of $100:

            Miami / HVHZ  (N7:O8)  -> by PROJECT KIND only.  Residential $150, Commercial $300.
                                      No size dimension at all: $150 holds at any size.
            Palm Beach / FBC (N7:O9) -> by SIZE only.  <20 $50, 20-50 $100, >50 $250.
                                      No residential/commercial split: the bands apply to both.

        `basis` says which axis a zone uses, so neither zone inherits an axis its sheet does not
        have. Legacy `residential_lt20` / `commercial_*` blocks still resolve, for configs seeded
        before 2026-07-26.
        """
        matrix = self.raw["pm_incentive"]
        zone_matrix = matrix.get(zone)
        if zone_matrix is None:
            raise ConfigError(
                f"pm_incentive has no entry for zone '{zone}'. "
                "Add it to the config or verify the zone value."
            )
        if project_kind not in ("residential", "commercial"):
            raise ConfigError(
                f"pm_incentive: unknown project_kind='{project_kind}'. "
                "Expected 'residential' or 'commercial'."
            )

        basis = zone_matrix.get("basis")
        if basis == "project_kind":
            val = zone_matrix.get(project_kind)
            if val is None:
                raise ConfigError(
                    f"pm_incentive: zone '{zone}' is keyed by project kind and has no "
                    f"'{project_kind}' amount."
                )
            return float(val)

        if basis == "size":
            for max_sq, amount in zone_matrix.get("bands") or []:
                if max_sq is None or num_squares <= max_sq:
                    return float(self.get_or_raise(amount, f"pm_incentive[{zone}].bands"))
            raise ConfigError(
                f"pm_incentive: zone '{zone}' size bands do not cover {num_squares} squares."
            )

        # --- legacy shape, pre-2026-07-26 ---
        if project_kind == "residential":
            key = ("residential_gte20" if num_squares >= 20 and "residential_gte20" in zone_matrix
                   else "residential_lt20")
        elif 20 <= num_squares <= 50:
            key = "commercial_20_50"
        elif num_squares > 50:
            key = "commercial_gt50"
        else:
            raise ConfigError(
                f"pm_incentive: no commercial band for zone='{zone}', "
                f"num_squares={num_squares} (<20 SQ commercial has no PM incentive band). "
                "Check project_kind."
            )
        val = zone_matrix.get(key)
        if val is None:
            raise ConfigError(
                f"pm_incentive: cell zone='{zone}', key='{key}' is null. "
                "Tim must confirm the amount for this band."
            )
        return float(val)

    def tile_dumpster_count(self, num_squares: float, zone: str) -> int:
        """Return number of dumpsters needed.

        tile_dumpster_boundary_inclusive=True  (default): ceil(sq / threshold)
          — reaching exactly the threshold starts a new dumpster count.
        tile_dumpster_boundary_inclusive=False (exclusive): floor(sq / threshold)
          — exactly-on-threshold does NOT start a new dumpster; only sq strictly
          above a multiple of threshold triggers the next count.
        """
        import math
        threshold = float(self.raw["tile_dumpster_threshold"][zone])
        if num_squares <= 0:
            return 0
        inclusive = self.raw.get("tile_dumpster_boundary_inclusive", True)
        if inclusive:
            return math.ceil(num_squares / threshold)
        else:
            return math.floor(num_squares / threshold)

    # ------------------------------------------------------------------ #
    # Low-slope accessors (raise ConfigError on null)                     #
    # ------------------------------------------------------------------ #
    def low_slope_base(self, zone: str, roof_type: str) -> float:
        val = self.raw["low_slope"]["base_cost_lm"][zone].get(roof_type)
        return self.get_or_raise(val, f"low_slope.base_cost_lm[{zone}][{roof_type}]")

    def low_slope_overhead(self, zone: str, oh_key: str) -> float:
        val = self.raw["low_slope"]["overhead"][zone].get(oh_key)
        return self.get_or_raise(val, f"low_slope.overhead[{zone}][{oh_key}]")

    def is_all_in(self, roof_type: str) -> bool:
        """Return True when the system price is all-in (OH+profit already included).

        All-in systems are listed in low_slope.all_in_systems. The engine must NOT
        add overhead or profit on top when this returns True.
        """
        return roof_type in self.raw["low_slope"].get("all_in_systems", [])

    def wood_deck_oh_adder(self) -> float:
        """Return the per-sq OH adder applied when deck_type is a wood variant ($50).

        Returns 0 if the key is absent so callers can always add without a None check.
        """
        return float(self.raw["low_slope"].get("wood_deck_oh_adder") or 0)

    #: legacy `insulation_tiers` rows, in the order Tim's sheet lists them (cells K15/K16/K17).
    INSULATION_THICKNESSES = ("1in", "1_5in", "2in")

    def low_slope_insulation_cost(self, thickness: str = "1in") -> float:
        """Return the per-sq insulation cost for a board THICKNESS.

        Tim keys these on thickness, not job size: 1" $255 / 1.5" $275 / 2" $310 (K15/K16/K17).
        The old schema was `insulation_tiers = [[max_sq, price], ...]`, a job-size breakpoint shape.
        Because thickness is not size, every row was written with `max_sq: null`, so the lookup
        returned on the first row and **every low-slope job priced at the 1" rate** — the $275 and
        $310 rows were unreachable and no input selected between them. Silent under-quote of
        $20-55/sq on any 1.5" or 2" spec.

        Reads `insulation_by_thickness` when present; otherwise maps the legacy null-bounded
        `insulation_tiers` rows positionally, which is exactly what their own config note says they
        mean ("type-based not sq-range-based").
        """
        ls = self.raw["low_slope"]
        by_thickness = ls.get("insulation_by_thickness")
        if not by_thickness:
            tiers = ls.get("insulation_tiers") or []
            if not tiers:
                raise ConfigError(
                    "low_slope insulation is unpriced: set low_slope.insulation_by_thickness "
                    "{1in, 1_5in, 2in} from Tim's sheet (K15/K16/K17)."
                )
            by_thickness = {
                name: row[1]
                for name, row in zip(self.INSULATION_THICKNESSES, tiers)
                if row and row[1] is not None
            }
        if thickness not in by_thickness:
            raise ConfigError(
                f"low_slope insulation thickness {thickness!r} is not priced. "
                f"Known: {sorted(by_thickness)}."
            )
        return float(self.get_or_raise(
            by_thickness[thickness], f"low_slope.insulation_by_thickness[{thickness}]"
        ))

    def low_slope_tear_off_total(self) -> float:
        """Full per-sq, per-layer low-slope tear-off cost.

        Tim's sheet (M15-N18) breaks a layer into additional hauling $20 + labor $20 + OH $35 = $75,
        and notes "$75 extra per layer". The engine previously charged only
        `tear_off_per_layer_per_sq` ($20) and left `tear_off_extras` unread, billing ~27% of the
        configured cost. Sums the numeric components of tear_off_extras when present; falls back to
        the single scalar for configs that predate the block.
        """
        extras = self.raw["low_slope"].get("tear_off_extras") or {}
        components = [v for k, v in extras.items()
                      if not k.startswith("_") and isinstance(v, (int, float))]
        if components:
            return float(sum(components))
        return self.low_slope_tear_off_cost()

    def low_slope_tapered_cost(self) -> float:
        val = self.raw["low_slope"]["tapered_cost_per_sq"]
        return self.get_or_raise(val, "low_slope.tapered_cost_per_sq")

    def low_slope_tear_off_cost(self) -> float:
        val = self.raw["low_slope"]["tear_off_per_layer_per_sq"]
        return self.get_or_raise(val, "low_slope.tear_off_per_layer_per_sq")

    # ------------------------------------------------------------------ #
    # v2: Day-based overhead + flat profit mode                           #
    # ------------------------------------------------------------------ #
    def daily_overhead_rates(self) -> dict[str, float]:
        """Return the per-series daily overhead rate map, scaled to THIS office's daily burn.

        Overhead is not a per-square price. Tim computes it as the office's gross daily cost of
        being in business, divided across the working days a job consumes — so it is a property
        of the BRANCH, not the roof. His sheet states it as `OH Basis = office daily burn / men`,
        and multiplying back out gives the burn per office:

            Jupiter  4x$345 = 7x$200 = 10x$140  ~= $1,390/day
            Miami    9x$460 = 12x$345 = 15x$275 ~= $4,140/day

        The per-series rates he emailed 2026-07-24 ($1,050 demo / $745 tile / $700 shingle /
        $850 metal) came with his 30 time-learning homes, all Palm Beach County — i.e. they are
        JUPITER's rates. They were being applied to every branch, so Miami quoted overhead at
        roughly a third of what that office actually costs to run.

        What scales is the BASIS (burn / men), not the burn. Miami burns 2.98x Jupiter but also
        runs bigger crews (9/12/15 men vs 4/7/10), so the same roof finishes in fewer days and
        the two effects partly cancel: his published per-square OH differs by only 1.73x
        ($345/man-day vs $200). Scaling on burn alone double-counts the crew and quoted a 30 SQ
        Miami tile roof at $1,622/sq against a $1,228/sq sold median.

        `office_daily_overhead` and `office_men` are therefore the per-branch admin inputs; the
        rates scale by their quotient against `office_oh_basis_reference` (the $/man-day of the
        office the base rates were measured in — Jupiter at 7 men, $200). Jupiter scales by 1.0
        and keeps Tim's emailed numbers to the dollar.

        Absent any key, rates pass through unscaled — a config predating this loads unchanged.
        """
        rates = dict(self.raw.get("daily_overhead_rates") or {})
        burn = self.raw.get("office_daily_overhead")
        men = self.raw.get("office_men")
        reference = self.raw.get("office_oh_basis_reference")
        if not rates or not burn or not men or not reference:
            return rates
        factor = (float(burn) / float(men)) / float(reference)
        return {series: round(rate * factor, 2) for series, rate in rates.items()}

    def office_daily_overhead(self) -> Optional[float]:
        """This branch's gross daily cost of doing business, or None when unset."""
        val = self.raw.get("office_daily_overhead")
        return float(val) if val else None

    def profit_mode_default(self) -> str:
        """Return 'scale' (default) or 'flat' — the tenant's default profit mode."""
        return str(self.raw.get("profit_mode_default") or "scale")

    def weekly_profit_floor(self) -> float:
        """Minimum profit per on-site week ($2,500)."""
        return float(self.raw.get("weekly_profit_floor") or 2500.0)

    def enforce_profit_floor(self) -> bool:
        """True when the profit floor MOVES THE PRICE instead of only warning.

        Tim, 2026-07-17 Zoom [08:52]: "i like to make 2500 bucks a week that we're on the job
        ... and if it's one day it still counts as one week and i'm still gonna charge 2500
        bucks minimum on re-roofs". The floor is per JOB and per WEEK ON THAT JOB — five
        separate one-day jobs are five separate $2,500 minimums, not one shared week.

        The amount is `weekly_profit_floor` x on-site weeks (see compute_profit_guidance's
        effective_floor); this flag only decides whether we enforce it or merely flag it.
        """
        return bool(self.raw.get("enforce_profit_floor"))

    def profit_floor_basis(self) -> str:
        """What the enforced floor is measured against: "job" (default) or "weekly".

        "job"    — one flat `job_profit_floor` per job however long it runs. Jon's call
                   2026-07-25 after seeing the alternative reprice 17 of Tim's 29 homes.
        "weekly" — `weekly_profit_floor` x on-site weeks. Follows from Tim's "$2,500 a week
                   that we're on the job", but he never said "$5,000 on a two-week job" out
                   loud, and most of his re-roofs run 7-10 days, so the multiple would fire on
                   nearly every normal tile job. Flip to this only if he confirms it.

        The weekly figure is still computed and returned as guidance either way — the estimator
        sees it, it just doesn't move the price unless this says so.
        """
        return str(self.raw.get("profit_floor_basis") or "job")

    def profit_floor_days_per_week(self) -> float:
        """Working days per week used to convert job days into billable weeks. Default 6.

        Crews work Monday-Saturday, so 6. ⚠️ Assumed, pending Tim — 5, 6 or 7 changes which
        jobs cross into a second week and therefore owe a second $2,500.
        """
        return float(self.raw.get("profit_floor_days_per_week") or 6)

    def job_profit_floor(self) -> float:
        """Absolute minimum profit per job ($2,500), regardless of size."""
        return float(self.raw.get("job_profit_floor") or 2500.0)

    def daily_oh_weeks_rounding(self) -> str:
        """'ceil' (default) or 'floor' — how total series days map to on-site weeks."""
        return str(self.raw.get("daily_overhead_weeks_rounding_mode") or "ceil")

    def daily_overhead_day_model(self) -> dict[str, Any]:
        """Return the fitted days-from-squares model (docs/ROOFR_OVERHEAD_TIERS.md).

        Shape: {"demo_series": str,
                "install_series_by_roof_type": {roof_type: series},
                "series": {series: {"setup": days, "rate": days_per_sq}}}
        Empty dict when unconfigured — callers then leave labor days manual.
        """
        return dict(self.raw.get("daily_overhead_day_model") or {})

    # ------------------------------------------------------------------ #
    # v2: Repair options (time-based pricing, Zoom 2026-07-20 [37:04]/[45:31]) #
    # ------------------------------------------------------------------ #
    def repair_roof_types(self) -> list[str]:
        """Valid roof-type categories for a repair quote (shingle/tile/metal/flat)."""
        return list((self.raw.get("repair") or {}).get("roof_types") or [])

    def repair_daily_labor_rate(self, crew_size: int) -> float:
        """Daily labor rate for a repair crew ($/day), keyed by crew size (1 or 2 men).

        Raises ConfigError if the rate for this crew size is null/missing.
        """
        rates = (self.raw.get("repair") or {}).get("daily_labor_rate") or {}
        key = "two_man" if crew_size == 2 else "one_man"
        val = rates.get(key)
        return self.get_or_raise(val, f"repair.daily_labor_rate.{key}")

    def low_slope_deck_cost(self, deck_type: str) -> float:
        val = self.raw["low_slope"]["deck_types"].get(deck_type)
        if val is None and deck_type != "existing_concrete":
            raise ConfigError(
                f"low_slope.deck_types[{deck_type}] is null. "
                "Tim must supply the deck replacement cost."
            )
        return float(val or 0)


# ---------------------------------------------------------------------------
# Loader and hash
# ---------------------------------------------------------------------------

def _strip_pending_keys(d: Any) -> Any:
    """Recursively remove keys starting with '_' (documentation/pending annotations)."""
    if isinstance(d, dict):
        return {k: _strip_pending_keys(v) for k, v in d.items() if not k.startswith("_")}
    if isinstance(d, list):
        return [_strip_pending_keys(v) for v in d]
    return d


def _coerce_for_jcs(d: Any) -> Any:
    """Recursively coerce Decimal → fixed-point string so jcs.canonicalize doesn't crash.

    jcs requires JSON-native types (str/int/float/bool/None/list/dict); Decimal is
    NOT one, so it must be serialised (4dp fixed-point, matching price_book._canon).
    float IS JSON-native and is left UNTOUCHED on purpose — coercing it would change
    the hash of every existing float-valued pricing config and retro-break already-
    pinned estimates. Callers that need Decimal money in the hash pass Decimals.
    """
    if isinstance(d, bool):
        return d
    if isinstance(d, Decimal):
        return format(d.quantize(Decimal("0.0001")), "f")
    if isinstance(d, dict):
        return {k: _coerce_for_jcs(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_coerce_for_jcs(v) for v in d]
    return d


def compute_hash(config_dict: dict) -> str:
    """Compute RFC 8785 canonical JSON + SHA-256 hex digest.

    Strips underscore-prefixed annotation keys before hashing so pending/meta
    fields in the fixture don't affect the hash. Coerces Decimal/float values
    to fixed-point strings before canonicalization (jcs requires JSON-native types).
    """
    clean = _strip_pending_keys(config_dict)
    coerced = _coerce_for_jcs(clean)
    canon: bytes = jcs.canonicalize(coerced)
    return hashlib.sha256(canon).hexdigest()


def compute_snapshot_hash(snapshot_dict: dict) -> str:
    """Hash a proposal snapshot WITHOUT stripping underscore-prefixed keys.

    Used by freeze_quote_snapshot — pinned price tables are stored under plain
    keys (no underscore prefix) so this is equivalent to compute_hash for
    correctly-structured snapshots. Kept separate so the intent is explicit:
    snapshot data must NEVER use underscore-prefixed keys for content that
    should be hashed.
    """
    coerced = _coerce_for_jcs(snapshot_dict)
    canon: bytes = jcs.canonicalize(coerced)
    return hashlib.sha256(canon).hexdigest()


def load_config(raw: dict) -> PricingConfig:
    """Validate and wrap a raw config dict. Raises ConfigValidationError on schema errors."""
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise ConfigValidationError(
            f"Pricing config is missing required keys: {missing}"
        )
    return PricingConfig(raw=raw)
