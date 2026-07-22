"""Scheduling CRUD routes — ScheduledContent management.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements:
  - All endpoints → admin only via manage_scheduling (admin "*" covers it).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from api.routes.video import clean_label
from app.models import Article, MiniSeries, ScheduledContent
from core.timeutil import iso_utc, to_naive_utc

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class ScheduledContentIn(BaseModel):
    kind: str
    ref_id: str
    publish_at: datetime
    target: str | None = None
    # status intentionally absent — new items are always forced to 'scheduled'


class ScheduledContentUpdate(BaseModel):
    publish_at: datetime | None = None
    target: str | None = None
    # status intentionally absent from update — status is derived from outcome, not set manually


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_display_name(db, kind: str, ref_id: str) -> str:
    """Return a clean human-readable title for a scheduled item.

    - article → Article.title (falls back to ref_id slug)
    - reel/series → MiniSeries.title cleaned via clean_label; falls back to ref_id
    """
    if kind == "article":
        row = db.query(Article.title).filter(Article.slug == ref_id).first()
        return row[0] if row and row[0] else ref_id
    else:
        # ref_id is the mini_series integer id stored as string
        try:
            series_id = int(ref_id)
        except (ValueError, TypeError):
            return ref_id
        row = db.query(MiniSeries.title).filter(MiniSeries.id == series_id).first()
        if row and row[0]:
            return clean_label(row[0]) or ref_id
        return ref_id


def _resolved_wp_base() -> str:
    """WordPress base URL for building post links. The admin-config value (PlatformConfig WP_URL,
    editable in the dashboard) WINS; falls back to the WP_URL env baked at deploy. This lets the
    staging/prod site URL be changed from Admin → Config without a redeploy."""
    import os
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415
        with PlatformSessionLocal() as pdb:
            pdb.info["platform_scope"] = True
            row = pdb.get(PlatformConfig, "WP_URL")
            if row and (row.value or "").strip():
                return row.value.strip().rstrip("/")
    except Exception:  # noqa: BLE001 — never break the response on a config lookup
        pass
    return (os.environ.get("WP_URL") or "").rstrip("/")


def _published_url(db, kind: str, ref_id: str) -> str | None:
    """For a published article, the live WordPress post URL (else None)."""
    if db is None or kind != "article":
        return None
    row = db.query(Article.wp_post_id).filter(Article.slug == ref_id).first()
    wp_post_id = row[0] if row else None
    if not wp_post_id:
        return None
    base = _resolved_wp_base()
    return f"{base}/?p={wp_post_id}" if base else None


def _row_dict(r: ScheduledContent, db=None) -> dict:
    display_name = _resolve_display_name(db, r.kind, r.ref_id) if db is not None else r.ref_id
    return {
        "id": r.id,
        "kind": r.kind,
        "ref_id": r.ref_id,
        "display_name": display_name,
        "publish_at": iso_utc(r.publish_at),
        "status": r.status,
        "target": r.target,
        # Live link to where it was published (WordPress) — shown on published rows.
        "published_url": _published_url(db, r.kind, r.ref_id),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
def list_scheduled(
    status: str | None = None,
    claims=Depends(require_role("manage_scheduling")),
    db: Session = Depends(get_db_session),
):
    q = db.query(ScheduledContent)
    if status is not None:
        q = q.filter(ScheduledContent.status == status)
    rows = q.order_by(ScheduledContent.publish_at).all()
    return [_row_dict(r, db) for r in rows]


@router.post("", status_code=201)
def create_scheduled(
    body: ScheduledContentIn,
    claims=Depends(require_role("manage_scheduling")),
    db: Session = Depends(get_db_session),
):
    item = ScheduledContent(
        tenant_id=db.info["tenant_id"],
        kind=body.kind,
        ref_id=body.ref_id,
        publish_at=to_naive_utc(body.publish_at),
        status="scheduled",
        target=body.target,
    )
    db.add(item)
    db.flush()
    db.refresh(item)
    return _row_dict(item, db)


@router.put("/{item_id}")
def update_scheduled(
    item_id: int,
    body: ScheduledContentUpdate,
    claims=Depends(require_role("manage_scheduling")),
    db: Session = Depends(get_db_session),
):
    item = db.get(ScheduledContent, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="scheduled item not found")
    if body.publish_at is not None:
        item.publish_at = to_naive_utc(body.publish_at)
    if body.target is not None:
        item.target = body.target
    db.flush()
    db.refresh(item)
    return _row_dict(item, db)


@router.delete("/{item_id}", status_code=204)
def delete_scheduled(
    item_id: int,
    claims=Depends(require_role("manage_scheduling")),
    db: Session = Depends(get_db_session),
):
    item = db.get(ScheduledContent, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="scheduled item not found")
    db.delete(item)
    db.flush()
