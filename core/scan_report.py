"""Persist scan-job outcomes. Cloud Logging is not a digest source."""
from __future__ import annotations

from typing import Any


def record(db, *, scan_type: str, payload: dict[str, Any], tenant_id: int | None = None):
    """Write one scan_reports row. Caller owns commit."""
    from app.models import ScanReport  # noqa: PLC0415

    tid = tenant_id if tenant_id is not None else int(db.info.get("tenant_id") or 1)
    row = ScanReport(tenant_id=tid, scan_type=scan_type, payload=dict(payload or {}))
    db.add(row)
    db.flush()
    return row
