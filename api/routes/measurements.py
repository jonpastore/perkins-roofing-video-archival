"""Measurement stub API — F2 manual-entry path. Full provider model in F2b.

Endpoints:
  POST  /measurements          create a manual measurement
  GET   /measurements/{id}     get a measurement by id

Authz: estimating_view for GET, estimating_manage for POST.
"""
import logging
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Measurement

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/measurements", tags=["measurements"])

#: A Roofr report is a handful of pages. The cap is a trust boundary, not a product rule.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _extract_pdf_text(data: bytes) -> str:
    """Text out of an uploaded PDF via pypdf (no OCR).

    Fails loudly on encrypted or image-only PDFs: a scanned report extracts to nothing, and
    silently returning an empty parse would look like a report with no measurements in it.
    """
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - installed in app/requirements
        raise HTTPException(500, "PDF extraction dependency pypdf is not installed") from exc
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise HTTPException(422, "PDF is encrypted; upload an unlocked copy")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Could not read the PDF: {type(exc).__name__}") from exc
    text = "\n".join(pages).strip()
    if not text:
        raise HTTPException(422, "No text in the PDF — it may be a scan or image-only export")
    return text


class MeasurementCreateRequest(BaseModel):
    property_id: Optional[int] = None
    total_sq: Optional[float] = None
    # RoofR reports total = pitched + flat. Capturing only the total made total_sq ambiguous
    # (Tim's sheet = sloped only; a RoofR transcription = pitched+flat). See migration 0046.
    pitched_sq: Optional[float] = None
    flat_sq: Optional[float] = None
    hips_lf: Optional[float] = None
    ridges_lf: Optional[float] = None
    valleys_lf: Optional[float] = None
    rakes_lf: Optional[float] = None
    eaves_lf: Optional[float] = None
    wall_flashings_lf: Optional[float] = None
    pitch_primary: Optional[float] = None
    provenance_note: Optional[str] = None


def _row_to_dict(row: Measurement) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "property_id": row.property_id,
        "provider": row.provider,
        "status": row.status,
        "total_sq": row.total_sq,
        "pitched_sq": row.pitched_sq,
        "flat_sq": row.flat_sq,
        "hips_lf": row.hips_lf,
        "ridges_lf": row.ridges_lf,
        "valleys_lf": row.valleys_lf,
        "rakes_lf": row.rakes_lf,
        "eaves_lf": row.eaves_lf,
        "wall_flashings_lf": row.wall_flashings_lf,
        "pitch_primary": row.pitch_primary,
        "confidence": row.confidence,
        "provenance_note": row.provenance_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    }


@router.post("")
def create_measurement(
    body: MeasurementCreateRequest,
    claims=Depends(require_role("estimating_manage")),
    db: Session = Depends(get_db_session),
):
    """Create a manual measurement entry. Sets provider='manual', confidence=null,
    and auto-builds provenance_note if not supplied. tenant_id comes from the
    RLS-stamped session (the caller's verified tenant), never a hardcoded literal."""
    email = claims.get("email") or "unknown"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    provenance = body.provenance_note or f"Manual entry by {email} on {now_str}"

    row = Measurement(
        tenant_id=db.info["tenant_id"],
        property_id=body.property_id,
        provider="manual",
        status="complete",
        total_sq=body.total_sq,
        pitched_sq=body.pitched_sq,
        flat_sq=body.flat_sq,
        hips_lf=body.hips_lf,
        ridges_lf=body.ridges_lf,
        valleys_lf=body.valleys_lf,
        rakes_lf=body.rakes_lf,
        eaves_lf=body.eaves_lf,
        wall_flashings_lf=body.wall_flashings_lf,
        pitch_primary=body.pitch_primary,
        confidence=None,
        provenance_note=provenance,
        created_by=email,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return _row_to_dict(row)


@router.post("/parse-roofr")
async def parse_roofr_report(
    file: UploadFile = File(...),
    claims=Depends(require_role("estimating_manage")),
):
    """Read a Roofr measurement PDF and return the fields it contains. Saves NOTHING.

    The estimator uploads the report, the form prefills, and they press Save — so a bad parse is
    visible and correctable before it becomes a measurement anything prices against. Auto-saving
    would put unreviewed numbers straight under a quote.

    Parsing lives in core.roofr, shared with scripts/fit_days_from_roofr.py, so there is one
    definition of what a Roofr report says rather than an estimating copy that drifts.
    """
    from core.roofr import is_roofr_report, parse_report  # noqa: PLC0415

    data = await file.read()
    if not data:
        raise HTTPException(422, "empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file is larger than {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB")

    text = _extract_pdf_text(data)
    if not is_roofr_report(text):
        # A non-Roofr PDF parses to a dict of nulls, which would prefill an empty form and read
        # as "the report had no measurements in it".
        raise HTTPException(422, "This does not look like a Roofr measurement report.")

    parsed = parse_report(text)
    if parsed.get("total_sq") is None:
        raise HTTPException(422, "No total roof area found in the report — check the PDF.")

    logger.info("Roofr report parsed for %s: %s sq", claims.get("email", "unknown"),
                parsed.get("total_sq"))
    return {
        "filename": file.filename,
        "measurement": {k: parsed.get(k) for k in (
            "total_sq", "pitched_sq", "flat_sq", "hips_lf", "ridges_lf", "valleys_lf",
            "rakes_lf", "eaves_lf", "wall_flashings_lf", "pitch_primary",
        )},
        # Not Measurement columns; shown to the estimator as complexity context.
        "extras": {k: parsed.get(k) for k in ("facets", "two_story_sq", "area_sqft")},
        "provenance_note": f"Parsed from Roofr report {file.filename!r}",
    }


@router.get("")
def list_measurements(
    property_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    q = db.query(Measurement).filter(Measurement.tenant_id == db.info["tenant_id"])
    if property_id is not None:
        q = q.filter(Measurement.property_id == property_id)
    rows = q.order_by(Measurement.created_at.desc()).limit(limit).all()
    return [_row_to_dict(r) for r in rows]


@router.get("/{measurement_id}")
def get_measurement(
    measurement_id: int,
    _claims=Depends(require_role("estimating_view")),
    db: Session = Depends(get_db_session),
):
    row = db.get(Measurement, measurement_id)
    if row is None:
        raise HTTPException(404, f"Measurement {measurement_id} not found")
    return _row_to_dict(row)
