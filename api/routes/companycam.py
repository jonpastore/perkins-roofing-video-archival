"""CompanyCam inbound webhook + the mirror's read surface.

The webhook is SECURITY-CRITICAL and unauthenticated (HMAC-verified); the readers at the
bottom of this file are ordinary role-gated, tenant-scoped reads. See each section.

## Webhook — unauthenticated + HMAC-verified

A webhook carries no user token, so the ONLY thing that authenticates it is the
signature over the raw request body, keyed by the `token` we supply when creating the
webhook (COMPANYCAM_WEBHOOK_SECRET, Secret Manager). Rules:
  * no secret configured  -> 503 (refuse; never accept an unsigned/unverifiable body)
  * bad/absent signature  -> 401
  * stale/absent created_at -> 401 (replay window, below)
  * signature must be checked against the RAW bytes, before JSON parsing, with a
    constant-time compare (hmac.compare_digest).

⚠️ The algorithm is CompanyCam's, not ours: **base64(HMAC-SHA1(body))** in
`X-CompanyCam-Signature` (docs.companycam.com/docs/webhooks-1). This was written as
sha256-hexdigest ahead of the account, and a real event would have 401'd every time —
along with the envelope, which is `event_type`/`created_at`/`payload`/`webhook_id`, not
`type`/`payload`. Both confirmed against the published spec 2026-08-02, before any live
event has ever been received.

Replay protection uses the envelope's `created_at` rather than a header: it is INSIDE the
signed body, so an attacker replaying a captured request cannot re-stamp it without
invalidating the signature. CompanyCam sends no timestamp header to use instead.

CompanyCam maps to the Perkins account (tenant 1) today, so photos are mirrored under
that tenant and RLS applies. A per-tenant webhook secret can replace the constant when a
second CompanyCam account exists.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role

log = logging.getLogger(__name__)

router = APIRouter(prefix="/companycam", tags=["companycam"])

_COMPANYCAM_TENANT_ID = 1
#: Accepted age of an event, in seconds, either side of now. Wide enough for CompanyCam's
#: retries and ordinary clock skew; short enough that a captured request stops working.
_REPLAY_WINDOW_S = 300


def _verify_signature(raw_body: bytes, signature: str) -> None:
    """Raise 503 if unconfigured, 401 if the signature does not match. Returns on success."""
    secret = os.getenv("COMPANYCAM_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="companycam webhook not configured")
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    if not hmac.compare_digest(expected, signature or ""):
        raise HTTPException(status_code=401, detail="invalid signature")


def _check_not_replayed(created_at) -> None:
    """401 unless the signed `created_at` is inside the replay window.

    Absent or unparseable is a rejection, not a pass: a replay defence that an attacker can
    switch off by dropping a field is not a defence. CompanyCam always sends it.
    """
    try:
        age = time.time() - float(created_at)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="missing created_at") from None
    if abs(age) > _REPLAY_WINDOW_S:
        raise HTTPException(status_code=401, detail="event outside replay window")


@router.post("/webhook")
async def companycam_webhook(
    request: Request,
    x_companycam_signature: str = Header(default=""),
):
    """Mirror a CompanyCam photo or video lifecycle event into the mirror (tenant 1)."""
    raw_body = await request.body()
    _verify_signature(raw_body, x_companycam_signature)

    try:
        payload = json.loads(raw_body.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc

    _check_not_replayed(payload.get("created_at"))

    event = str(payload.get("event_type") or "")
    media_raw = payload.get("payload") or {}

    # Only photo/video create+update carry mirrorable media. Everything else: ack, no work.
    # Videos are a separate v2 resource with their own payload shape (see adapters.companycam),
    # and the same nightly job mirrors both — a webhook that handled only photos would leave
    # video a day stale for the portfolio reader that consumes them side by side.
    kind = event.split(".")[0]
    if kind not in ("photo", "video") or not isinstance(media_raw, dict) or "id" not in media_raw:
        return {"ok": True, "ignored": event or "unknown"}

    from adapters.companycam import normalize_photo, normalize_video
    from app.models import SessionLocal
    from core.companycam.mirror import upsert_photo, upsert_video

    if kind == "photo":
        media, upsert, id_key = normalize_photo(media_raw), upsert_photo, "companycam_photo_id"
    else:
        media, upsert, id_key = normalize_video(media_raw), upsert_video, "companycam_video_id"

    with SessionLocal() as db:
        db.info["tenant_id"] = _COMPANYCAM_TENANT_ID  # RLS GUC stamped on after_begin
        changed = upsert(db, media)
        db.commit()

    log.info(
        "companycam webhook: event=%s %s=%s changed=%s",
        event, kind, media[id_key], changed,
    )
    return {"ok": True, "event": event, "changed": changed}


# ---------------------------------------------------------------------------
# Readers (#360) — the mirror had no read surface of its own
# ---------------------------------------------------------------------------
#
# jobs/companycam_sync.py has been filling these tables since 2026-07-28 (prod: ~156k photos,
# ~11.7k videos across ~3.7k projects) and the only thing that read them back was
# api/routes/portfolio.py, through a publish-permission filter, for one project at a time.
# There was no way to answer "what media do we hold for this job" without writing SQL.
#
# Both readers are tenant-scoped through get_db_session (RLS does the isolating) and paginated
# — an unbounded SELECT here returns six figures of rows.
#
# `lat`/`lon` are deliberately NOT returned. They are the property's location, and CompanyCam
# also burns those coordinates into the image pixels (core/pii.py is text-only and cannot see
# them). Nothing needs coordinates from this endpoint today, and the cheapest way to keep them
# out of something public is to not hand them out.

_MAX_LIMIT = 500


@router.get("/photos")
def list_photos(
    project_id: str | None = Query(None, description="CompanyCam project id"),
    limit: int = Query(100, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """Mirrored CompanyCam photos, newest capture first."""
    from app.models import CompanyCamPhoto  # noqa: PLC0415

    stmt = select(CompanyCamPhoto)
    if project_id:
        stmt = stmt.where(CompanyCamPhoto.project_id == str(project_id))
    stmt = stmt.order_by(CompanyCamPhoto.captured_at.desc().nullslast(),
                         CompanyCamPhoto.id.desc()).limit(limit).offset(offset)
    return [
        {
            "companycam_photo_id": p.companycam_photo_id,
            "project_id": p.project_id,
            "url": p.url,
            "tags": p.tags or [],
            "captured_at": p.captured_at.isoformat() if p.captured_at else None,
        }
        for p in db.execute(stmt).scalars().all()
    ]


@router.get("/videos")
def list_videos(
    project_id: str | None = Query(None, description="CompanyCam project id"),
    include_internal: bool = Query(
        False, description="Include crew-only media. Never publish these."),
    limit: int = Query(100, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _claims=Depends(require_role("quoting_view")),
    db: Session = Depends(get_db_session),
):
    """Mirrored CompanyCam videos, newest capture first.

    Internal media is excluded unless explicitly asked for: crews mark clips internal-only and
    they must never reach a proposal or a public project page. The mirror defaults `internal`
    to True when a payload omits it, so the safe default here is to hide, not to show.
    """
    from app.models import CompanyCamVideo  # noqa: PLC0415

    stmt = select(CompanyCamVideo)
    if project_id:
        stmt = stmt.where(CompanyCamVideo.project_id == str(project_id))
    if not include_internal:
        stmt = stmt.where(CompanyCamVideo.internal.is_(False))
    stmt = stmt.order_by(CompanyCamVideo.captured_at.desc().nullslast(),
                         CompanyCamVideo.id.desc()).limit(limit).offset(offset)
    return [
        {
            "companycam_video_id": v.companycam_video_id,
            "project_id": v.project_id,
            "url": v.url,
            "thumbnail_url": v.thumbnail_url,
            "status": v.status,
            "internal": bool(v.internal),
            "captured_at": v.captured_at.isoformat() if v.captured_at else None,
        }
        for v in db.execute(stmt).scalars().all()
    ]
