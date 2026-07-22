"""Estimator routes — roofing bid calculator (F2).

Endpoints:
  POST  /estimator/quote    compute estimate using active config + stamp hash
  GET   /estimator/rates    rate tables from active config (config-driven in F2)

Role requirements (core.authz):
  estimating_view  → POST /estimator/quote, GET /estimator/rates
  estimating_manage → config CRUD (lives in api/routes/pricing_configs.py)
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Estimate, Measurement, PricingConfig
from core import estimator as E
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
    branch: str = "miami"
    # roof_type is config-driven (repair.roof_types), not a Literal — a static enum here would
    # 422 on a new category Tim adds to config without a code deploy (see roof_type on
    # QuoteRequest above for the same fix, and its history).
    roof_type: str = Field(..., max_length=40)
    days: float = Field(..., gt=0)
    crew_size: Literal[1, 2] = 1
    material_cost: float = Field(default=0, ge=0)
    config_id: Optional[int] = None      # null = use active config; explicit = pin to version


router = APIRouter(prefix="/estimator", tags=["estimator"])

# Low-slope systems route to the low-slope calculator regardless of the slope_type
# flag, so a caller can never mismatch roof_type and calculator.
LOW_SLOPE_ROOF_TYPES = frozenset({"tpo", "coatings", "silicone", "bur"})


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
    branch: str = "miami"
    code_zone: Literal["HVHZ", "FBC"] = "HVHZ"
    county: Optional[str] = None
    slope_type: Literal["sloped", "low_slope"] = "sloped"
    # roof_type keys are config-driven (exhibit_b uses granular low-slope system keys like
    # `tpo_adhered`, `pb_silicone_2coat`); a static Literal can't enumerate them, so validate
    # at the boundary with a length cap and let the engine's ConfigError guard unknown keys (→422).
    roof_type: str = Field(default="13_tile", max_length=40)
    num_squares: float = Field(..., gt=0)
    roof_cuts: Literal["low", "medium", "high"] = "low"
    roof_height: Literal["1_story", "2_stories", "3_5_stories", "6_plus"] = "1_story"
    tile_pointing: Literal["no", "yes"] = "no"
    specialty_tile: Optional[str] = None
    project_kind: Literal["residential", "commercial"] = "residential"
    pitch_7_12: bool = False
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
    include_tapered: bool = False
    measurement_id: Optional[int] = None
    config_id: Optional[int] = None      # null = use active config; explicit = pin to version
    override_base_cost: Optional[float] = None
    override_overhead: Optional[float] = None
    override_profit_per_sq: Optional[float] = None

    # v2: day-based overhead + flat profit mode
    overhead_mode: Literal["per_sq", "daily"] = "per_sq"
    daily_series: list[DailySeriesItem] = Field(default_factory=list)
    profit_mode: Literal["scale", "flat"] = "scale"
    flat_profit_dollars: Optional[float] = Field(default=None, ge=0)
    commission_basis: Literal["profit", "job"] = "profit"
    commission_rate: Optional[float] = Field(default=None, ge=0, le=1)  # fraction, e.g. 0.30
    discounts: list[DiscountInput] = Field(default_factory=list)
    selected_tier: Literal["good", "better", "best"] = "good"
    parent_estimate_id: Optional[int] = None
    source_proposal_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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

    # Route to the low-slope calculator whenever the roof_type is a low-slope system, regardless
    # of the client-sent slope_type flag. The set is config-driven (granular exhibit_b keys) plus
    # the coarse aliases so a caller can never mismatch roof_type and calculator.
    low_slope_keys = LOW_SLOPE_ROOF_TYPES | set(_priced_low_slope_types(cfg_row.config, body.code_zone))
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
    if body.measurement_id is not None:
        m = db.get(Measurement, body.measurement_id)
        if m is None or m.tenant_id != db.info.get("tenant_id"):
            raise HTTPException(404, f"Measurement {body.measurement_id} not found")
        for field_name in cut_lfs:
            if not cut_lfs[field_name]:  # explicit field wins when non-zero; else measurement
                cut_lfs[field_name] = getattr(m, field_name) or 0

    # Build QuoteInput kwargs. The headline quote uses the FLAT base (Tim's standard pricing);
    # cut LFs are applied only to a separate cut_calc reference block below, so both the flat
    # and cut-adjusted numbers are shown side-by-side and Tim picks (golden proposals show he
    # prices standard roofs off the flat base, not the cut calculator).
    qkwargs = dict(
        code_zone=body.code_zone,
        slope_type=effective_slope_type,
        roof_type=body.roof_type,
        num_squares=body.num_squares,
        county=body.county,
        roof_cuts=body.roof_cuts,
        roof_height=body.roof_height,
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
        include_tapered=body.include_tapered,
        override_base_cost=body.override_base_cost,
        override_overhead=body.override_overhead,
        override_profit_per_sq=body.override_profit_per_sq,
        overhead_mode=body.overhead_mode,
        daily_series=[DailyOverheadSeries(series=s.series, days=s.days) for s in body.daily_series],
        profit_mode=body.profit_mode,
        flat_profit_dollars=body.flat_profit_dollars,
        base_tile_brand=body.base_tile_brand,
        commission_basis=body.commission_basis,
        commission_rate_override=body.commission_rate,
    )
    q = E.QuoteInput(**qkwargs)

    config = load_config(cfg_row.config)

    # Gutter accessories (elbows, leaf guard, 2-story uplift) only price alongside a
    # gutter run — reject them without gutter_lf so they can't silently drop to $0.
    if (body.gutter_elbows or body.leaf_guard != "none" or body.gutter_two_story) and not body.gutter_lf:
        raise HTTPException(
            422,
            detail="gutter_elbows, leaf_guard, and gutter_two_story require gutter_lf > 0.",
        )

    # Validate daily series names against config before engine call (→422, not 500)
    if body.daily_series:
        known_series = set(config.daily_overhead_rates().keys())
        unknown = [s.series for s in body.daily_series if s.series not in known_series]
        if unknown:
            raise HTTPException(
                422,
                detail=f"unknown daily_series name(s): {unknown}. "
                f"Valid series: {sorted(known_series)}",
            )

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
                            else config.commission_rate(effective_slope_type, body.code_zone))
        warnings = list(result.get("margin_warnings") or [])
        if adjusted_profit < 0 and "discount_exceeds_profit" not in warnings:
            warnings.append("discount_exceeds_profit")
        if profit_pct < config.raw["profit_floor_pct"] and "profit_floor" not in warnings:
            warnings.append("profit_floor")
        if combined_pct < config.raw["profit_plus_oh_floor_pct"] and "combined_floor" not in warnings:
            warnings.append("combined_floor")
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
    result["package_options"] = package_options(
        body.roof_type, float(body.num_squares), float(result["project_total"]),
        discount_total=float(result.get("discount_total") or 0),
    )

    # Cut-calculator reference (shown alongside the flat headline; Tim picks). A second estimate
    # with the RoofR cut LFs, attached only when cuts actually move the base (calibrated zone).
    # Pre-discount totals so the flat-vs-cut delta is purely the base difference.
    if any(cut_lfs.values()):
        try:
            cut_res = E.estimate(config, E.QuoteInput(**qkwargs, **cut_lfs))
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
        branch=body.branch,
        code_zone=body.code_zone,
        county=body.county,
        pricing_config_id=cfg_row.id,
        pricing_config_hash=cfg_row.config_hash,
        parent_id=parent_id,
        root_id=root_id,
        version_number=version_number,
        source_proposal_id=body.source_proposal_id,
        input_json=body.model_dump(),
        result_json=result,
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
    est.result_json = result
    db.flush()

    return result


@router.post("/repair-quote")
def repair_quote(
    body: RepairQuoteRequest,
    _claims=Depends(require_role("estimating_view")),
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
        )
        result = E.estimate_repair(config, r)
    except (ValueError, ConfigError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    result["branch"] = body.branch
    result["pricing_config_id"] = cfg_row.id
    result["pricing_config_hash"] = cfg_row.config_hash
    return result


def _estimate_row(row: Estimate) -> dict:
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
        "input_json": row.input_json or {},
        "result_json": row.result_json or {},
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
    _claims=Depends(require_role("estimating_view")),
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
    return [_estimate_row(r) for r in rows]


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
            "daily_overhead_rates": cfg.get("daily_overhead_rates") or {},
            "daily_overhead_weeks_rounding_mode": cfg.get("daily_overhead_weeks_rounding_mode") or "ceil",
            "weekly_profit_floor": cfg.get("weekly_profit_floor") or 2500,
            "job_profit_floor": cfg.get("job_profit_floor") or 2500,
            # v2: repair (time-based) quote config — roof-type categories + daily labor rates
            "repair": cfg.get("repair") or {},
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
