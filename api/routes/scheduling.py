"""Scheduling CRUD routes — ScheduledContent management.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements:
  - All endpoints → admin only via manage_scheduling (admin "*" covers it).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from app.models import ScheduledContent, SessionLocal

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ScheduledContentIn(BaseModel):
    kind: str
    ref_id: str
    publish_at: datetime
    target: str | None = None
    status: str | None = "scheduled"


class ScheduledContentUpdate(BaseModel):
    publish_at: datetime | None = None
    status: str | None = None
    target: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_dict(r: ScheduledContent) -> dict:
    return {
        "id": r.id,
        "kind": r.kind,
        "ref_id": r.ref_id,
        "publish_at": r.publish_at.isoformat() if r.publish_at else None,
        "status": r.status,
        "target": r.target,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_scheduled(
    status: str | None = None,
    claims=Depends(require_role("manage_scheduling")),
):
    with SessionLocal() as db:
        q = db.query(ScheduledContent)
        if status is not None:
            q = q.filter(ScheduledContent.status == status)
        rows = q.order_by(ScheduledContent.publish_at).all()
        return [_row_dict(r) for r in rows]


@router.post("", status_code=201)
def create_scheduled(
    body: ScheduledContentIn,
    claims=Depends(require_role("manage_scheduling")),
):
    with SessionLocal() as db:
        item = ScheduledContent(
            kind=body.kind,
            ref_id=body.ref_id,
            publish_at=body.publish_at,
            status=body.status or "scheduled",
            target=body.target,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return _row_dict(item)


@router.put("/{item_id}")
def update_scheduled(
    item_id: int,
    body: ScheduledContentUpdate,
    claims=Depends(require_role("manage_scheduling")),
):
    with SessionLocal() as db:
        item = db.get(ScheduledContent, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="scheduled item not found")
        if body.publish_at is not None:
            item.publish_at = body.publish_at
        if body.status is not None:
            item.status = body.status
        if body.target is not None:
            item.target = body.target
        db.commit()
        db.refresh(item)
        return _row_dict(item)


@router.delete("/{item_id}", status_code=204)
def delete_scheduled(
    item_id: int,
    claims=Depends(require_role("manage_scheduling")),
):
    with SessionLocal() as db:
        item = db.get(ScheduledContent, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="scheduled item not found")
        db.delete(item)
        db.commit()
