"""Pricing config schema, loader, and RFC 8785 hash computation.

PricingConfig is the single source of truth for all rates — zero hard-coded constants
in the engine. Loaded from JSONB (DB) or a fixture dict; never written back.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

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
        """Return PM incentive amount; raises ConfigError on unmatched cell."""
        matrix = self.raw["pm_incentive"]
        zone_matrix = matrix.get(zone)
        if zone_matrix is None:
            raise ConfigError(
                f"pm_incentive has no entry for zone '{zone}'. "
                "Add it to the config or verify the zone value."
            )

        if project_kind == "residential":
            if num_squares < 20:
                key = "residential_lt20"
            else:
                raise ConfigError(
                    f"pm_incentive: no residential band for zone='{zone}', "
                    f"num_squares={num_squares} (≥20 SQ residential has no PM incentive band). "
                    "Check project_kind — large residential jobs may be commercial."
                )
        elif project_kind == "commercial":
            if 20 <= num_squares <= 50:
                key = "commercial_20_50"
            elif num_squares > 50:
                key = "commercial_gt50"
            else:
                raise ConfigError(
                    f"pm_incentive: no commercial band for zone='{zone}', "
                    f"num_squares={num_squares} (<20 SQ commercial has no PM incentive band). "
                    "Check project_kind."
                )
        else:
            raise ConfigError(
                f"pm_incentive: unknown project_kind='{project_kind}'. "
                "Expected 'residential' or 'commercial'."
            )

        val = zone_matrix.get(key)
        if val is None:
            raise ConfigError(
                f"pm_incentive: cell zone='{zone}', key='{key}' is null. "
                "Tim must confirm the amount for this band."
            )
        return float(val)

    # ------------------------------------------------------------------ #
    # Tile dumpster                                                        #
    # ------------------------------------------------------------------ #
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

    def low_slope_insulation_cost(self, num_squares: float) -> float:
        tiers = self.raw["low_slope"]["insulation_tiers"]
        if not tiers:
            raise ConfigError(
                "low_slope.insulation_tiers is empty. "
                "Tim must supply tiered insulation cost-per-sq breakpoints."
            )
        for max_sq, cost_per_sq in tiers:
            if max_sq is None or num_squares <= max_sq:
                return float(cost_per_sq)
        return float(tiers[-1][1])

    def low_slope_tapered_cost(self) -> float:
        val = self.raw["low_slope"]["tapered_cost_per_sq"]
        return self.get_or_raise(val, "low_slope.tapered_cost_per_sq")

    def low_slope_tear_off_cost(self) -> float:
        val = self.raw["low_slope"]["tear_off_per_layer_per_sq"]
        return self.get_or_raise(val, "low_slope.tear_off_per_layer_per_sq")

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


def compute_hash(config_dict: dict) -> str:
    """Compute RFC 8785 canonical JSON + SHA-256 hex digest.

    Strips underscore-prefixed annotation keys before hashing so pending/meta
    fields in the fixture don't affect the hash.
    """
    clean = _strip_pending_keys(config_dict)
    canon: bytes = jcs.canonicalize(clean)
    return hashlib.sha256(canon).hexdigest()


def load_config(raw: dict) -> PricingConfig:
    """Validate and wrap a raw config dict. Raises ConfigValidationError on schema errors."""
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise ConfigValidationError(
            f"Pricing config is missing required keys: {missing}"
        )
    return PricingConfig(raw=raw)
