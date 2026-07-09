"""Pricing config admin API — versioned, immutable per-tenant per-branch configs.

Endpoints:
  GET    /estimator/configs?branch=miami        list versions for branch
  POST   /estimator/configs                     create new version
  GET    /estimator/configs/active?branch=miami get active config for branch
  GET    /estimator/configs/diff?from_id=&to_id= field-level JSON diff
  GET    /estimator/configs/{id}                get version detail + hash
  POST   /estimator/configs/{id}/activate       activate version (idempotent)

Authz:
  estimating_view  → GET endpoints
  estimating_manage → POST / activate
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import PricingConfig
from core.pricing_config import compute_hash as _core_compute_hash

router = APIRouter(prefix="/estimator/configs", tags=["pricing_configs"])




# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ConfigCreateRequest(BaseModel):
    branch: str
    label: Optional[str] = None
    config: dict


class ConfigResponse(BaseModel):
    id: int
    tenant_id: int
    branch: str
    version: int
    label: Optional[str]
    config_hash: str
    is_active: bool
    created_at: str
    created_by: str

    model_config = {"from_attributes": True}


def _row_to_dict(row: PricingConfig, include_config: bool = False) -> dict:
    d = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "branch": row.branch,
        "version": row.version,
        "label": row.label,
        "config_hash": row.config_hash,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    }
    if include_config:
        d["config"] = row.config
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/active")
def get_active_config(
    branch: str = Query(...),
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Return the currently active config for a branch."""
    row = db.execute(
        select(PricingConfig).where(
            PricingConfig.branch == branch,
            PricingConfig.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"No active config for branch {branch!r}")
    return _row_to_dict(row, include_config=True)


def _flatten(obj, prefix: str = "") -> dict:
    """Recursively flatten a dict into dot-path keys.

    Lists are treated as leaf values (not recursed into) so that array-valued
    config fields like profit_scale compare as atomic values.
    """
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten(v, path))
            else:
                out[path] = v
    else:
        out[prefix] = obj
    return out


@router.get("/diff")
def diff_configs(
    from_id: int = Query(...),
    to_id: int = Query(...),
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Return a field-level dot-path diff between two config versions.

    Response shape:
      {from_id, to_id, from_hash, to_hash,
       changes: [{path, from_value, to_value}, ...],   # sorted by path
       changed_count: N}

    Lists are treated as leaf values. Added keys have from_value=null;
    removed keys have to_value=null.
    """
    a = db.get(PricingConfig, from_id)
    b = db.get(PricingConfig, to_id)
    if a is None:
        raise HTTPException(404, f"Config {from_id} not found")
    if b is None:
        raise HTTPException(404, f"Config {to_id} not found")

    flat_a = _flatten(a.config or {})
    flat_b = _flatten(b.config or {})

    all_paths = sorted(set(flat_a) | set(flat_b))
    changes = [
        {"path": p, "from_value": flat_a.get(p), "to_value": flat_b.get(p)}
        for p in all_paths
        if flat_a.get(p) != flat_b.get(p)
    ]

    return {
        "from_id": from_id,
        "to_id": to_id,
        "from_hash": a.config_hash,
        "to_hash": b.config_hash,
        "changes": changes,
        "changed_count": len(changes),
    }


@router.get("")
def list_configs(
    branch: Optional[str] = Query(None),
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """List all versions for a branch (or all branches if branch omitted)."""
    stmt = select(PricingConfig)
    if branch:
        stmt = stmt.where(PricingConfig.branch == branch)
    stmt = stmt.order_by(PricingConfig.branch, PricingConfig.version.desc())
    rows = db.execute(stmt).scalars().all()
    return [_row_to_dict(r) for r in rows]


@router.get("/{config_id}")
def get_config(
    config_id: int,
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Get a specific config version including the full config body and hash."""
    row = db.get(PricingConfig, config_id)
    if row is None:
        raise HTTPException(404, f"Config {config_id} not found")
    return _row_to_dict(row, include_config=True)


@router.post("")
def create_config(
    body: ConfigCreateRequest,
    claims=Depends(require_role("estimating_manage")),
    db: Session = Depends(get_db_session),
):
    """Create a new immutable config version. Server computes the RFC 8785 hash."""
    config_hash = _core_compute_hash(body.config)

    # Compute next version number for (caller's tenant, branch)
    from sqlalchemy import func
    tenant_id = db.info["tenant_id"]
    max_ver = db.execute(
        select(func.max(PricingConfig.version)).where(
            PricingConfig.tenant_id == tenant_id,
            PricingConfig.branch == body.branch,
        )
    ).scalar()
    next_version = (max_ver or 0) + 1

    row = PricingConfig(
        tenant_id=tenant_id,
        branch=body.branch,
        version=next_version,
        label=body.label,
        config=body.config,
        config_hash=config_hash,
        is_active=False,
        created_by=claims.get("email") or "unknown",
    )
    db.add(row)
    try:
        db.flush()
        db.refresh(row)
    except IntegrityError:
        raise HTTPException(409, "Config version conflict — retry")

    return _row_to_dict(row, include_config=True)


@router.post("/{config_id}/activate")
def activate_config(
    config_id: int,
    claims=Depends(require_role("estimating_manage")),
    db: Session = Depends(get_db_session),
):
    """Activate a config version. Deactivates the current active version atomically.
    Idempotent: activating an already-active version returns 200 with no changes.
    """
    target = db.get(PricingConfig, config_id)
    if target is None:
        raise HTTPException(404, f"Config {config_id} not found")

    if target.is_active:
        # Idempotent re-activate — no-op
        return _row_to_dict(target)

    # Deactivate any currently active row for this (tenant, branch)
    current_active = db.execute(
        select(PricingConfig).where(
            PricingConfig.tenant_id == target.tenant_id,
            PricingConfig.branch == target.branch,
            PricingConfig.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if current_active is not None:
        current_active.is_active = False

    target.is_active = True
    db.flush()
    db.refresh(target)

    return _row_to_dict(target)
