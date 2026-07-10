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
from app.models import Estimate, PricingConfig
from core import estimator as E
from core.estimator import DailyOverheadSeries
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

router = APIRouter(prefix="/estimator", tags=["estimator"])


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
    roof_type: Literal[
        "13_tile", "barrel_tile", "3tab_shingle", "dimensional_shingle", "standing_seam_metal"
    ] = "13_tile"
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
        if cfg_row is None:
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

    # Validate specialty_tile against the active config
    if body.specialty_tile is not None:
        valid = (cfg_row.config.get("specialty_tile_upgrade") or {}).get(body.code_zone, {})
        if not valid:
            # Schema lacks specialty_tile_upgrade — re-export from legacy with explicit TODO
            from core import _legacy_rates as _lr  # TODO(config-migrate): move to config schema
            valid = _lr.SPECIALTY_TILE_UPGRADE.get(body.code_zone, {})
        if body.specialty_tile not in valid:
            raise HTTPException(400, f"unknown specialty_tile for {body.code_zone}: {body.specialty_tile!r}")

    # Build QuoteInput
    q = E.QuoteInput(
        code_zone=body.code_zone,
        slope_type=body.slope_type,
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
    )

    config = load_config(cfg_row.config)

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

    # Persist estimate row for audit reproduction (TRD §2.2)
    est = Estimate(
        tenant_id=db.info["tenant_id"],
        branch=body.branch,
        code_zone=body.code_zone,
        county=body.county,
        pricing_config_id=cfg_row.id,
        pricing_config_hash=cfg_row.config_hash,
        input_json=body.model_dump(),
        result_json=result,
        created_by=claims.get("email") or "unknown",
    )
    db.add(est)
    db.flush()

    return result


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
        return {
            "branch": branch,
            "region": zone,
            "config_id": cfg_row.id,
            "config_hash": cfg_row.config_hash,
            "roof_types": list((cfg.get("sloped_base_cost_lm") or {}).get(zone, {}).keys()),
            "base_cost_lm": (cfg.get("sloped_base_cost_lm") or {}).get(zone, {}),
            "overhead": (cfg.get("sloped_overhead") or {}).get(zone, {}),
            "profit_scale": cfg.get("profit_scale", []),
            "roof_cuts": cfg.get("roof_cuts", {}),
            "tile_pointing": cfg.get("tile_pointing", {}),
            "specialty_tile": (cfg.get("specialty_tile_upgrade") or {}).get(zone, {}),
            "line_items": (cfg.get("line_items") or {}).get(zone, {}),
            "pm_incentive": cfg.get("pm_incentive", {}),
            # v2: day-based overhead and profit-floor config fields for the UI
            "daily_overhead_rates": cfg.get("daily_overhead_rates") or {},
            "daily_overhead_weeks_rounding_mode": cfg.get("daily_overhead_weeks_rounding_mode") or "ceil",
            "weekly_profit_floor": cfg.get("weekly_profit_floor") or 2500,
            "job_profit_floor": cfg.get("job_profit_floor") or 2500,
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
