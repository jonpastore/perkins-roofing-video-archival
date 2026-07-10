"""api/routes/squares.py — Roof measurement via Google Solar API.

Endpoints:
  POST /squares/measure      geocode + Solar buildingInsights + persist Measurement
  GET  /squares/measurements recent measurements for the caller's tenant (newest first, limit 25)

Auth: estimating_view for both (GET); estimating_view for POST (same role reads the result).
Session: always via Depends(get_db_session) — STRICT TENANT MODE enforced.

Solar API key: SQUARES_API_KEY env var.  Missing key → 503 with clear detail.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Optional

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Measurement
from core.squares import parse_building_insights, segments_to_squares, staleness_warning

log = logging.getLogger(__name__)

router = APIRouter(prefix="/squares", tags=["squares"])

_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_SOLAR_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
_HTTP_TIMEOUT = 20


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class MeasureRequest(BaseModel):
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    key = os.environ.get("SQUARES_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=503,
            detail="SQUARES_API_KEY not configured — contact your administrator.",
        )
    return key


def _geocode(address: str, api_key: str) -> tuple[float, float, str]:
    """Resolve a free-text address to (lat, lng, formatted_address) via Google Geocoding."""
    try:
        resp = http_requests.get(
            _GEOCODING_URL,
            params={"address": address, "key": api_key},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except http_requests.exceptions.Timeout:
        raise HTTPException(502, "Geocoding API timed out — try again.")
    except http_requests.exceptions.RequestException as exc:
        raise HTTPException(502, f"Geocoding API error: {exc}")

    data = resp.json()
    status = data.get("status")
    if status == "ZERO_RESULTS" or not data.get("results"):
        raise HTTPException(404, f"Address not found: {address!r}")
    if status != "OK":
        raise HTTPException(502, f"Geocoding API returned status {status!r}")

    loc = data["results"][0]["geometry"]["location"]
    formatted = data["results"][0].get("formatted_address", address)
    return float(loc["lat"]), float(loc["lng"]), formatted


def _fetch_solar(lat: float, lng: float, api_key: str) -> dict[str, Any]:
    """Call Solar buildingInsights:findClosest and return the raw JSON dict."""
    try:
        resp = http_requests.get(
            _SOLAR_URL,
            params={
                "location.latitude": lat,
                "location.longitude": lng,
                "requiredQuality": "MEDIUM",
                "key": api_key,
            },
            timeout=_HTTP_TIMEOUT,
        )
    except http_requests.exceptions.Timeout:
        raise HTTPException(502, "Solar API timed out — try again.")
    except http_requests.exceptions.RequestException as exc:
        raise HTTPException(502, f"Solar API error: {exc}")

    if resp.status_code == 404:
        raise HTTPException(
            404,
            "No building found at those coordinates. "
            "Use manual entry if the address is not yet in Google's building database.",
        )
    try:
        resp.raise_for_status()
    except http_requests.exceptions.HTTPError as exc:
        raise HTTPException(502, f"Solar API returned {resp.status_code}: {exc}")

    return resp.json()


def _row_to_dict(row: Measurement) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "provider": row.provider,
        "status": row.status,
        "total_sq": row.total_sq,
        "pitch_primary": row.pitch_primary,
        "segments_json": row.segments_json,
        "confidence": row.confidence,
        "address": row.address,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "imagery_date": row.imagery_date,
        "imagery_quality": row.imagery_quality,
        "source_building": row.source_building,
        "provenance_note": row.provenance_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/measure")
def measure(
    body: MeasureRequest,
    claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Geocode an address (or accept lat/lng directly), fetch Google Solar building
    insights, normalise to roofing squares, persist a Measurement row, and return
    the result with a staleness warning when warranted.

    Returns 503 if SQUARES_API_KEY is not set.
    Returns 404 if the address cannot be geocoded or Solar has no building there.
    Returns 502 on upstream API errors.
    """
    api_key = _api_key()
    email = claims.get("email") or "unknown"

    # Resolve lat/lng
    resolved_address = body.address
    if body.address and (body.latitude is None or body.longitude is None):
        lat, lng, resolved_address = _geocode(body.address, api_key)
    elif body.latitude is not None and body.longitude is not None:
        lat, lng = body.latitude, body.longitude
    else:
        raise HTTPException(422, "Provide either 'address' or both 'latitude' and 'longitude'.")

    # Fetch Solar data
    raw = _fetch_solar(lat, lng, api_key)

    # Parse + normalise
    parsed = parse_building_insights(raw)
    agg = segments_to_squares(parsed["roof_segments"])
    warn = staleness_warning(parsed["imagery_date"], parsed["imagery_quality"], date.today())

    # Persist
    row = Measurement(
        tenant_id=db.info["tenant_id"],
        provider="google_solar",
        status="complete",
        total_sq=agg["total_squares"],
        pitch_primary=agg["predominant_pitch"],
        segments_json=agg["per_segment"],
        confidence=None,
        address=resolved_address,
        latitude=lat,
        longitude=lng,
        imagery_date=parsed["imagery_date"],
        imagery_quality=parsed["imagery_quality"],
        source_building=parsed["source_building"],
        provenance_note=f"Google Solar API — {resolved_address or f'{lat},{lng}'}",
        created_by=email,
    )
    db.add(row)
    db.flush()
    db.refresh(row)

    return {
        **_row_to_dict(row),
        "measurement_id": row.id,
        "staleness_warning": warn,
        "per_segment": agg["per_segment"],
        "predominant_pitch": agg["predominant_pitch"],
    }


@router.get("/measurements")
def list_measurements(
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    """Return the 25 most recent measurements for the caller's tenant (RLS scopes it)."""
    rows = (
        db.query(Measurement)
        .filter(Measurement.provider == "google_solar")
        .order_by(Measurement.created_at.desc())
        .limit(25)
        .all()
    )
    return [_row_to_dict(r) for r in rows]
