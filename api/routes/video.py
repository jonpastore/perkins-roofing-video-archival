"""Video approval routes — admin-only mini-series proposal review and approval.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - approve_video  → admin only (sales is denied; admin passes via the "*" wildcard)
  - manage_series  → admin only
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from app.models import MiniSeries, SessionLocal

router = APIRouter(prefix="/video", tags=["video"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class Part(BaseModel):
    title: str
    start: float
    end: float


class ApproveRequest(BaseModel):
    parts: list[Part] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _series_to_dict(s: MiniSeries) -> dict:
    return {
        "id": s.id,
        "video_id": s.video_id,
        "title": s.title,
        "parts": s.parts_json or [],
        "approved": s.approved,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/proposals")
def list_proposals(claims=Depends(require_role("approve_video"))):
    """Return all pending MiniSeries (approved==0)."""
    with SessionLocal() as db:
        rows = db.query(MiniSeries).filter(MiniSeries.approved == 0).all()
        return [_series_to_dict(r) for r in rows]


@router.get("/series")
def list_series(claims=Depends(require_role("approve_video"))):
    """Return ALL MiniSeries (approved and unapproved), ordered by id desc."""
    with SessionLocal() as db:
        rows = db.query(MiniSeries).order_by(MiniSeries.id.desc()).all()
        return [
            {
                "id": s.id,
                "video_id": s.video_id,
                "title": s.title,
                "approved": s.approved,
            }
            for s in rows
        ]


@router.get("/{series_id}")
def get_series(series_id: int, claims=Depends(require_role("approve_video"))):
    """Return one MiniSeries by id (any approval state)."""
    with SessionLocal() as db:
        row = db.get(MiniSeries, series_id)
        if row is None:
            raise HTTPException(status_code=404, detail="series not found")
        return _series_to_dict(row)


@router.post("/{series_id}/approve")
def approve_series(
    series_id: int,
    body: ApproveRequest,
    claims=Depends(require_role("approve_video")),
):
    """Approve a MiniSeries; optionally edit parts in/out points before approval."""
    with SessionLocal() as db:
        row = db.get(MiniSeries, series_id)
        if row is None:
            raise HTTPException(status_code=404, detail="series not found")
        if body.parts is not None:
            row.parts_json = [p.model_dump() for p in body.parts]
        row.approved = 1
        db.commit()
        db.refresh(row)
        return _series_to_dict(row)
