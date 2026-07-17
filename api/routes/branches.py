"""Branch management (Zoom 2026-07-17): branches drive every branch selector.

Reads are open to any role that can view estimating/quoting surfaces; writes are
admin-only (manage_config). Branch keys are referenced by customers.branch and
pricing_configs.branch — keys are immutable once created (rename via `name` only),
and branches deactivate rather than delete (assets keep pointing at them).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Branch

router = APIRouter(prefix="/branches", tags=["branches"])


def _dict(b: Branch) -> dict:
    return {"id": b.id, "key": b.key, "name": b.name, "active": b.active, "sort": b.sort}


@router.get("")
def list_branches(
    include_inactive: bool = False,
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    q = select(Branch).order_by(Branch.sort, Branch.key)
    rows = db.execute(q).scalars().all()
    if not include_inactive:
        rows = [b for b in rows if b.active]
    return [_dict(b) for b in rows]


class BranchCreate(BaseModel):
    key: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    sort: int = 0


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None
    sort: int | None = None


@router.post("", status_code=201)
def create_branch(
    body: BranchCreate,
    claims=Depends(require_role("manage_config")),
    db: Session = Depends(get_db_session),
):
    exists = db.execute(select(Branch).where(Branch.key == body.key)).scalar_one_or_none()
    if exists:
        raise HTTPException(409, f"branch key {body.key!r} already exists")
    b = Branch(key=body.key, name=body.name, sort=body.sort)
    db.add(b)
    db.flush()
    return _dict(b)


@router.put("/{branch_id}")
def update_branch(
    branch_id: int,
    body: BranchUpdate,
    claims=Depends(require_role("manage_config")),
    db: Session = Depends(get_db_session),
):
    b = db.get(Branch, branch_id)
    if b is None:
        raise HTTPException(404, "branch not found")
    if body.name is not None:
        b.name = body.name
    if body.active is not None:
        b.active = body.active
    if body.sort is not None:
        b.sort = body.sort
    db.flush()
    return _dict(b)
