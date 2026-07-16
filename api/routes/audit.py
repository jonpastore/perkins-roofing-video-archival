"""Audit log reader — "what happened, and who did it".

GET /audit?hours=&actor=&action=&entity_type=&entity_id=&status=&source=&limit=
  → {entries: [...], count: int}

Admin-only (manage_config), matching /logs: an audit trail names people and what they did, so
it is not a reporting surface for every web_admin. Tenant-scoped by RLS — one tenant can never
read another's trail even if this route is wrong.

The filters are the three questions this actually gets asked, in order:
  "what happened lately"        -> hours
  "what did this person do"     -> actor
  "what happened to this thing" -> entity_type + entity_id
Each is backed by an index from migration 0036; without one, this becomes a seq-scan over the
busiest table in the schema.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role_db

router = APIRouter(prefix="/audit", tags=["audit"])

_MAX_HOURS = 24 * 90
_MAX_LIMIT = 1000


def _platform_entries(hours: int, actor: str | None, action: str | None,
                      request_id: str | None, limit: int) -> list[dict]:
    """Rows from the platform trail, shaped like audit_log rows so they can be merged.

    Separate table by design (see PlatformAuditLog): platform rows must not live behind an RLS
    policy flag in a table every tenant queries. The union happens HERE, where the reader is
    already a platform admin, so the split costs a join instead of a leak.
    """
    from datetime import datetime, timedelta, timezone

    from app.models import PlatformAuditLog, PlatformSessionLocal

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    with PlatformSessionLocal() as pdb:
        pdb.info["platform_scope"] = True
        q = pdb.query(PlatformAuditLog).filter(PlatformAuditLog.occurred_at >= since)
        if actor:
            q = q.filter(PlatformAuditLog.platform_admin_email == actor)
        if action:
            q = q.filter(PlatformAuditLog.action == action)
        if request_id:
            q = q.filter(PlatformAuditLog.request_id == request_id)
        rows = q.order_by(PlatformAuditLog.occurred_at.desc()).limit(limit).all()
        return [{
            "id": f"p{r.id}",
            "scope": "platform",
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "actor_email": r.platform_admin_email,
            "actor_role": "platform_admin",
            "impersonating": r.target_tenant_id is not None,
            "impersonating_as": r.target_tenant_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "method": r.method,
            "route": r.route,
            "path": r.path,
            "status_code": r.status_code,
            "request_id": r.request_id,
            "source": r.source,
            "detail": r.detail,
        } for r in rows]


@router.get("")
def list_audit(
    hours: int = Query(24, ge=1, le=_MAX_HOURS),
    actor: str | None = Query(None, description="actor_email, exact"),
    action: str | None = Query(None, description='e.g. "proposal.sign"'),
    entity_type: str | None = None,
    entity_id: str | None = None,
    status: int | None = Query(None, description="HTTP status, e.g. 403"),
    source: str | None = Query(None, description="api | job | script | system"),
    request_id: str | None = Query(None, description="ties a request across both trails"),
    scope: str = Query("tenant", pattern="^(tenant|platform|all)$",
                       description="tenant (default) | platform | all"),
    failures_only: bool = Query(False, description="status >= 400"),
    limit: int = Query(200, ge=1, le=_MAX_LIMIT),
    db: Session = Depends(get_db_session),
    claims: dict = Depends(require_role_db("manage_config")),
):
    """Most recent first. Bounded by `limit` — this table is the busiest in the schema.

    `scope=all` merges the tenant trail (audit_log) with the platform trail
    (platform_audit_log). They are separate tables so a policy bug can never expose platform
    history to a tenant; merging them here costs one extra query and no isolation. `request_id`
    is the join key when a single request spans both — e.g. a platform admin impersonating a
    tenant and then editing something.
    """
    from datetime import datetime, timedelta, timezone

    from app.models import AuditLog

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    if scope == "platform":
        entries = _platform_entries(hours, actor, action, request_id, limit)
        return {"count": len(entries), "entries": entries}

    q = db.query(AuditLog).filter(AuditLog.occurred_at >= since)
    if actor:
        q = q.filter(AuditLog.actor_email == actor)
    if action:
        q = q.filter(AuditLog.action == action)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditLog.entity_id == str(entity_id))
    if status is not None:
        q = q.filter(AuditLog.status_code == status)
    if source:
        q = q.filter(AuditLog.source == source)
    if request_id:
        q = q.filter(AuditLog.request_id == request_id)
    if failures_only:
        q = q.filter(AuditLog.status_code >= 400)

    rows = q.order_by(AuditLog.occurred_at.desc()).limit(limit).all()
    entries = [{
            "id": r.id,
            "scope": "tenant",
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "actor_email": r.actor_email,
            "actor_role": r.actor_role,
            "impersonating": r.impersonating,
            "impersonating_as": r.impersonating_as,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "method": r.method,
            "route": r.route,
            "path": r.path,
            "status_code": r.status_code,
            "request_id": r.request_id,
            "source": r.source,
            "detail": r.detail,
    } for r in rows]

    if scope == "all":
        entries += _platform_entries(hours, actor, action, request_id, limit)
        # One timeline, newest first — the point of merging is that you stop having to ask
        # "which table was that in?" at 2am.
        entries.sort(key=lambda e: e["occurred_at"] or "", reverse=True)
        entries = entries[:limit]
    return {"count": len(entries), "entries": entries}


@router.get("/actions")
def list_actions(
    hours: int = Query(24 * 7, ge=1, le=_MAX_HOURS),
    db: Session = Depends(get_db_session),
    claims: dict = Depends(require_role_db("manage_config")),
):
    """Which actions fired, how often, and how many failed — the "is anything on fire" view."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import case, func

    from app.models import AuditLog

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    rows = (db.query(
                AuditLog.action,
                func.count().label("n"),
                func.sum(case((AuditLog.status_code >= 400, 1), else_=0)).label("failed"),
                func.max(AuditLog.occurred_at).label("last"),
            )
            .filter(AuditLog.occurred_at >= since)
            .group_by(AuditLog.action)
            .order_by(func.count().desc())
            .all())
    return {"count": len(rows),
            "actions": [{"action": a, "n": n, "failed": int(f or 0),
                         "last": last.isoformat() if last else None}
                        for a, n, f, last in rows]}
