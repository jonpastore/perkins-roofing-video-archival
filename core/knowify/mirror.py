"""Pure DB logic for the Knowify raw-mirror layer (Wave 2).

No network calls here — fetch lives in jobs/knowify_sync.py.
All functions accept an already-stamped SQLAlchemy Session (tenant_id set
in session.info; RLS GUC fires on Postgres via the after_begin event).

Log safety: log lines carry entity + knowify_id + status ONLY.
             Raw payload bodies are NEVER logged (PII).
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


def content_hash(payload: dict) -> str:
    """Stable canonical sha256 of a dict.

    sort_keys=True + compact separators → identical dicts produce identical
    hashes regardless of key insertion order.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def upsert_raw(
    session: Session,
    entity: str,
    records: list[dict[str, Any]],
    id_key: str = "Id",
) -> dict[str, int]:
    """Hash-gated upsert of Knowify records into knowify_raw_records.

    Unique constraint: (tenant_id, entity, knowify_id).
    Unchanged records (same content_hash) produce zero writes (AC-2).

    Returns dict with keys inserted / updated / unchanged.
    """
    from app.models import KnowifyRawRecord

    # Resolve the dialect-aware insert once.
    dialect = session.bind.dialect.name  # type: ignore[union-attr]
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        _insert = pg_insert
    else:
        _insert = insert  # SQLite path (tests / dev)

    tenant_id: int = session.info.get("tenant_id", 1)
    now = _utcnow()

    counts = {"inserted": 0, "updated": 0, "unchanged": 0}

    for rec in records:
        kid = str(rec[id_key])
        chash = content_hash(rec)

        if dialect == "postgresql":
            # Pre-check current row state so we can classify insert/update/unchanged
            # without relying on rowcount (pg8000 returns 1 for all ON CONFLICT cases).
            # ponytail: one SELECT + one upsert per record; fine at single-tenant volume.
            existing_row = session.execute(
                select(
                    KnowifyRawRecord.content_hash,
                    KnowifyRawRecord.is_present,
                ).where(
                    KnowifyRawRecord.tenant_id == tenant_id,
                    KnowifyRawRecord.entity == entity,
                    KnowifyRawRecord.knowify_id == kid,
                )
            ).fetchone()

            if existing_row is None:
                action = "inserted"
            elif existing_row[0] != chash or not existing_row[1]:
                # hash changed OR row was tombstoned → needs write
                action = "updated"
            else:
                action = "unchanged"

            if action != "unchanged":
                stmt = (
                    _insert(KnowifyRawRecord)
                    .values(
                        tenant_id=tenant_id,
                        entity=entity,
                        knowify_id=kid,
                        payload=rec,
                        content_hash=chash,
                        is_present=True,
                        deleted_at=None,
                        fetched_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "entity", "knowify_id"],
                        set_={
                            "payload": rec,
                            "content_hash": chash,
                            "is_present": True,
                            "deleted_at": None,
                            "fetched_at": now,
                        },
                    )
                )
                session.execute(stmt)

            counts[action] += 1
            log.debug("knowify mirror: entity=%s id=%s status=%s", entity, kid, action)
        else:
            # SQLite path: no ON CONFLICT DO UPDATE WHERE, so manual check.
            existing = session.execute(
                select(KnowifyRawRecord).where(
                    KnowifyRawRecord.tenant_id == tenant_id,
                    KnowifyRawRecord.entity == entity,
                    KnowifyRawRecord.knowify_id == kid,
                )
            ).scalar_one_or_none()

            if existing is None:
                session.execute(
                    insert(KnowifyRawRecord).values(
                        tenant_id=tenant_id,
                        entity=entity,
                        knowify_id=kid,
                        payload=rec,
                        content_hash=chash,
                        is_present=True,
                        deleted_at=None,
                        fetched_at=now,
                    )
                )
                counts["inserted"] += 1
                log.debug("knowify mirror: entity=%s id=%s status=inserted", entity, kid)
            elif existing.content_hash != chash or not existing.is_present:
                # Hash changed OR row was tombstoned and is returning — write update.
                existing.payload = rec
                existing.content_hash = chash
                existing.is_present = True
                existing.deleted_at = None
                existing.fetched_at = now
                session.flush()  # materialize before the next SELECT in this session
                counts["updated"] += 1
                log.debug("knowify mirror: entity=%s id=%s status=updated", entity, kid)
            else:
                counts["unchanged"] += 1
                log.debug("knowify mirror: entity=%s id=%s status=unchanged", entity, kid)

    return counts


def tombstone_absent(
    session: Session,
    entity: str,
    present_ids: set[str],
) -> int:
    """Mark rows for this entity whose knowify_id is NOT in present_ids as tombstoned.

    Sets is_present=FALSE + deleted_at=now() only on rows currently is_present=TRUE,
    so re-runs are idempotent (already-tombstoned rows are not touched again).
    A returning id un-tombstones (is_present flips back to TRUE via upsert_raw).

    Returns the count of newly tombstoned rows.
    """
    from app.models import KnowifyRawRecord

    tenant_id: int = session.info.get("tenant_id", 1)
    now = _utcnow()

    # Fetch candidates: present rows for this entity whose id is absent.
    rows = session.execute(
        select(KnowifyRawRecord).where(
            KnowifyRawRecord.tenant_id == tenant_id,
            KnowifyRawRecord.entity == entity,
            KnowifyRawRecord.is_present.is_(True),
        )
    ).scalars().all()

    count = 0
    for row in rows:
        if row.knowify_id not in present_ids:
            row.is_present = False
            row.deleted_at = now
            count += 1
            log.info(
                "knowify mirror: entity=%s id=%s status=tombstoned",
                entity,
                row.knowify_id,
            )

    return count


def write_state(
    session: Session,
    entity: str,
    *,
    rows_seen: int,
    status: str,
    high_water: datetime | None = None,
) -> None:
    """Upsert knowify_sync_state for (tenant_id, entity).

    Records last_run_at, last_status, rows_seen, and optionally last_high_water.
    Idempotent: ON CONFLICT updates in place.
    """
    from app.models import KnowifySyncState

    dialect = session.bind.dialect.name  # type: ignore[union-attr]
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        _insert = pg_insert
    else:
        _insert = insert

    tenant_id: int = session.info.get("tenant_id", 1)
    now = _utcnow()

    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "entity": entity,
        "last_run_at": now,
        "last_status": status,
        "rows_seen": rows_seen,
        "updated_at": now,
    }
    if high_water is not None:
        values["last_high_water"] = high_water

    if dialect == "postgresql":
        update_set: dict[str, Any] = {
            "last_run_at": now,
            "last_status": status,
            "rows_seen": rows_seen,
            "updated_at": now,
        }
        if high_water is not None:
            update_set["last_high_water"] = high_water

        stmt = (
            _insert(KnowifySyncState)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_knowify_sync_state_tenant_entity",
                set_=update_set,
            )
        )
        session.execute(stmt)
    else:
        # SQLite: manual upsert
        existing = session.execute(
            select(KnowifySyncState).where(
                KnowifySyncState.tenant_id == tenant_id,
                KnowifySyncState.entity == entity,
            )
        ).scalar_one_or_none()

        if existing is None:
            session.execute(insert(KnowifySyncState).values(**values))
        else:
            existing.last_run_at = now
            existing.last_status = status
            existing.rows_seen = rows_seen
            existing.updated_at = now
            if high_water is not None:
                existing.last_high_water = high_water

    log.info(
        "knowify mirror: write_state entity=%s status=%s rows_seen=%d",
        entity,
        status,
        rows_seen,
    )
