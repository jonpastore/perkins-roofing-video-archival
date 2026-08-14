"""Estimator routes — roofing bid calculator (F2).

Endpoints:
  POST  /estimator/quote    compute estimate using active config + stamp hash
  GET   /estimator/rates    rate tables from active config (config-driven in F2)
  POST  /estimator/scope-of-work/rewrite   AI-rewrite a scope-of-work template

Role requirements (core.authz):
  estimating_view  → POST /estimator/quote, GET /estimator/rates,
                     POST /estimator/scope-of-work/rewrite
  estimating_manage → config CRUD (lives in api/routes/pricing_configs.py)
"""
from dataclasses import replace
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import can, get_db_session, require_role
from app.models import BidProject, Estimate, Measurement, PricingConfig, Property
from core import bid_project as BP
from core import estimator as E
from core import scope_of_work as SOW
from core.discounts import resolve_discounts
from core.estimator import DailyOverheadSeries, RepairInput
from core.pricing_config import ConfigError, load_config


class DailySeriesItem(BaseModel):
    series: str
    days: float = Field(..., gt=0)

    @field_validator("days")
    @classmethod
    def days_must_be_half_increment(cls, v: float) -> float:
        remainder = round(v % 0.5, 10)
        if remainder != 0.0:
            raise ValueError(
                f"days must be a multiple of 0.5 (half-day increments); got {v!r}"
            )
        return v


class DiscountInput(BaseModel):
    description: str = "Discount"
    amount: Optional[float] = Field(default=None, ge=0)
    discount_type: Literal["amount", "percent"] = "amount"
    value: Optional[float] = Field(default=None, ge=0)
    percent: Optional[float] = Field(default=None, ge=0, le=100)

class RepairQuoteRequest(BaseModel):
    branch: str = Field(default="miami", max_length=100)  # see QuoteRequest.branch
    # roof_type is config-driven (repair.roof_types), not a Literal — a static enum here would
    # 422 on a new category Tim adds to config without a code deploy (see roof_type on
    # QuoteRequest above for the same fix, and its history).
    roof_type: str = Field(..., max_length=40)
    days: float = Field(..., gt=0)
    crew_size: Literal[1, 2] = 1
    material_cost: float = Field(default=0, ge=0)
    # Same mechanism/naming as QuoteRequest's percent_profit_pct (Jarvis #432/#434) — a
    # fraction, 0.20 = 20%. Omitted = 0.0; the min_profit_dollars/min_service_call_dollars
    # floors in core.estimator.estimate_repair still apply regardless.
    percent_profit_pct: Optional[float] = Field(default=None, ge=0)
    config_id: Optional[int] = None      # null = use active config; explicit = pin to version


class ScopeOfWorkRewriteRequest(BaseModel):
    template: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1)
    job_context: Optional[dict] = None


router = APIRouter(prefix="/estimator", tags=["estimator"])

# Low-slope systems route to the low-slope calculator regardless of the slope_type
# flag, so a caller can never mismatch roof_type and calculator.
LOW_SLOPE_ROOF_TYPES = frozenset({"tpo", "coatings", "silicone", "bur"})


def _audit_payload(result: dict, *, debug: bool = False) -> dict:
    """Strip the debug trace before an estimate is persisted — unless *debug* was requested.

    HONOURS THE FLAG (2026-08-12). This used to strip unconditionally, so a manager who asked for
    debug got the trace in the response and then found it gone from the saved row, and from any
    proposal built off it. The reason given was confidentiality, and THAT REASON DOES NOT SURVIVE
    CHECKING:

      * `GET /estimator/rates` (:1196) is gated on **estimating_view** — the role `sales` holds —
        and returns `profit_scale`, `pm_incentive`, `overhead` and `base_cost_lm` in the clear.
        Those are the exact fields the old docstring named as the things worth hiding.
      * `core/estimator.py to_dict()` emits `margin` (profit_dollars, oh_dollars, eligible_base),
        `pm_incentive`, `profit_dollars`, `profit_pct` and `commission` UNCONDITIONALLY. Only
        `calculation_trace` and per-line `explain` are gated on debug at all.

    So the strip was removing the EXPLANATION while leaving every NUMBER it explains, for an
    audience that could already read both. It bought no confidentiality; it only made the feature
    not work.

    *debug* must be the RESOLVED flag (`q.debug`), not the raw request field. It is already
    ``bool(body.debug) and can(role, "estimating_manage")`` (:387), so a `sales` caller who sends
    debug=true still gets a stripped row — the gate lives there, once, rather than being
    re-derived here where it could drift.

    What the strip still buys, and why it remains the default: row size (~2x JSONB) and uniform
    audit-row shape. Callers with no request context — notably
    `api/routes/proposals._freeze_calc_breakdown` — pass nothing and keep the old behaviour.
    """
    if debug:
        # Copy, never the caller's own dict: the quote route mutates `result` (estimate_id,
        # estimate_root_id, estimate_version) between the two calls at :775 and :786, and aliasing
        # it into est.result_json would let those writes land in the ORM object unannounced.
        return dict(result)
    stripped = {k: v for k, v in result.items() if k != "calculation_trace"}
    detail = stripped.get("line_items_detail")
    if isinstance(detail, list):
        stripped["line_items_detail"] = [
            {k: v for k, v in li.items() if k != "explain"} if isinstance(li, dict) else li
            for li in detail
        ]
    return stripped


# Profit is an internal number. quoting_view / estimating_view (the roles sales holds)
# must not read it on the wire. Strip on READ, same shape as
# proposals._snapshot_without_internal_calc — persist stays intact so a manager
# can still reconcile. ~30 lines; the three exposures this closes are listed in
# docs/PRODUCTION_CUTOVER_PLAN.md §3.
_PROFIT_KEYS = frozenset({
    "profit_dollars", "profit_pct", "margin", "commission", "estimated_commission",
    "profit_guidance",
})


def _without_profit(payload):
    """Drop profit dollars / margin / commission from a response or snapshot."""
    if not isinstance(payload, dict):
        return payload
    out = {}
    for key, value in payload.items():
        if key in _PROFIT_KEYS:
            continue
        if key == "line_items_detail" and isinstance(value, list):
            out[key] = [
                li for li in value
                if not (isinstance(li, dict) and li.get("key") == "profit")
            ]
            continue
        if key == "line_items" and isinstance(value, dict):
            out[key] = {ik: iv for ik, iv in value.items() if ik != "profit"}
            continue
        if key == "calc_lines_internal":
            continue
        if key == "calc_lines" and payload.get("calc_audience") == "internal":
            continue
        if key in ("estimate_result", "quote_snapshot", "result_json") and isinstance(value, dict):
            out[key] = _without_profit(value)
            continue
        out[key] = value
    return out


def _public_estimate(payload: dict, claims: dict) -> dict:
    """The estimate a caller is allowed to see."""
    if can(claims.get("role"), "estimating_manage"):
        return payload
    return _without_profit(payload)


def _get_active_config_row(branch: str, db: Session) -> Optional[PricingConfig]:
    """Fetch the active PricingConfig row for (current tenant, branch), or None."""
    return db.execute(
        select(PricingConfig).where(
            PricingConfig.tenant_id == db.info["tenant_id"],
            PricingConfig.branch == branch,
            PricingConfig.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class QuoteRequest(BaseModel):
    # max_length tracks bid_projects.branch VARCHAR(100) (migration 0052) — the strictest DB bound
    # on a column of this name. estimates.branch is an unbounded String, so this was unconstrained
    # until a project quote started writing the same value into bid_projects, where an over-long
    # branch would 500 on Postgres and pass silently on SQLite.
    branch: str = Field(default="miami", max_length=100)
    code_zone: Literal["HVHZ", "FBC"] = "HVHZ"
    # 100 to match properties.county — the longest US county name is well under it, and an
    # unbounded value 500s on Postgres while passing every SQLite test (the bug 16a662b shipped).
    county: Optional[str] = Field(default=None, max_length=100)
    slope_type: Literal["sloped", "low_slope"] = "sloped"
    # roof_type keys are config-driven (exhibit_b uses granular low-slope system keys like
    # `tpo_adhered`, `pb_silicone_2coat`); a static Literal can't enumerate them, so validate
    # at the boundary with a length cap and let the engine's ConfigError guard unknown keys (→422).
    roof_type: str = Field(default="13_tile", max_length=40)
    num_squares: float = Field(..., gt=0)
    # A roof with both sections is one job. Tim's own sheet has a "Squares (Flat)" column.
    #
    # NULLABLE ON PURPOSE, and the default is None rather than 0. `0` means "there is no flat
    # section"; `None` means "nobody has said". Those were the same value until 2026-08-02, which is
    # why a NULL-split measurement could not be told apart from a genuinely all-sloped roof — see
    # the split resolution in _quote_input_from_request. The engine still treats None as 0.0.
    flat_squares: Optional[float] = Field(default=None, ge=0)
    flat_roof_type: Optional[str] = Field(default=None, max_length=40)
    roof_cuts: Literal["low", "medium", "high"] = "low"
    roof_cuts_per_sq: Optional[float] = Field(default=None, ge=0)  # explicit $/sq overrides the pick
    # Accessibility: MANUAL dollars, never a tier (Tim 2026-07-27 20:36). roof_cuts_per_sq is the
    # per-square half; this is the flat quoted delivery/hand-load charge.
    accessibility_flat: Optional[float] = Field(default=None, ge=0)
    waterfront: bool = False   # salt exposure -> gate the COASTAL package
    roof_height: Literal["1_story", "2_stories", "3_5_stories", "6_plus"] = "1_story"
    # ── #417 low-slope inputs ────────────────────────────────────────────────────────────
    # These reach QuoteInput and nothing else. They exist here because an engine capability the
    # request model cannot express is unreachable: the first live check after deploying #417 found
    # the warranty upgrade and pressure cleaning silently absent from real quotes, because Pydantic
    # dropped the unknown keys and the engine defaulted them off. Same shape as the config-with-no-
    # reader defect #417 itself was about, one layer up.
    #: Actual storey count. roof_height is a BAND and cannot say how many trash-chute sections a
    #: job needs; absent means the engine bills the band's floor and warns.
    stories: Optional[int] = Field(default=None, ge=1, le=60)
    #: Pressure cleaning as an add-on — $30/sq flat, $40/sq sloped (sheet O1/O2).
    include_pressure_cleaning: bool = False
    #: Polyglass warranty upgrade key (low_slope.polyglass_warranty_upgrades). An unknown key is
    #: a 422 from the engine, never a silent fall back to the base warranty.
    warranty_upgrade: Optional[str] = Field(default=None, max_length=60)
    #: Silicone add-on keys (low_slope.silicone_addons) — granules, traffic coat, TPO primer.
    silicone_addons: list[str] = Field(default_factory=list, max_length=10)
    #: Extra silicone coats. Needs extra_coat_material_per_sq — L27 prices a coat as
    #: "$100 (L, OH & P) + M", and billing the labour half alone under-charges every time.
    extra_coats: int = Field(default=0, ge=0, le=10)
    extra_coat_material_per_sq: Optional[float] = Field(default=None, ge=0)
    #: Detail-item key -> quantity in the sheet's own unit (low_slope.detail_items).
    detail_items: dict[str, float] = Field(default_factory=dict)
    # ─────────────────────────────────────────────────────────────────────────────────────
    #: Poor access to part of the roof (a back slope the truck cannot reach, a tight lot). Feeds
    #: the DAY model only — accessibility_flat is the money field. #436: the single feature that
    #: moved the day model most, 83% -> 90% of homes within a day of Tim's own booked days.
    access_difficult: bool = False
    tile_pointing: Literal["no", "yes"] = "no"
    specialty_tile: Optional[str] = None
    project_kind: Literal["residential", "commercial"] = "residential"
    pitch_7_12: bool = False
    pitch_primary: float | None = Field(default=None, ge=0, le=24)   # rise per 12, e.g. 6 = 6/12
    # Estimate-debug: return the formula, variables and values behind every priced line plus the
    # section roll-ups. Ignored unless the caller holds estimating_manage — the trace exposes
    # internal config keys and roughly doubles the payload, so it is not for the sales view.
    debug: bool = False
    demo: bool = False
    secondary_water_barrier: bool = False
    winterguard: bool = False
    stucco_metal_lf: float = 0
    penetrations: int = 0
    extra_line_items: list[str] = Field(default_factory=list)
    ridge_vent_lf: float = 0
    layers_to_remove: int = 0
    existing_roof: Optional[Literal["none", "shingle", "tile", "metal", "flat"]] = None
    # RoofR cut linear-footages — feed Tim's custom cut calculator (geometry-adjusted base).
    # Explicit values win; otherwise resolved from measurement_id when given.
    eaves_lf: float = Field(default=0, ge=0)
    hips_lf: float = Field(default=0, ge=0)
    ridges_lf: float = Field(default=0, ge=0)
    valleys_lf: float = Field(default=0, ge=0)
    rakes_lf: float = Field(default=0, ge=0)
    wall_flashings_lf: float = Field(default=0, ge=0)
    base_tile_brand: Optional[str] = Field(default=None, max_length=30)
    gutter_style: Optional[str] = Field(default=None, max_length=50)
    gutter_lf: float = Field(default=0, ge=0)
    gutter_two_story: bool = False
    gutter_elbows: int = Field(default=0, ge=0)
    gutter_removal_lf: float = Field(default=0, ge=0)
    downspout_lf: float = Field(default=0, ge=0)
    leaf_guard: Literal["none", "std", "upgraded"] = "none"
    leaderheads_res: int = Field(default=0, ge=0)
    leaderheads_comm: int = Field(default=0, ge=0)
    deck_type: Optional[str] = None
    include_insulation: bool = False
    insulation_thickness: Literal["1in", "1_5in", "2in"] = "1in"
    include_tapered: bool = False
    # Plywood deck replacement — per SHEET (Tim's Lumber Schedule), any roof type, first N free.
    plywood_sheets: float = Field(default=0, ge=0)
    plywood_thickness: Literal["5_8in", "1_2in", "3_4in"] = "5_8in"
    measurement_id: Optional[int] = None
    config_id: Optional[int] = None      # null = use active config; explicit = pin to version
    override_base_cost: Optional[float] = None
    override_overhead: Optional[float] = None
    override_profit_per_sq: Optional[float] = None

    # Day-based overhead is the DEFAULT. Tim, Zoom 2026-07-17 [09:46]: "that's how we get the
    # overhead is based on time, it's not using this thing here, this is just a guide ... more of a
    # guide than it is a rule". per_sq remains available for comparison, but shipping it as the
    # default meant every quote used the number he calls a guide. Days are auto-derived from the
    # roof's geometry when the caller supplies none (see derive_daily_series).
    overhead_mode: Literal["per_sq", "daily"] = "daily"
    daily_series: list[DailySeriesItem] = Field(default_factory=list)
    # "scale" is legacy (Jarvis #432, Tim 2026-07-27) — kept only so stored old-proposal
    # snapshots still re-render. "percent" is a fraction of eligible_base (0.20 = 20%, not 20).
    profit_mode: Literal["scale", "flat", "percent"] = "scale"
    flat_profit_dollars: Optional[float] = Field(default=None, ge=0)
    percent_profit_pct: Optional[float] = Field(default=None, ge=0, le=1)
    min_profit_dollars: Optional[float] = Field(default=None, ge=0)
    commission_basis: Literal["profit", "job"] = "profit"
    commission_rate: Optional[float] = Field(default=None, ge=0, le=1)  # fraction, e.g. 0.30
    discounts: list[DiscountInput] = Field(default_factory=list)
    selected_tier: Literal["good", "better", "best"] = "good"
    parent_estimate_id: Optional[int] = None
    source_proposal_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _quote_input_from_request(body, cfg_row, db, claims):
    """Map a QuoteRequest onto a core.estimator.QuoteInput against the active config.

    Extracted from /quote so /project-quote prices each building through the EXACT same
    validation and field mapping. A second copy of this would be the real hazard: it is 110 lines
    of roof_type/specialty_tile validation, measurement-backed cut-LF resolution and ~60 field
    assignments, and a project quote that silently diverged from a single-building quote on any
    one of them would be indistinguishable from a pricing bug.

    Returns (QuoteInput, effective_slope_type, cut_lfs). `cut_lfs` comes back because /quote tests
    it to decide whether the cut-calculator comparison is worth running; `pitch_primary` does NOT,
    because it is already baked into the returned QuoteInput and no caller reads it separately.
    """
    # Route to the low-slope calculator whenever the roof_type is a low-slope system, regardless
    # of the client-sent slope_type flag. The set is config-driven (granular exhibit_b keys) plus
    # the coarse aliases so a caller can never mismatch roof_type and calculator.
    low_slope_keys = LOW_SLOPE_ROOF_TYPES | set(
        _priced_low_slope_types(cfg_row.config, body.code_zone))
    effective_slope_type = "low_slope" if body.roof_type in low_slope_keys else body.slope_type

    # roof_type is a free str at the boundary (config-driven keys), so validate it here against the
    # active config for this zone — otherwise an unknown key reaches the engine and raises KeyError
    # (an uncaught 500) instead of a clean 422. Valid = priced sloped keys + the low-slope set.
    valid_sloped = {
        k for k in ((cfg_row.config.get("sloped_base_cost_lm") or {}).get(body.code_zone) or {})
        if not k.startswith("_")
    }
    if body.roof_type not in (valid_sloped | low_slope_keys):
        raise HTTPException(
            422,
            detail=f"unknown roof_type {body.roof_type!r} for zone {body.code_zone}. "
            f"Valid: {sorted(valid_sloped | low_slope_keys)}",
        )

    # Validate specialty_tile against the active config
    if body.specialty_tile is not None and effective_slope_type == "sloped":
        valid = (cfg_row.config.get("specialty_tile_upgrade") or {}).get(body.code_zone, {})
        if not valid:
            # Schema lacks specialty_tile_upgrade — re-export from legacy with explicit TODO
            from core import _legacy_rates as _lr  # TODO(config-migrate): move to config schema
            valid = _lr.SPECIALTY_TILE_UPGRADE.get(body.code_zone, {})
        if body.specialty_tile not in valid:
            raise HTTPException(400, f"unknown specialty_tile for {body.code_zone}: {body.specialty_tile!r}")

    # Resolve RoofR cut LFs: start from the measurement (the RoofR -> estimate ingestion path)
    # when a measurement_id is supplied, then let any explicit request field override per-field.
    # Merging per-field (not all-or-nothing) means a single typed override can't silently drop
    # the measurement's other five values.
    cut_lfs = {
        "eaves_lf": body.eaves_lf, "hips_lf": body.hips_lf, "ridges_lf": body.ridges_lf,
        "valleys_lf": body.valleys_lf, "rakes_lf": body.rakes_lf,
        "wall_flashings_lf": body.wall_flashings_lf,
    }
    # Predominant pitch drives the steep-roof day adder; same explicit-wins-else-measurement rule.
    pitch_primary = body.pitch_primary
    num_squares = body.num_squares
    flat_squares = body.flat_squares
    #: True when the roof was priced against a measurement whose pitched/flat split nobody has
    #: recorded. Not an error — most legacy rows are all-sloped and price correctly — but the one
    #: state where `num_squares` might silently already contain the flat area.
    split_unknown = False
    if body.measurement_id is not None:
        m = db.get(Measurement, body.measurement_id)
        if m is None or m.tenant_id != db.info.get("tenant_id"):
            raise HTTPException(404, f"Measurement {body.measurement_id} not found")
        for field_name in cut_lfs:
            if not cut_lfs[field_name]:  # explicit field wins when non-zero; else measurement
                cut_lfs[field_name] = getattr(m, field_name) or 0
        if not pitch_primary:
            pitch_primary = m.pitch_primary

        # ── The pitched/flat split. DELIBERATELY the OPPOSITE rule to the cut LFs above. ────────
        # core/estimator.py sums `num_squares + flat_squares`, and `measurements.total_sq` is
        # AMBIGUOUS by provenance: Tim's sheet means sloped-only, a RoofR transcription means
        # pitched + flat. So a caller that sends total_sq as num_squares AND a flat figure bills
        # the flat area twice. A cut LF is a measurement an operator may reasonably correct; the
        # split is MONEY and the body demonstrably cannot be trusted to know it — that is the whole
        # defect. The operator's escape hatch is to fix the measurement, not to out-argue it per
        # quote. Measured on prod 2026-08-02: 13 of 42 measurements carry no split.
        #
        # ⚠️ SLOPED ONLY, and this guard is load-bearing. `_build_low_slope` prices
        # `base * q.num_squares` and NEVER reads `flat_squares` — the mixed-roof block is gated on
        # `q.slope_type == "sloped"` (core/estimator.py:1375). So applying a sloped roof's split to
        # a low-slope quote moves the whole area into a field that path ignores and DELETES it from
        # the price: measured on the exhibit_b fixture, a 45-square `tpo_adhered` roof resolved to
        # `num_squares=5, flat_squares=45` prices $8,250 against $35,050 — **76% under**, silent,
        # and larger per occurrence than the double-bill this block exists to prevent. On a
        # low-slope quote `num_squares` IS the flat area, so the sloped split does not apply and
        # nothing here touches it.
        #
        # `if m.pitched_sq` is truthy, not `is not None`: a measurement may legitimately record
        # `pitched_sq = 0` (a flat-only building), and assigning that would bypass the
        # `num_squares: Field(..., gt=0)` boundary guarantee and raise deeper in the engine.
        # RECORDED is not the same as NON-ZERO. A flat-only building legitimately records
        # pitched_sq = 0 (prod #16: 0 pitched / 12.67 flat), and that roof's split IS known — it
        # must not be reported as unknown, and assigning 0 to num_squares would bypass the
        # `gt=0` bound the field carries and fail deeper in the engine. So: `is not None` decides
        # whether we KNOW, and truthiness decides whether we can OVERRIDE.
        split_recorded = m.pitched_sq is not None
        if effective_slope_type == "sloped" and split_recorded and m.pitched_sq:
            num_squares = m.pitched_sq
            flat_squares = m.flat_sq or 0.0
        elif effective_slope_type == "sloped" and not split_recorded and flat_squares:
            raise HTTPException(422, detail={
                "message": (
                    "this measurement has no recorded pitched/flat split, so a separate flat "
                    "figure cannot be added to it without risking double-billing the flat area"),
                "measurement_id": body.measurement_id,
                "total_sq": m.total_sq,
                "flat_squares": flat_squares,
                "why": ("total_sq is ambiguous: on Tim's sheet it is the SLOPED area only, on a "
                        "RoofR transcription it is pitched + flat. If it already includes the "
                        "flat section, adding flat_squares bills that area twice."),
                # NOT "PATCH /measurements/{id}" — api/routes/measurements.py implements POST and
                # GET only, so that instruction would 405 the operator who followed it.
                "fix": ("re-save the measurement with its Pitched SQ and Flat SQ filled in "
                        "(POST /measurements), then quote against the new one."),
            })
        else:
            # No flat figure was offered, so nothing can double-count. The quote proceeds — but if
            # total_sq DID include a flat section it is now priced at the sloped rate, so say so
            # rather than let it pass unremarked. Only when the split is genuinely UNRECORDED:
            # a recorded 0-pitched roof is known, not unknown.
            split_unknown = not split_recorded

    # Build QuoteInput kwargs. The headline quote keeps the FLAT base (Tim's standard pricing) —
    # the cut-adjusted base is shown alongside it in the cut_calc reference block below and Tim
    # picks (his golden proposals price standard roofs off the flat base). Cut LFs ARE passed to
    # the headline quote, but with apply_cut_calc_to_base=False: they drive the geometry day
    # model without moving the base.
    # Gated on estimating_manage rather than the estimating_view every quote carries. Asking
    # without the role is not an error — the quote returns normally, minus the trace.
    # NOT a confidentiality boundary: /rates already serves profit_scale, pm_incentive and the
    # daily rates to estimating_view. The gate keeps the payload lean and the audit rows
    # uniform (see _audit_payload, which strips the trace before persistence).
    debug = bool(body.debug) and can(claims.get("role"), "estimating_manage")
    qkwargs = dict(
        debug=debug,
        code_zone=body.code_zone,
        slope_type=effective_slope_type,
        roof_type=body.roof_type,
        num_squares=num_squares,      # measurement-resolved; see the split block above
        flat_squares=flat_squares or 0.0,
        flat_roof_type=body.flat_roof_type,
        county=body.county,
        roof_cuts=body.roof_cuts,
        roof_cuts_per_sq=body.roof_cuts_per_sq,
        accessibility_flat=body.accessibility_flat,
        waterfront=body.waterfront,
        roof_height=body.roof_height,
        access_difficult=body.access_difficult,
        tile_pointing=body.tile_pointing,
        specialty_tile=body.specialty_tile,
        project_kind=body.project_kind,
        pitch_7_12=body.pitch_7_12,
        demo=body.demo,
        secondary_water_barrier=body.secondary_water_barrier,
        winterguard=body.winterguard,
        stucco_metal_lf=body.stucco_metal_lf,
        penetrations=body.penetrations,
        extra_line_items=body.extra_line_items,
        ridge_vent_lf=body.ridge_vent_lf,
        layers_to_remove=body.layers_to_remove,
        existing_roof=body.existing_roof,
        gutter_style=body.gutter_style,
        gutter_lf=body.gutter_lf,
        gutter_two_story=body.gutter_two_story,
        gutter_elbows=body.gutter_elbows,
        gutter_removal_lf=body.gutter_removal_lf,
        downspout_lf=body.downspout_lf,
        leaf_guard=body.leaf_guard,
        leaderheads_res=body.leaderheads_res,
        leaderheads_comm=body.leaderheads_comm,
        deck_type=body.deck_type,
        include_insulation=body.include_insulation,
        insulation_thickness=body.insulation_thickness,
        include_tapered=body.include_tapered,
        # #417 — see the request model. Every one of these is inert unless the caller sets it.
        stories=body.stories,
        include_pressure_cleaning=body.include_pressure_cleaning,
        warranty_upgrade=body.warranty_upgrade,
        silicone_addons=list(body.silicone_addons),
        extra_coats=body.extra_coats,
        extra_coat_material_per_sq=body.extra_coat_material_per_sq,
        detail_items=dict(body.detail_items),
        plywood_sheets=body.plywood_sheets,
        plywood_thickness=body.plywood_thickness,
        override_base_cost=body.override_base_cost,
        override_overhead=body.override_overhead,
        override_profit_per_sq=body.override_profit_per_sq,
        overhead_mode=body.overhead_mode,
        daily_series=[DailyOverheadSeries(series=s.series, days=s.days) for s in body.daily_series],
        profit_mode=body.profit_mode,
        flat_profit_dollars=body.flat_profit_dollars,
        percent_profit_pct=body.percent_profit_pct,
        min_profit_dollars=body.min_profit_dollars,
        base_tile_brand=body.base_tile_brand,
        commission_basis=body.commission_basis,
        commission_rate_override=body.commission_rate,
    )
    # The cut LFs reach the headline quote so the geometry day model can see how cut-up the roof
    # is (Tim: two 30-SQ roofs can be 2 days or 6), but apply_cut_calc_to_base=False keeps the
    # base on his flat standard pricing. Without this the day model silently evaluated every
    # quote at zero complexity and fell back to the squares-only fit.
    q = E.QuoteInput(**qkwargs, **cut_lfs, apply_cut_calc_to_base=False,
                     pitch_primary=pitch_primary)

    return q, effective_slope_type, cut_lfs, split_unknown


def _validate_quote_guards(body, config, *, where: str = "") -> None:
    """Guards that need the loaded CONFIG, so they sit outside _quote_input_from_request.

    Shared because they were NOT extracted with the mapper and /project-quote therefore skipped
    both. The gutter one is the expensive miss: core/estimator.py prices the whole accessory
    block inside `if q.gutter_lf:`, so elbows / leaf guard / 2-story uplift silently cost $0
    without it — a nine-building bid could ship under-priced with nothing in the response saying
    so. `where` names the structure, because "unknown daily_series" is unactionable on a bid with
    nine of them.
    """
    prefix = f"{where}: " if where else ""
    if (body.gutter_elbows or body.leaf_guard != "none" or body.gutter_two_story) and not body.gutter_lf:
        raise HTTPException(
            422,
            detail=f"{prefix}gutter_elbows, leaf_guard, and gutter_two_story require gutter_lf > 0.",
        )
    if body.daily_series:
        known_series = set(config.daily_overhead_rates().keys())
        unknown = [s.series for s in body.daily_series if s.series not in known_series]
        if unknown:
            raise HTTPException(
                422,
                detail=f"{prefix}unknown daily_series name(s): {unknown}. "
                f"Valid series: {sorted(known_series)}",
            )
        # Tim, 2026-08-04: "no install days is an error, 1 min required" (demo may be 0, which is
        # expressed by omitting it — DailySeriesItem already requires days > 0 per entry).
        #
        # This closes a silent under-bill: the engine derives days ONLY when daily_series arrives
        # empty, so a caller who sent demo days alone got a quote with NO install overhead at all
        # and no warning. Measured on a 20 sq HVHZ tile roof: $25,090 against the $27,050 the same
        # job prices at when the days are derived — $1,960 missing, because "blank" was read as
        # "zero" rather than "estimate it".
        # ⚠️ This reads `demo_series` to know which entry is the tear-off. A config that does not
        # declare it counts demo days AS install and the guard silently passes — which is exactly
        # how this guard's own test first went green against a 200. All three prod configs declare
        # it; if you add a branch, declare it there too.
        demo_series = (config.daily_overhead_day_model() or {}).get("demo_series")
        install_days = sum(s.days for s in body.daily_series if s.series != demo_series)
        if install_days < 1:
            raise HTTPException(
                422,
                detail=f"{prefix}install days are required and must be at least 1 "
                f"(got {install_days:g}). Demo days may be omitted for new construction; "
                f"install days may not.",
            )



@router.post("/suggested-days")
def suggested_days(
    body: QuoteRequest,
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """The day counts the model would derive for this roof — WITHOUT pricing or persisting it.

    Tim, 2026-08-04: *"you can derive days and estimate working days to create the value and let
    tim or a sales rep override."* The day cells must never be blank, because a blank one is
    read as ZERO rather than "estimate it" — so the UI needs the derived number BEFORE the first
    quote, not after it. `/quote` could not serve that: it prices, validates and writes an audit
    row, none of which a pre-fill should do.

    Returns `{demo_days, install_days, series}`. `install_days` FOLDS IN the flat section of a
    mixed roof: every series bills the same `office_daily_overhead / concurrent_crews` under the
    branch basis all three branches now use, so what the money depends on is the day TOTAL, not
    which series carries it. One cell per crew — demo and install — is the whole model.
    """
    if body.config_id is not None:
        cfg_row = db.get(PricingConfig, body.config_id)
        if cfg_row is None or cfg_row.tenant_id != db.info.get("tenant_id"):
            raise HTTPException(404, f"Config {body.config_id} not found")
    else:
        cfg_row = _get_active_config_row(body.branch, db)
    if cfg_row is None or not cfg_row.config:
        raise HTTPException(
            503,
            detail=(
                f"no active pricing config for branch '{body.branch}' — "
                "seed/activate one in Admin -> Estimating"
            ),
        )

    # Derive from the roof, never from what the caller typed: this endpoint answers "what does
    # the model say", so any daily_series on the body is deliberately ignored.
    q, _slope, _cuts, _split = _quote_input_from_request(body, cfg_row, db, claims)
    config = load_config(cfg_row.config)
    derived = E.derive_daily_series(config, replace(q, daily_series=[]))

    demo_series = (config.daily_overhead_day_model() or {}).get("demo_series")
    demo = sum(s.days for s in derived if s.series == demo_series)
    install = sum(s.days for s in derived if s.series != demo_series)
    return {
        "demo_days": demo,
        "install_days": install,
        "series": [{"series": s.series, "days": s.days} for s in derived],
        "derived": bool(derived),
    }


@router.post("/quote")
def quote(
    body: QuoteRequest,
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Compute an itemized roofing estimate.

    Uses the active config for the branch (or a pinned config_id).
    Returns HTTP 503 if no active config is seeded for the branch.
    Stamps pricing_config_id and pricing_config_hash on the response and
    persists an Estimate row for audit reproduction.
    """
    # Resolve the config row
    if body.config_id is not None:
        cfg_row = db.get(PricingConfig, body.config_id)
        if cfg_row is None or cfg_row.tenant_id != db.info.get("tenant_id"):
            raise HTTPException(404, f"Config {body.config_id} not found")
    else:
        cfg_row = _get_active_config_row(body.branch, db)

    # No active config — refuse with 503 (no silent legacy fallback)
    if cfg_row is None or not cfg_row.config:
        raise HTTPException(
            503,
            detail=(
                f"no active pricing config for branch '{body.branch}' — "
                "seed/activate one in Admin -> Estimating"
            ),
        )

    q, effective_slope_type, cut_lfs, split_unknown = _quote_input_from_request(
        body, cfg_row, db, claims)

    config = load_config(cfg_row.config)

    # Gutter accessories (elbows, leaf guard, 2-story uplift) only price alongside a
    _validate_quote_guards(body, config)

    try:
        result = E.estimate(config, q)
    except (ValueError, ConfigError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    # Stamp config audit fields on response
    result["pricing_config_id"] = cfg_row.id
    result["pricing_config_hash"] = cfg_row.config_hash
    result["branch"] = body.branch
    result["code_zone"] = body.code_zone
    result["county"] = body.county
    result["slope_type"] = effective_slope_type
    result["selected_tier"] = body.selected_tier
    # Priced off a measurement with no recorded pitched/flat split. Stamped on the response AND
    # therefore on the persisted audit row, so a quote that MIGHT have charged a flat section at
    # the sloped rate can be found later by query rather than by memory.
    if split_unknown:
        result["split_unknown"] = True
        result.setdefault("warnings", []).append(
            "split_unknown: this measurement records no pitched/flat split, so total_sq was priced "
            "entirely as sloped. If the roof has a flat section, record pitched_sq/flat_sq on the "
            "measurement and re-quote — total_sq means sloped-only on Tim's sheet but pitched+flat "
            "on a RoofR transcription.")
    # Config floor percentages, exposed so clients (proposal snapshot "floors") stay
    # config-driven per branch instead of hardcoding 13%/33%.
    result["floors"] = {
        "min_profit_pct": config.raw["profit_floor_pct"],
        "min_profit_plus_oh_pct": config.raw["profit_plus_oh_floor_pct"],
    }

    # Discounts are sales concessions. They reduce project_total and available
    # profit/margin, while preserving the pre-discount engine total for audit.
    discount_rows = [d.model_dump(exclude_none=True) for d in body.discounts]
    try:
        resolved_discounts = resolve_discounts(discount_rows, result["project_total"])
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if resolved_discounts:
        discount_total = round(sum(float(d["amount"]) for d in resolved_discounts), 2)
        pre_discount_total = float(result["project_total"])
        adjusted_total = round(pre_discount_total - discount_total, 2)
        adjusted_profit = round(float(result["profit_dollars"]) - discount_total, 2)
        eligible_base = float((result.get("margin") or {}).get("eligible_base") or 0)
        oh_dollars = float((result.get("margin") or {}).get("oh_dollars") or 0)
        profit_pct = (adjusted_profit / eligible_base) if eligible_base else 0.0
        combined_pct = ((adjusted_profit + oh_dollars) / eligible_base) if eligible_base else 0.0
        commission_rate = (body.commission_rate if body.commission_rate is not None
                            else config.commission_rate(body.commission_basis))
        warnings = list(result.get("margin_warnings") or [])
        if adjusted_profit < 0 and "discount_exceeds_profit" not in warnings:
            warnings.append("discount_exceeds_profit")
        if profit_pct < config.raw["profit_floor_pct"] and "profit_floor" not in warnings:
            warnings.append("profit_floor")
        if combined_pct < config.raw["profit_plus_oh_floor_pct"] and "combined_floor" not in warnings:
            warnings.append("combined_floor")
        # The minimum-margin floor is applied in the ENGINE, pre-discount. A discount subtracts
        # straight off profit here, so the first discount silently defeats it: a job floored to
        # $2,500 with a $2,000 discount lands at $500 and, before this, warned only if profit
        # went negative. Sales holds quoting_create, so that lever is exactly the one they have.
        # profit_floor_guidance is nested inside result["profit_guidance"], never top level. Reading
        # it flat returned None -> 0.0 -> falsy, so the `and floor_after_discount` conjunct below
        # short-circuited and this guard could NEVER fire under the weekly basis. Dead since it was
        # written; only harmless because prod ran "job".
        if config.profit_floor_basis() == "weekly":
            guidance = result.get("profit_guidance") or {}
            floor_after_discount = float(guidance.get("effective_floor")
                                         or guidance.get("profit_floor_guidance") or 0)
        else:
            floor_after_discount = config.job_profit_floor()
        if (config.enforce_profit_floor() and floor_after_discount
                and adjusted_profit < floor_after_discount
                and "min_margin_breached" not in warnings):
            warnings.append("min_margin_breached")
        result["pre_discount_total"] = round(pre_discount_total, 2)
        result["discount_total"] = discount_total
        result["discounts"] = resolved_discounts
        result["project_total"] = adjusted_total
        result["profit_dollars"] = adjusted_profit
        result["profit_pct"] = round(profit_pct, 4)
        comm_base = adjusted_total if body.commission_basis == "job" else adjusted_profit
        result["estimated_commission"] = round(comm_base * commission_rate, 2)
        result["margin_ok"] = profit_pct >= config.raw["profit_floor_pct"]
        result["margin_warnings"] = warnings
        result["margin"] = {
            **(result.get("margin") or {}),
            "profit_dollars": adjusted_profit,
            "profit_pct": round(profit_pct, 4),
            "combined_pct": round(combined_pct, 4),
            "profit_floor_ok": profit_pct >= config.raw["profit_floor_pct"],
            "combined_floor_ok": combined_pct >= config.raw["profit_plus_oh_floor_pct"],
            "margin_warnings": warnings,
        }

    # Full package menu (Protector from the engine total + flat catalog adders — Zoom
    # 2026-07-17: offer ALL premiums + coastal; adders don't re-price cuts). Computed
    # AFTER discounts so tier totals, the proposal snapshot, and the deposit all agree
    # with the discounted headline number ("Discounts affect total and margin").
    from core.perkins_packages import package_options  # noqa: PLC0415
    # RESOLVED squares, not body.num_squares: PROTECTOR is the engine total (priced off the
    # resolved split) while every upgrade tier is catalog $/sq x squares. Reading the body here
    # made the two disagree by exactly the amount the split resolution corrected.
    result["package_options"] = package_options(
        body.roof_type, float(q.num_squares), float(result["project_total"]),
        discount_total=float(result.get("discount_total") or 0),
    )

    # Cut-calculator reference (shown alongside the flat headline; Tim picks). A second estimate
    # with the RoofR cut LFs, attached only when cuts actually move the base (calibrated zone).
    # Pre-discount totals so the flat-vs-cut delta is purely the base difference.
    if any(cut_lfs.values()):
        try:
            # Same input as the headline quote with the cut-adjusted base switched ON. Previously
            # rebuilt from qkwargs; `q` already carries the cut LFs and pitch_primary and differs
            # only by apply_cut_calc_to_base=False, so this is the same object by a shorter route
            # — and cannot drift from the headline quote's field mapping.
            cut_res = E.estimate(config, replace(q, apply_cut_calc_to_base=True))
        except (ValueError, ConfigError):
            cut_res = None
        if cut_res:
            def _base_ps(res):
                return next((li["per_sq"] for li in res["line_items_detail"]
                             if li["key"] == "base_cost_lm"), None)
            flat_base, cut_base = _base_ps(result), _base_ps(cut_res)
            if flat_base is not None and cut_base is not None and abs(cut_base - flat_base) > 0.01:
                result["cut_calc"] = {
                    "flat_base_per_sq": round(flat_base, 2),
                    "cut_base_per_sq": round(cut_base, 2),
                    "flat_project_total": round(float(result.get("pre_discount_total")
                                                      or result["project_total"]), 2),
                    "cut_project_total": round(float(cut_res["project_total"]), 2),
                    "base_tile_brand": body.base_tile_brand
                        or (config.cuts_calc() or {}).get("default_tile_brand"),
                    "warnings": cut_res.get("warnings", []),
                }

    # Persist estimate row for audit reproduction (TRD §2.2)
    parent_id = body.parent_estimate_id
    root_id = None
    version_number = 1
    if parent_id is not None:
        parent = db.get(Estimate, parent_id)
        if parent is None or parent.tenant_id != db.info["tenant_id"]:
            raise HTTPException(404, f"Parent estimate {parent_id} not found")
        root_id = parent.root_id or parent.id
        version_number = int(parent.version_number or 1) + 1

    est = Estimate(
        tenant_id=db.info["tenant_id"],
        # cfg_row.branch, not body.branch: the row records which config priced this quote, and
        # the config IS a branch. They are the same value when the config was looked up BY
        # branch, and when the caller pins config_id they need not be — body.branch is then
        # unvalidated free text, so the audit row claimed a branch the quote was never priced
        # for. (#359's FK turns that from a quiet wrong value into a write that fails.)
        branch=cfg_row.branch,
        code_zone=body.code_zone,
        county=body.county,
        pricing_config_id=cfg_row.id,
        pricing_config_hash=cfg_row.config_hash,
        parent_id=parent_id,
        root_id=root_id,
        version_number=version_number,
        source_proposal_id=body.source_proposal_id,
        # The RESOLVED squares, not the raw body. api/routes/proposals.py rebuilds a QuoteInput
        # straight from this row without going through _quote_input_from_request, so persisting
        # the rejected values would let a customer-facing proposal re-price a bid to a number no
        # estimate ever produced. An audit row must record what was CHARGED.
        # slope_type is RESOLVED for the same reason as the squares above, and was missed when
        # they were: a low-slope system (tpo_adhered, polyglass_sav_sap, pb_silicone_*) is coerced
        # to slope_type='low_slope' before pricing, but the raw body says 'sloped'. Persisting the
        # raw value means proposals.py rebuilds a QuoteInput that prices the sloped path and
        # KeyErrors on `sloped_base_cost_lm[zone][tpo_adhered]` — an unhandled 500 on a
        # customer-facing document, from a row that priced fine.
        input_json={**body.model_dump(), "num_squares": q.num_squares,
                    "flat_squares": q.flat_squares, "slope_type": q.slope_type},
        # q.debug, not body.debug: already role-gated at :387, so a sales caller
        # asking for debug still persists a stripped row.
        result_json=_audit_payload(result, debug=q.debug),
        created_by=claims.get("email") or "unknown",
    )
    db.add(est)
    db.flush()
    if est.root_id is None:
        est.root_id = est.id
        db.flush()
    result["estimate_id"] = est.id
    result["estimate_root_id"] = est.root_id
    result["estimate_version"] = est.version_number
    est.result_json = _audit_payload(result, debug=q.debug)
    db.flush()

    return _public_estimate(result, claims)


class BuildingInput(BaseModel):
    """One structure in the bid: a label, its own full quote, and optionally its on-site days."""
    name: str = Field(..., min_length=1, max_length=200)
    #: Days the crew spends on THIS structure. Only feeds the site week count; when absent the
    #: building contributes its own estimate's derived series days.
    days: Optional[float] = Field(default=None, ge=0)
    #: This structure's own street address. Absent = the bid project's property, which is the
    #: normal case (Tim, 2026-08-02: "yes but they can share"). Priced nowhere; it reaches the
    #: customer through the proposal render, grouped so shared addresses print once.
    address: Optional[str] = Field(default=None, max_length=300)
    quote: QuoteRequest


class ProjectItemInput(BaseModel):
    """A quoted block belonging to the site rather than to any one roof (General Conditions)."""
    key: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=300)
    cost: float = Field(..., ge=0)
    #: null = take the project-level default. For General Conditions that is
    #: ProjectQuoteRequest.general_conditions_markup (Tim's slider, x1.15); an add-on block that
    #: names no markup is quoted at cost. A block that DOES carry one wins — the project value is
    #: a default, not a cap.
    markup: Optional[float] = Field(default=None, ge=1.0, le=3.0)
    #: Only "project" is implemented — see core.bid_project.ProjectItem. "building:<name>" is
    #: reserved for Tim's folding habit and is refused until the fold exists.
    allocation: Literal["project"] = "project"


class ProjectQuoteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    property_id: Optional[int] = None
    # Capped: every building triggers a full estimate() plus an INSERT, and one authenticated
    # estimating_view caller could otherwise hold a worker and a transaction with 10,000 of them.
    # Evergrene, the largest real bid, is 9.
    buildings: list[BuildingInput] = Field(..., min_length=1, max_length=50)
    #: General Conditions — site-wide cost that exists because the JOB does. Tim's Evergrene block
    #: is green fence + telehandler ($22,800) and a full-time PM ($9,000) at x1.15 = $36,570, and
    #: on his sheet it stands as its own quoted line referenced by no total formula.
    project_items: list[ProjectItemInput] = Field(default_factory=list, max_length=50)
    #: Scope blocks that belong to the project rather than to any one building — Tim's $42,050
    #: sloped and $31,000 tile add-ons. Priced identically to project_items; kept as a SEPARATE
    #: list because his proposal presents them as a separate block, and the bid_projects column
    #: exists for exactly this and was being written as [] with everything folded into
    #: general_conditions.
    add_on_blocks: list[ProjectItemInput] = Field(default_factory=list, max_length=50)
    #: null = the measured default (see core.bid_project.DEFAULT_ONCE_PER_PROJECT). An explicit
    #: list is how a bid opts out of a site-scoping decision that is still pending Tim.
    once_per_project: Optional[list[str]] = None
    floor_basis: Literal["project", "week", "building"] = "project"
    #: Markup applied to every General Conditions block that names no markup of its own. Tim,
    #: 2026-08-02: "we have a slider for this" — his Evergrene block is (green fence + telehandler
    #: $22,800 + full-time PM $9,000) x 1.15. Persisted to bid_projects.general_conditions_markup,
    #: which until now was written as a flat 1.0 that nothing read.
    general_conditions_markup: float = Field(default=1.0, ge=1.0, le=3.0)
    #: null = ONE PERMIT PER BUILDING (Tim, 2026-08-02; 73 of 333 Knowify projects with a permit
    #: line bill more than one). An integer says the county issued a different number for this
    #: site — a single site permit on a nine-structure bid is permit_count=1, said out loud.
    permit_count: Optional[int] = Field(default=None, ge=1, le=99)
    notes: Optional[str] = None
    #: Defaults to FALSE. The primary caller is an SPA that re-prices on every keystroke, and
    #: there is no idempotency key or dedupe on name — defaulting to True meant any client that
    #: omitted the field grew two tables per request. The caller that wants a row asks for one.
    persist: bool = False


@router.post("/project-quote")
def project_quote(
    body: ProjectQuoteRequest,
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Price several structures at one site as ONE bid (#430/#449 slice 2).

    Each building is priced through the SAME config resolution and field mapping as
    POST /quote (`_quote_input_from_request`), then core.bid_project.price_project suppresses the
    site-scoped fees per building, adds them once, and applies one profit floor over the bid.

    Persists one `bid_projects` row and N `estimates` rows carrying `bid_project_id` +
    `structure_name`, so a project is reproducible for audit exactly like a single quote is.

    Returns 422 when the buildings disagree on branch or zone: a bid is one site with one permit
    office and one price book, and silently pricing half the structures off another branch's
    config would be invisible in the total.
    """
    branches = {b.quote.branch for b in body.buildings}
    if len(branches) > 1:
        raise HTTPException(422, detail=f"all buildings must share one branch, got {sorted(branches)}")
    zones = {b.quote.code_zone for b in body.buildings}
    if len(zones) > 1:
        raise HTTPException(422, detail=f"all buildings must share one code_zone, got {sorted(zones)}")

    first = body.buildings[0].quote
    if first.config_id is not None:
        cfg_row = db.get(PricingConfig, first.config_id)
        if cfg_row is None or cfg_row.tenant_id != db.info.get("tenant_id"):
            raise HTTPException(404, f"Config {first.config_id} not found")
    else:
        cfg_row = _get_active_config_row(first.branch, db)
    if cfg_row is None or not cfg_row.config:
        raise HTTPException(
            503,
            detail=(f"no active pricing config for branch '{first.branch}' — "
                    "seed/activate one in Admin -> Estimating"),
        )

    # REFUSE what the project path cannot honour, rather than accepting and ignoring it.
    # BuildingInput.quote is the FULL QuoteRequest, so it advertises every field /quote supports;
    # the project roll-up implements a subset. Silently dropping the rest is the dangerous
    # option — `discounts` in particular would be persisted into input_json while never coming
    # off the price, so the audit row would disagree with what the customer was quoted.
    unsupported = {
        "discounts": [b.name for b in body.buildings if b.quote.discounts],
        "parent_estimate_id": [b.name for b in body.buildings
                               if b.quote.parent_estimate_id is not None],
        "source_proposal_id": [b.name for b in body.buildings
                               if b.quote.source_proposal_id is not None],
    }
    named = {k: v for k, v in unsupported.items() if v}
    if named:
        raise HTTPException(422, detail={
            "message": "these fields are not supported on a project quote and were refused "
                       "rather than silently ignored",
            "fields": named,
        })
    # config_id is the third axis of the same decision as branch/code_zone above: pricing half a
    # site off a pinned config and half off the active one is invisible in the total.
    config_ids = {b.quote.config_id for b in body.buildings}
    if len(config_ids) > 1:
        raise HTTPException(422, detail=f"all buildings must share one config_id, got {sorted(config_ids, key=str)}")

    # A property_id is a cross-tenant reference if it is not checked. bid_projects.property_id is
    # a plain FK, and Postgres evaluates FK constraints with row security bypassed, so RLS on
    # `properties` does NOT stop a bid pointing at another tenant's property — it only stops
    # anyone reading it back. db.get under the tenant-scoped session returns None for a row this
    # tenant cannot see, which is exactly the check.
    if body.property_id is not None:
        if db.get(Property, body.property_id) is None:
            raise HTTPException(404, f"Property {body.property_id} not found")

    config = load_config(cfg_row.config)
    built: list[BP.Building] = []
    # Named per structure: on a nine-building bid an unstamped flag says a flat section may have
    # been priced as sloped SOMEWHERE, which is not actionable.
    split_unknown_structures: list[str] = []
    for item in body.buildings:
        q, _slope, _cuts, split_unknown = _quote_input_from_request(
            item.quote, cfg_row, db, claims)
        _validate_quote_guards(item.quote, config, where=item.name)
        if split_unknown:
            split_unknown_structures.append(item.name)
        built.append(BP.Building(name=item.name, quote=q, days=item.days,
                                 address=(item.address or "").strip() or None))

    once = (frozenset(body.once_per_project) if body.once_per_project is not None
            else BP.DEFAULT_ONCE_PER_PROJECT)
    # Resolve each block's EFFECTIVE markup once, here, and use the same list to price and to
    # persist. Storing the request's nulls instead would leave the re-price path in
    # /quoting/proposals/from-project reading `markup or 1.0` and quietly dropping the project
    # slider — a 15% under-charge on Tim's $36,570 General Conditions, invisible in the total.
    gc_items = [pi.model_copy(update={"markup": pi.markup if pi.markup is not None
                                      else body.general_conditions_markup})
                for pi in body.project_items]
    add_on_items = [pi.model_copy(update={"markup": pi.markup if pi.markup is not None else 1.0})
                    for pi in body.add_on_blocks]
    try:
        roll_up = BP.price_project(
            config, built,
            project_items=[BP.ProjectItem(**pi.model_dump())
                           for pi in (*gc_items, *add_on_items)],
            once_per_project=once,
            floor_basis=body.floor_basis,
            permit_count=body.permit_count,
        )
    except (ValueError, ConfigError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    # The count that was actually PRICED, not the one that was asked for: null means one per
    # building, and every consumer downstream (the response, the audit row, the re-price that
    # builds the proposal) has to carry the same number the customer was charged for.
    permit_count = roll_up["permit_count"]

    result = {
        **roll_up,
        "name": body.name,
        "branch": first.branch,
        "code_zone": first.code_zone,
        "pricing_config_id": cfg_row.id,
        "pricing_config_hash": cfg_row.config_hash,
        "once_per_project": sorted(once),
        "permit_count": permit_count,
        # Same stamp as /quote, per structure. Additive: absent means every building's measurement
        # carried a recorded split.
        **({"split_unknown_structures": split_unknown_structures}
           if split_unknown_structures else {}),
        "general_conditions_markup": body.general_conditions_markup,
        "dominant_roof_type": BP.dominant_roof_type(built),
        "num_squares": round(BP.total_squares(built), 2),
    }
    if not body.persist:
        return _public_estimate(result, claims)

    project = BidProject(
        tenant_id=db.info["tenant_id"],
        property_id=body.property_id,
        name=body.name,
        branch=cfg_row.branch,  # see the single-quote path — the config priced it, so it names it
        code_zone=first.code_zone,
        # The EFFECTIVE blocks — each already carries the markup it was priced at, so the
        # re-price that builds the proposal reproduces this bid without re-deriving anything.
        general_conditions=[pi.model_dump() for pi in gc_items],
        # The project-level default the blocks above inherited when they named no markup of their
        # own. Kept because Tim has a slider for it; it is NOT a second authority over a block
        # that set its own rate, and price_project multiplies by the per-block value either way.
        general_conditions_markup=body.general_conditions_markup,
        add_on_blocks=[pi.model_dump() for pi in add_on_items],
        once_per_project_fees=sorted(once),
        profit_floor_basis=body.floor_basis,
        notes=body.notes,
        created_by=claims.get("email") or "unknown",
    )
    db.add(project)
    db.flush()

    # One estimate row per structure, each carrying the project id and its label. Written with the
    # SAME _audit_payload shape a single quote uses, so an auditor replaying a project reads the
    # same rows in the same format rather than a second, project-only schema.
    estimate_ids: list[int] = []
    for item, resolved, priced in zip(body.buildings, built, roll_up["buildings"],
                                      strict=True):
        est = Estimate(
            tenant_id=db.info["tenant_id"],
            # One cfg_row prices the whole project, so a per-building branch was never what
            # this row was priced with — it only ever looked like it was.
            branch=cfg_row.branch,
            code_zone=item.quote.code_zone,
            county=item.quote.county,
            pricing_config_id=cfg_row.id,
            pricing_config_hash=cfg_row.config_hash,
            bid_project_id=project.id,
            structure_name=item.name,
            structure_address=(item.address or "").strip() or None,
            # The building's OWN inputs plus the two project-level facts that decide its price
            # and are not part of QuoteRequest. Without them a week-basis project cannot be
            # recomputed from what was stored, which is the whole point of an audit row.
            input_json={
                **item.quote.model_dump(),
                # RESOLVED, not the raw body — /quoting/proposals/from-project rebuilds a
                # QuoteInput straight from this row without the mapper, so storing the rejected
                # squares would let the customer-facing proposal re-price to a number no estimate
                # ever produced. An audit row records what was CHARGED.
                "num_squares": resolved.quote.num_squares,
                "flat_squares": resolved.quote.flat_squares,
                # …and slope_type, for the same reason: a low-slope structure in a multi-building
                # bid is coerced to 'low_slope' before pricing, so storing the body's 'sloped'
                # makes the rebuilt QuoteInput price the sloped path and KeyError. This is the
                # site that path actually reads.
                "slope_type": resolved.quote.slope_type,
                "structure_days": item.days,
                "project_permit_count": permit_count,
                "project_floor_basis": body.floor_basis,
                "project_once_per_project": sorted(once),
            },
            # `project_total` mirrors this building's own total. The roll-up's per-building dict
            # calls it `total`, and GET /estimator/estimates -> Quoting.tsx reads
            # result_json.project_total — so every project building rendered as an em dash.
            result_json=_audit_payload({**priced, "project_total": priced["total"]}),
            created_by=claims.get("email") or "unknown",
        )
        db.add(est)
        db.flush()
        est.root_id = est.id
        estimate_ids.append(est.id)
    db.flush()

    result["bid_project_id"] = project.id
    result["estimate_ids"] = estimate_ids
    return _public_estimate(result, claims)


@router.post("/repair-quote")
def repair_quote(
    body: RepairQuoteRequest,
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Compute a time-based repair quote (days x daily labor rate + material cost).

    A simpler alternative to POST /quote for repair work — no line-item breakdown,
    no audit row persisted; the sales flow re-quotes on demand.
    """
    if body.config_id is not None:
        cfg_row = db.get(PricingConfig, body.config_id)
        if cfg_row is None or cfg_row.tenant_id != db.info.get("tenant_id"):
            raise HTTPException(404, f"Config {body.config_id} not found")
    else:
        cfg_row = _get_active_config_row(body.branch, db)

    if cfg_row is None or not cfg_row.config:
        raise HTTPException(
            503,
            detail=(
                f"no active pricing config for branch '{body.branch}' — "
                "seed/activate one in Admin -> Estimating"
            ),
        )

    config = load_config(cfg_row.config)
    try:
        r = RepairInput(
            roof_type=body.roof_type,
            days=body.days,
            crew_size=body.crew_size,
            material_cost=body.material_cost,
            percent_profit_pct=body.percent_profit_pct,
        )
        result = E.estimate_repair(config, r)
    except (ValueError, ConfigError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    result["branch"] = body.branch
    result["pricing_config_id"] = cfg_row.id
    result["pricing_config_hash"] = cfg_row.config_hash
    # Same shape as /quote's floors block, so the UI can build a send-valid proposal
    # snapshot (core/proposal.py validate_snapshot requires pricing_config_hash + floors).
    result["floors"] = {
        "min_profit_pct": config.raw["profit_floor_pct"],
        "min_profit_plus_oh_pct": config.raw["profit_plus_oh_floor_pct"],
    }
    return _public_estimate(result, claims)


@router.post("/scope-of-work/rewrite")
def rewrite_scope_of_work(
    body: ScopeOfWorkRewriteRequest,
    _claims=Depends(require_role("estimating_view")),
):
    """AI-rewrite a scope-of-work template per a free-text instruction.

    Returns HTTP 502 (template unchanged) on validation failure or an empty LLM reply,
    rather than shipping a broken/empty scope of work.
    """
    from app.llm import chat  # noqa: PLC0415

    try:
        prompt = SOW.build_rewrite_prompt(body.template, body.instruction, body.job_context)
        reply = chat(prompt)
        text = SOW.validate_rewrite(reply or "")
    except Exception as exc:  # noqa: BLE001 — fail-safe: ANY llm/transport/parse error
        # returns "template unchanged", never a raw 500 (same posture as proposal_review).
        raise HTTPException(502, detail="rewrite failed — template unchanged") from exc
    return {"text": text}


def _estimate_row(row: Estimate, claims: dict | None = None) -> dict:
    result_json = row.result_json or {}
    if claims is not None:
        result_json = _public_estimate(result_json, claims)
    return {
        "id": row.id,
        "pricing_config_id": row.pricing_config_id,
        "pricing_config_hash": row.pricing_config_hash,
        "branch": row.branch,
        "code_zone": row.code_zone,
        "county": row.county,
        "parent_id": row.parent_id,
        "root_id": row.root_id,
        "version_number": row.version_number,
        "source_proposal_id": row.source_proposal_id,
        # Without these a persisted project is nine anonymous rows in the estimates list with no
        # way to tell they belong together — the write half of slice 2 had no reader at all.
        "bid_project_id": row.bid_project_id,
        "structure_name": row.structure_name,
        # Read back so a typo'd structure address is visible somewhere other than the rendered PDF.
        "structure_address": row.structure_address,
        "input_json": row.input_json or {},
        "result_json": result_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    }


def _priced_low_slope_types(cfg: dict, zone: str) -> list[str]:
    base = ((cfg.get("low_slope") or {}).get("base_cost_lm") or {}).get(zone, {})
    return [
        key for key, value in base.items()
        if not key.startswith("_") and value is not None
    ]


@router.get("/estimates")
def list_estimates(
    measurement_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    rows = (
        db.query(Estimate)
        .filter(Estimate.tenant_id == db.info["tenant_id"])
        .order_by(Estimate.created_at.desc())
        .limit(limit)
        .all()
    )
    if measurement_id is not None:
        rows = [r for r in rows if (r.input_json or {}).get("measurement_id") == measurement_id]
    return [_estimate_row(r, claims) for r in rows]


@router.get("/rates")
def rates(
    branch: str = Query(default="miami"),
    region: str = Query(default="FBC"),
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Rate tables from the active config for the current tenant's branch.

    Returns a minimal response with null config fields when no active config is seeded
    (graceful — no 503 here; the estimator UI can still show the form).
    """
    cfg_row = _get_active_config_row(branch, db)
    if cfg_row and cfg_row.config:
        cfg = cfg_row.config
        zone = region
        sloped_roof_types = [
            key for key in (cfg.get("sloped_base_cost_lm") or {}).get(zone, {}).keys()
            if not key.startswith("_")
        ]
        low_slope_roof_types = _priced_low_slope_types(cfg, zone)
        return {
            "branch": branch,
            "region": zone,
            "config_id": cfg_row.id,
            "config_hash": cfg_row.config_hash,
            "roof_types": sloped_roof_types + low_slope_roof_types,
            "sloped_roof_types": sloped_roof_types,
            "low_slope_roof_types": low_slope_roof_types,
            "low_slope_pending": low_slope_roof_types == [],
            "base_cost_lm": (cfg.get("sloped_base_cost_lm") or {}).get(zone, {}),
            "overhead": (cfg.get("sloped_overhead") or {}).get(zone, {}),
            "low_slope": cfg.get("low_slope") or {},
            "profit_scale": cfg.get("profit_scale", []),
            "roof_cuts": cfg.get("roof_cuts", {}),
            # Cut calculator: whether this zone is calibrated, and the selectable base tile brands.
            "cut_calc_available": bool(((cfg.get("cuts_calc") or {}).get("fixed_per_sq") or {}).get(zone)),
            "tile_brands": {
                k: (v or {}).get("label", k)
                for k, v in ((cfg.get("cuts_calc") or {}).get("tile_brands") or {}).items()
            },
            "default_tile_brand": (cfg.get("cuts_calc") or {}).get("default_tile_brand"),
            "tile_pointing": cfg.get("tile_pointing", {}),
            "specialty_tile": (cfg.get("specialty_tile_upgrade") or {}).get(zone, {}),
            "line_items": (cfg.get("line_items") or {}).get(zone, {}),
            "pm_incentive": cfg.get("pm_incentive", {}),
            # v2: day-based overhead and profit-floor config fields for the UI
            # Rates as the engine will actually apply them — scaled to this branch's office
            # burn, not the raw stored numbers, so the admin panel shows what gets quoted.
            "daily_overhead_rates": load_config(cfg).daily_overhead_rates(),
            "daily_overhead_rates_base": cfg.get("daily_overhead_rates") or {},
            # Overhead is the office's gross daily cost of doing business (Tim: total office
            # costs / working days) — a per-branch admin input, ~$1,390 Jupiter vs ~$4,140 Miami.
            "office_daily_overhead": cfg.get("office_daily_overhead"),
            "office_men": cfg.get("office_men"),
            "office_oh_basis_reference": cfg.get("office_oh_basis_reference"),
            "daily_overhead_weeks_rounding_mode": cfg.get("daily_overhead_weeks_rounding_mode") or "ceil",
            "daily_overhead_day_model": cfg.get("daily_overhead_day_model") or {},
            "weekly_profit_floor": cfg.get("weekly_profit_floor") or 2500,
            "job_profit_floor": cfg.get("job_profit_floor") or 2500,
            # When true the profit floor MOVES THE PRICE rather than only warning. The amount
            # is weekly_profit_floor x on-site weeks (one week minimum) — Tim: "$2,500 a week
            # that we're on the job ... if it's one day it still counts as one week".
            "enforce_profit_floor": bool(cfg.get("enforce_profit_floor")),
            "profit_floor_days_per_week": cfg.get("profit_floor_days_per_week") or 6,
            # "job" = one flat floor per job (current). "weekly" = x on-site weeks.
            "profit_floor_basis": cfg.get("profit_floor_basis") or "job",
            # v2: repair (time-based) quote config — roof-type categories + daily labor rates
            "repair": cfg.get("repair") or {},
            # scope-of-work AI rewrite: saved default template ({"default_template": str})
            "scope_of_work": cfg.get("scope_of_work") or {},
        }

    # No active config seeded — minimal response (documented; the SPA shows the note).
    # (A "legacy rates" fallback used to live here but could never fire: E is
    # core.estimator, which has no module-level rate constants. Deleted 2026-07-10.)
    return {
        "branch": branch,
        "region": region,
        "config_id": None,
        "config_hash": None,
        "roof_types": [],
        "note": "No active config seeded for this branch. Activate a config version first.",
    }


class SaltWaterRequest(BaseModel):
    """Either coordinates or an address. Address is geocoded with the Squares/Maps key."""
    address: Optional[str] = Field(default=None, max_length=300)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


@router.post("/salt-water")
def salt_water_check(
    body: SaltWaterRequest,
    claims=Depends(require_role("estimating_view")),
):
    """How close is this property to salt water, and what does that do to a metal warranty.

    Answers from the SAME assets the public warranty checker uses, through core.salt_water — one
    implementation, so an estimate and the customer-facing tool can never disagree about an
    address. `waterfront` is what the estimate form ticks: true inside the widest setback any
    manufacturer applies to a material Perkins sells.

    Coordinates win when supplied; an address is geocoded. Returns 404 when the address cannot be
    resolved, and a null distance (not an error) when the address is simply outside the mapped
    South Florida tidal coverage — "we do not know" is a different answer from "no salt water".
    """
    from core.salt_water import check  # noqa: PLC0415

    lat, lon, resolved = body.latitude, body.longitude, body.address
    if lat is None or lon is None:
        if not (body.address or "").strip():
            raise HTTPException(422, "supply an address or latitude/longitude")
        from api.routes.squares import _api_key, _geocode  # noqa: PLC0415
        lat, lon, resolved = _geocode(body.address.strip(), _api_key())

    r = check(lat, lon)
    return {
        "address": resolved,
        "latitude": lat,
        "longitude": lon,
        "distance_ft": r.distance_ft,
        "waterfront": r.waterfront,
        "confidence": r.confidence,
        "water_name": r.water_name,
        "materials": r.materials,
        "warranty_terms": r.warranty_terms,
        "note": r.note,
    }
