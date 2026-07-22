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

from adapters.quickbooks import branch_qb_mapping
from api.auth import get_db_session, require_role
from app.models import Branch, BranchAccounting

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
    # Stamp the verified tenant explicitly (matches customers.py) — the column default
    # (=1) is only coincidentally right for tenant 1; RLS WITH CHECK would 500 tenant 2.
    b = Branch(key=body.key, name=body.name, sort=body.sort, tenant_id=db.info["tenant_id"])
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


# ---------------------------------------------------------------------------
# B9 scaffold — per-branch QuickBooks/Knowify mapping admin API.
# Live QBO OAuth client is HELD; this only populates the mapping row that
# adapters/quickbooks.py's resolution seam reads once credentials exist.
# ---------------------------------------------------------------------------

def _accounting_dict(row: BranchAccounting) -> dict:
    return {
        "branch": row.branch,
        "qb_realm_id": row.qb_realm_id,
        "qb_company_name": row.qb_company_name,
        "knowify_subscription_id": row.knowify_subscription_id,
        "active": row.active,
    }


class BranchAccountingUpdate(BaseModel):
    qb_realm_id: str | None = Field(default=None, max_length=50)
    qb_company_name: str | None = Field(default=None, max_length=200)
    knowify_subscription_id: str | None = Field(default=None, max_length=100)
    active: bool | None = None


@router.get("/{branch}/accounting")
def get_branch_accounting(
    branch: str,
    claims=Depends(require_role("billing_view")),
    db: Session = Depends(get_db_session),
):
    row = branch_qb_mapping(db, branch)
    if row is None:
        raise HTTPException(404, f"no accounting mapping for branch {branch!r}")
    return _accounting_dict(row)


@router.put("/{branch}/accounting")
def put_branch_accounting(
    branch: str,
    body: BranchAccountingUpdate,
    claims=Depends(require_role("manage_config")),
    db: Session = Depends(get_db_session),
):
    b = db.execute(select(Branch).where(Branch.key == branch)).scalar_one_or_none()
    if b is None or not b.active:
        raise HTTPException(422, f"unknown or inactive branch {branch!r}")

    row = branch_qb_mapping(db, branch)
    if row is None:
        row = BranchAccounting(branch=branch, tenant_id=db.info["tenant_id"])
        db.add(row)

    if body.qb_realm_id is not None:
        row.qb_realm_id = body.qb_realm_id
    if body.qb_company_name is not None:
        row.qb_company_name = body.qb_company_name
    if body.knowify_subscription_id is not None:
        row.knowify_subscription_id = body.knowify_subscription_id
    if body.active is not None:
        row.active = body.active

    db.flush()
    return _accounting_dict(row)
