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


_URL_MAX = 1000


def _clip(value: Any, n: int = _URL_MAX) -> Any:
    """Keep URL columns inside the current varchar(1000) until migration 0061 lands."""
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= n else text[:n]


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
        url=_clip(photo.get("url")),
        captured_at=captured_at,
        lat=photo.get("lat"),
        lon=photo.get("lon"),
        raw=photo.get("raw") or {},
        content_hash=chash,
    )
    # `tags` is deliberately NOT written here. It is owned solely by set_publish_tags(), fed by
    # an account-wide tag pass. Neither the sync job nor the webhook knows a photo's tags, so
    # letting either write the column would mean one of them overwriting the other with [] —
    # silently dropping a photo out of a published gallery. Absent from `values` = untouched
    # on update, and the column default ([]) applies on insert.

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


def upsert_video(session: Session, video: dict[str, Any]) -> bool:
    """Hash-gated upsert of one normalized CompanyCam video (migration 0047).

    Same contract as upsert_photo — unique on (tenant_id, companycam_video_id), unchanged
    rows produce zero writes, returns True when something was written.

    ``internal`` is stored explicitly and defaults to True when the payload omits it: the
    safe default for media we could not classify is "do not publish". Publishers filter on
    it; nothing downstream should be reading it back out of ``raw``.
    """
    from app.models import CompanyCamVideo

    dialect = session.bind.dialect.name  # type: ignore[union-attr]
    tenant_id: int = session.info.get("tenant_id", 1)
    now = _utcnow()

    video_id = str(video["companycam_video_id"])
    chash = content_hash(video)

    captured_at = video.get("captured_at")
    if isinstance(captured_at, (int, float)):
        captured_at = datetime.fromtimestamp(captured_at, tz=timezone.utc).replace(tzinfo=None)

    values = dict(
        tenant_id=tenant_id,
        companycam_video_id=video_id,
        project_id=video.get("project_id"),
        url=_clip(video.get("url")),
        thumbnail_url=_clip(video.get("thumbnail_url")),
        captured_at=captured_at,
        lat=video.get("lat"),
        lon=video.get("lon"),
        status=video.get("status"),
        internal=bool(video.get("internal", True)),
        raw=video.get("raw") or {},
        content_hash=chash,
    )
    # `tags` is owned by set_publish_tags() — same contract as upsert_photo.

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        existing_hash = session.execute(
            select(CompanyCamVideo.content_hash).where(
                CompanyCamVideo.tenant_id == tenant_id,
                CompanyCamVideo.companycam_video_id == video_id,
            )
        ).scalar_one_or_none()

        if existing_hash == chash:
            log.debug("companycam mirror: video=%s status=unchanged", video_id)
            return False

        session.execute(
            pg_insert(CompanyCamVideo)
            .values(**values, created_at=now)
            .on_conflict_do_update(
                index_elements=["tenant_id", "companycam_video_id"],
                set_=values,
            )
        )
        log.debug("companycam mirror: video=%s status=upserted", video_id)
        return True

    # SQLite path (tests / dev): no ON CONFLICT DO UPDATE, so manual check.
    existing = session.execute(
        select(CompanyCamVideo).where(
            CompanyCamVideo.tenant_id == tenant_id,
            CompanyCamVideo.companycam_video_id == video_id,
        )
    ).scalar_one_or_none()

    if existing is None:
        session.execute(insert(CompanyCamVideo).values(**values, created_at=now))
        log.debug("companycam mirror: video=%s status=inserted", video_id)
        return True

    if existing.content_hash == chash:
        log.debug("companycam mirror: video=%s status=unchanged", video_id)
        return False

    for key, val in values.items():
        setattr(existing, key, val)
    session.flush()
    log.debug("companycam mirror: video=%s status=updated", video_id)
    return True


def set_publish_tags(session: Session, kind: str, tagged_ids: set[str], tag_id: str) -> dict:
    """Make the mirror's publish tags match an account-wide tag fetch, for one media kind.

    The SINGLE writer of `tags` (see upsert_photo). Two statements, both idempotent:
    stamp `[tag_id]` on every mirrored row in `tagged_ids`, and clear any row that still
    carries `tag_id` but is no longer in the set — so untagging in CompanyCam actually
    reaches the gallery instead of leaving a photo published forever.

    Deliberately NOT keyed on the sync job's incremental `needs_media` gate. That gate keys
    off the PROJECT's CompanyCam `updated_at`, which never moves again once a roof is
    finished — so anything gated by it could never reach the completed jobs the portfolio is
    built from, and a photo tagged today would never appear. This runs every time.

    `kind` is "photo" or "video". Returns {"tagged": n, "cleared": n} — the operator's only
    evidence the pass did anything, so it is counted rather than assumed.
    """
    from app.models import CompanyCamPhoto, CompanyCamVideo  # noqa: PLC0415

    if kind not in ("photo", "video"):
        raise ValueError(f"kind must be 'photo' or 'video'; got {kind!r}")

    model = CompanyCamPhoto if kind == "photo" else CompanyCamVideo
    id_col = model.companycam_photo_id if kind == "photo" else model.companycam_video_id
    tenant_id: int = session.info.get("tenant_id", 1)
    wanted = {str(i) for i in tagged_ids}

    tagged = cleared = 0
    # Only rows we mirror can be tagged; a tagged id we have never synced is simply not here
    # yet and will be picked up once its project syncs.
    rows = session.execute(
        select(model).where(model.tenant_id == tenant_id)
    ).scalars().all()
    for row in rows:
        current = [str(t) for t in (row.tags or [])]
        should = str(getattr(row, id_col.key)) in wanted
        if should and current != [tag_id]:
            row.tags = [tag_id]
            tagged += 1
        elif not should and tag_id in current:
            row.tags = [t for t in current if t != tag_id]
            cleared += 1
    session.flush()
    log.info("companycam tags: kind=%s tag=%s tagged=%d cleared=%d seen=%d",
             kind, tag_id, tagged, cleared, len(wanted))
    return {"tagged": tagged, "cleared": cleared}


def _epoch_to_dt(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    return value if isinstance(value, datetime) else None


def upsert_project(session: Session, project: dict[str, Any]) -> tuple[Any, bool]:
    """Upsert one raw CompanyCam project row and say whether its media needs re-fetching.

    Returns (row, needs_media). ``needs_media`` is True when we have never pulled this
    project's media, or when CompanyCam's ``updated_at`` has moved since we last did — that
    check is what turns a ~7,400-request full crawl into a nightly no-op.

    Deliberately NOT hash-gated like the photo/video upserts: the row is small, and the
    interesting comparison is one timestamp, not the whole payload.
    """
    from app.models import CompanyCamProject

    tenant_id: int = session.info.get("tenant_id", 1)
    project_id = str(project["id"])
    remote_updated = _epoch_to_dt(project.get("updated_at"))

    row = session.execute(
        select(CompanyCamProject).where(
            CompanyCamProject.tenant_id == tenant_id,
            CompanyCamProject.companycam_project_id == project_id,
        )
    ).scalar_one_or_none()

    if row is None:
        row = CompanyCamProject(tenant_id=tenant_id, companycam_project_id=project_id)
        session.add(row)
        needs_media = True
    else:
        needs_media = row.media_synced_at is None or (
            remote_updated is not None and (
                row.remote_updated_at is None or remote_updated > row.remote_updated_at
            )
        )

    row.name = project.get("name")
    row.address = project.get("address") or {}
    row.status = project.get("status")
    row.archived = bool(project.get("archived"))
    row.photo_count = project.get("photo_count")
    row.remote_updated_at = remote_updated
    session.flush()
    return row, needs_media


def mark_media_synced(session: Session, row: Any) -> None:
    """Stamp a project as media-synced. Only called after BOTH endpoints succeeded — a
    partial pull must re-run next time rather than being remembered as complete."""
    row.media_synced_at = _utcnow()
    session.flush()
