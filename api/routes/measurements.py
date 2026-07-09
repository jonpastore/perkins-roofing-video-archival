"""Measurement stub API — F2 manual-entry path. Full provider model in F2b.

Endpoints:
  POST  /measurements          create a manual measurement
  GET   /measurements/{id}     get a measurement by id

Authz: estimating_view for GET, estimating_manage for POST.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from app.models import Measurement, SessionLocal

router = APIRouter(prefix="/measurements", tags=["measurements"])


class MeasurementCreateRequest(BaseModel):
    total_sq: Optional[float] = None
    hips_lf: Optional[float] = None
    ridges_lf: Optional[float] = None
    valleys_lf: Optional[float] = None
    rakes_lf: Optional[float] = None
    eaves_lf: Optional[float] = None
    wall_flashings_lf: Optional[float] = None
    pitch_primary: Optional[float] = None
    provenance_note: Optional[str] = None


def _row_to_dict(row: Measurement) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "provider": row.provider,
        "status": row.status,
        "total_sq": row.total_sq,
        "hips_lf": row.hips_lf,
        "ridges_lf": row.ridges_lf,
        "valleys_lf": row.valleys_lf,
        "rakes_lf": row.rakes_lf,
        "eaves_lf": row.eaves_lf,
        "wall_flashings_lf": row.wall_flashings_lf,
        "pitch_primary": row.pitch_primary,
        "confidence": row.confidence,
        "provenance_note": row.provenance_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    }


@router.post("")
def create_measurement(
    body: MeasurementCreateRequest,
    claims=Depends(require_role("estimating_manage")),
):
    """Create a manual measurement entry. Sets provider='manual', confidence=null,
    and auto-builds provenance_note if not supplied."""
    email = claims.get("email") or "unknown"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    provenance = body.provenance_note or f"Manual entry by {email} on {now_str}"

    with SessionLocal() as db:
        row = Measurement(
            tenant_id=1,
            provider="manual",
            status="complete",
            total_sq=body.total_sq,
            hips_lf=body.hips_lf,
            ridges_lf=body.ridges_lf,
            valleys_lf=body.valleys_lf,
            rakes_lf=body.rakes_lf,
            eaves_lf=body.eaves_lf,
            wall_flashings_lf=body.wall_flashings_lf,
            pitch_primary=body.pitch_primary,
            confidence=None,
            provenance_note=provenance,
            created_by=email,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    return _row_to_dict(row)


@router.get("/{measurement_id}")
def get_measurement(
    measurement_id: int,
    _claims=Depends(require_role("estimating_view")),
):
    with SessionLocal() as db:
        row = db.get(Measurement, measurement_id)
    if row is None:
        raise HTTPException(404, f"Measurement {measurement_id} not found")
    return _row_to_dict(row)
