"""CompanyCam inbound webhook — SECURITY-CRITICAL, unauthenticated + HMAC-verified.

A webhook carries no user token, so the ONLY thing that authenticates it is an
HMAC-SHA256 signature over the raw request body using a shared secret
(COMPANYCAM_WEBHOOK_SECRET, Secret Manager). Rules:
  * no secret configured  -> 503 (refuse; never accept an unsigned/unverifiable body)
  * bad/absent signature  -> 401
  * signature must be checked against the RAW bytes, before JSON parsing, with a
    constant-time compare (hmac.compare_digest).

CompanyCam maps to the Perkins account (tenant 1) today, so photos are mirrored under
that tenant and RLS applies. A per-tenant webhook secret can replace the constant when a
second CompanyCam account exists.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request

log = logging.getLogger(__name__)

router = APIRouter(prefix="/companycam", tags=["companycam"])

_COMPANYCAM_TENANT_ID = 1


def _verify_signature(raw_body: bytes, signature: str) -> None:
    """Raise 503 if unconfigured, 401 if the signature does not match. Returns on success."""
    secret = os.getenv("COMPANYCAM_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="companycam webhook not configured")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise HTTPException(status_code=401, detail="invalid signature")


@router.post("/webhook")
async def companycam_webhook(
    request: Request,
    x_companycam_signature: str = Header(default=""),
):
    """Mirror a CompanyCam photo lifecycle event into companycam_photos (tenant 1)."""
    raw_body = await request.body()
    _verify_signature(raw_body, x_companycam_signature)

    try:
        payload = json.loads(raw_body.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc

    # ponytail: CompanyCam webhook envelope assumed to be {"type": "photo.*", "payload": {photo}}.
    # Confirm the exact envelope + signature header/format against live events when the account
    # is connected; also add timestamp/replay protection then. Upgrade path is this one function.
    event = str(payload.get("type") or "")
    photo_raw = payload.get("payload") or {}

    # Only photo create/update carry a mirrorable photo. Deletes/other events: ack, no work.
    if not event.startswith("photo.") or not isinstance(photo_raw, dict) or "id" not in photo_raw:
        return {"ok": True, "ignored": event or "unknown"}

    from adapters.companycam import normalize_photo
    from app.models import SessionLocal
    from core.companycam.mirror import upsert_photo

    photo = normalize_photo(photo_raw)
    with SessionLocal() as db:
        db.info["tenant_id"] = _COMPANYCAM_TENANT_ID  # RLS GUC stamped on after_begin
        changed = upsert_photo(db, photo)
        db.commit()

    log.info(
        "companycam webhook: event=%s photo=%s changed=%s",
        event, photo["companycam_photo_id"], changed,
    )
    return {"ok": True, "event": event, "changed": changed}
