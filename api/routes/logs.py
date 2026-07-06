"""GCP log viewer route — surfaces Cloud Logging errors to admins.

GET /logs?hours=&severity=&limit=
  → {entries: [...], project: str}

Admin-only: requires view_status permission (granted to admin + web_admin).
Returns 503 if Cloud Logging library or ADC is unavailable.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_role

router = APIRouter(prefix="/logs", tags=["logs"])

_MAX_HOURS = 168   # 7 days
_MAX_LIMIT = 500


@router.get("")
def get_logs(
    hours: int = Query(default=24, ge=1, le=_MAX_HOURS),
    severity: str = Query(default="ERROR"),
    limit: int = Query(default=100, ge=1, le=_MAX_LIMIT),
    _claims=Depends(require_role("view_status")),
):
    """Return recent Cloud Logging entries at >= severity from Cloud Run services/jobs.

    Response:
      {
        "entries": [
          {
            "timestamp": "2026-07-06T04:00:00+00:00",
            "severity": "ERROR",
            "resource": "video-archival-api",
            "message": "...",
            "log_name": "projects/my-project/logs/run.googleapis.com"
          }
        ],
        "project": "my-gcp-project"
      }

    503 if Cloud Logging library is not installed or GCP credentials are absent.
    """
    from adapters.gcp_logging import recent_errors  # noqa: PLC0415 — lazy import for testability

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT") or "unknown"

    try:
        entries = recent_errors(hours=hours, severity=severity, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"entries": entries, "project": project}
