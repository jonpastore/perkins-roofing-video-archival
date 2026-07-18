"""Pure DB logic for the CompanyCam photo mirror.

No network calls here — fetch lives in adapters/companycam.py, orchestration in
jobs/companycam_sync.py. Accepts an already-stamped SQLAlchemy Session (tenant_id
set in session.info; RLS GUC fires on Postgres via the after_begin event). Mirrors
core/knowify/mirror.py's content_hash + hash-gated upsert idioms.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def content_hash(photo: dict[str, Any]) -> str:
    """Stable canonical sha256 of a normalized photo dict."""
    canonical = json.dumps(photo, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def upsert_photo(session: Session, photo: dict[str, Any]) -> bool:
    """Hash-gated upsert of one normalized CompanyCam photo.

    Unique constraint: (tenant_id, companycam_photo_id).
    Unchanged photos (same content_hash) produce zero writes.

    Returns True if the row was inserted or updated, False if unchanged.
    """
    from app.models import CompanyCamPhoto

    dialect = session.bind.dialect.name  # type: ignore[union-attr]
    tenant_id: int = session.info.get("tenant_id", 1)
    now = _utcnow()

    photo_id = str(photo["companycam_photo_id"])
    chash = content_hash(photo)

    captured_at = photo.get("captured_at")
    if isinstance(captured_at, (int, float)):
        captured_at = datetime.fromtimestamp(captured_at, tz=timezone.utc).replace(tzinfo=None)

    values = dict(
        tenant_id=tenant_id,
        companycam_photo_id=photo_id,
        project_id=photo.get("project_id"),
        url=photo.get("url"),
        captured_at=captured_at,
        lat=photo.get("lat"),
        lon=photo.get("lon"),
        tags=photo.get("tags") or [],
        raw=photo.get("raw") or {},
        content_hash=chash,
    )

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        existing_hash = session.execute(
            select(CompanyCamPhoto.content_hash).where(
                CompanyCamPhoto.tenant_id == tenant_id,
                CompanyCamPhoto.companycam_photo_id == photo_id,
            )
        ).scalar_one_or_none()

        if existing_hash == chash:
            log.debug("companycam mirror: photo=%s status=unchanged", photo_id)
            return False

        stmt = (
            pg_insert(CompanyCamPhoto)
            .values(**values, created_at=now)
            .on_conflict_do_update(
                index_elements=["tenant_id", "companycam_photo_id"],
                set_=values,
            )
        )
        session.execute(stmt)
        log.debug("companycam mirror: photo=%s status=upserted", photo_id)
        return True

    # SQLite path (tests / dev): no ON CONFLICT DO UPDATE, so manual check.
    existing = session.execute(
        select(CompanyCamPhoto).where(
            CompanyCamPhoto.tenant_id == tenant_id,
            CompanyCamPhoto.companycam_photo_id == photo_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        session.execute(insert(CompanyCamPhoto).values(**values, created_at=now))
        log.debug("companycam mirror: photo=%s status=inserted", photo_id)
        return True

    if existing.content_hash == chash:
        log.debug("companycam mirror: photo=%s status=unchanged", photo_id)
        return False

    for key, val in values.items():
        setattr(existing, key, val)
    session.flush()
    log.debug("companycam mirror: photo=%s status=updated", photo_id)
    return True
