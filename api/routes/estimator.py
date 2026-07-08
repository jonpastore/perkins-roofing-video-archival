"""Estimator routes — roofing bid calculator (Phase-2 STUB).

Backend-only: rebuilds Tim's pricing-workbook logic (core.estimator) behind an API so quote
data can be passed in. No UI in this cut (per 2026-07-08 direction). Integrates into the
existing admin dashboard later as a tab that POSTs here.

Export ``router`` only; mount in api/app.py with ``app.include_router(router)``.

Role requirements (core.authz):
  - manage_estimates → admin, web_admin, sales   (all estimator endpoints)
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import require_role
from core import estimator as E

router = APIRouter(prefix="/estimator", tags=["estimator"])


class QuoteRequest(BaseModel):
    region: str = Field(..., description="HVHZ | FBC")
    # roof_type: 13_tile | barrel_tile | 3tab_shingle | dimensional_shingle | standing_seam_metal
    roof_type: str = Field(..., description="roof type key; see GET /estimator/rates")
    num_squares: float = Field(..., gt=0)
    roof_cuts: str = "low"
    roof_height: str = "1_2_stories"
    tile_pointing: str = "no"
    specialty_tile: Optional[str] = None
    project_kind: str = "residential"
    pitch_7_12: bool = False
    demo: bool = False
    secondary_water_barrier: bool = False
    winterguard: bool = False
    stucco_metal_lf: float = 0
    penetrations: int = 0
    extra_line_items: list[str] = Field(default_factory=list)
    ridge_vent_lf: float = 0
    include_dumpster: bool = False
    override_base_cost: Optional[float] = None
    override_overhead: Optional[float] = None
    override_profit_per_sq: Optional[float] = None


@router.post("/quote")
def quote(body: QuoteRequest, _claims=Depends(require_role("manage_estimates"))):
    """Compute an itemized roofing estimate from the workbook logic. STUB — validate the
    rate tables against the live workbook before quoting real jobs (see core.estimator notes)."""
    q = E.QuoteInput(**body.model_dump())
    return E.estimate(q)


@router.get("/rates")
def rates(region: str = "FBC", _claims=Depends(require_role("manage_estimates"))):
    """Return the rate tables for a region so the future dashboard tab can render pickers.
    Prep for passing data in — the UI reads these to build its dropdowns."""
    return {
        "region": region,
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
