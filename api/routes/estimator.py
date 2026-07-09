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
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth import require_role
from app.models import Estimate, PricingConfig, SessionLocal
from core import estimator as E
from core.pricing_config import load_config

router = APIRouter(prefix="/estimator", tags=["estimator"])


def current_tenant_id() -> int:
    """Return the active tenant id. Single seam: F4 swaps this for multi-tenant JWT claims."""
    return 1


def _get_active_config_row(branch: str) -> Optional[PricingConfig]:
    """Fetch the active PricingConfig row for (current tenant, branch), or None."""
    with SessionLocal() as db:
        return db.execute(
            select(PricingConfig).where(
                PricingConfig.tenant_id == current_tenant_id(),
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/quote")
def quote(body: QuoteRequest, claims=Depends(require_role("estimating_view"))):
    """Compute an itemized roofing estimate.

    Uses the active config for the branch (or a pinned config_id).
    Returns HTTP 503 if no active config is seeded for the branch.
    Stamps pricing_config_id and pricing_config_hash on the response and
    persists an Estimate row for audit reproduction.
    """
    # Resolve the config row
    if body.config_id is not None:
        with SessionLocal() as db:
            cfg_row = db.get(PricingConfig, body.config_id)
        if cfg_row is None:
            raise HTTPException(404, f"Config {body.config_id} not found")
    else:
        cfg_row = _get_active_config_row(body.branch)

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
    )

    config = load_config(cfg_row.config)
    result = E.estimate(config, q)

    # Stamp config audit fields on response
    result["pricing_config_id"] = cfg_row.id
    result["pricing_config_hash"] = cfg_row.config_hash
    result["branch"] = body.branch
    result["code_zone"] = body.code_zone
    result["county"] = body.county

    # Persist estimate row for audit reproduction (TRD §2.2)
    with SessionLocal() as db:
        est = Estimate(
            tenant_id=current_tenant_id(),
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
        db.commit()

    return result


@router.get("/rates")
def rates(
    branch: str = Query(default="miami"),
    region: str = Query(default="FBC"),
    _claims=Depends(require_role("estimating_view")),
):
    """Rate tables from the active config for the current tenant's branch.

    Returns a minimal response with null config fields when no active config is seeded
    (graceful — no 503 here; the estimator UI can still show the form).
    """
    cfg_row = _get_active_config_row(branch)
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
        }

    # Legacy fallback — no active config seeded
    try:
        return {
            "branch": branch,
            "region": region,
            "config_id": None,
            "config_hash": None,
            "roof_types": list(E.BASE_COST_LM.get(region, {}).keys()),
            "base_cost_lm": E.BASE_COST_LM.get(region, {}),
            "overhead": E.OVERHEAD.get(region, {}),
            "profit_scale": E.PROFIT_SCALE,
            "roof_cuts": E.ROOF_CUTS,
            "tile_pointing": E.TILE_POINTING,
            "specialty_tile": E.SPECIALTY_TILE_UPGRADE.get(region, {}),
            "line_items": E.LINE_ITEMS.get(region, {}),
            "pm_incentive": E.PM_INCENTIVE,
        }
    except AttributeError:
        # New engine has no module-level constants; return minimal structure
        return {
            "branch": branch,
            "region": region,
            "config_id": None,
            "config_hash": None,
            "roof_types": [],
            "note": "No active config seeded for this branch. Activate a config version first.",
        }
