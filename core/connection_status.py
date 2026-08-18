"""Flip integration_status to healthy after a verified credential write.

The Data sources badge reads this row. Writing a token to Secret Manager
without updating the row leaves "Needs login" up until the next health
probe — and YouTube's probe still reads the mounted env, so a remount
would be required. Callers that just proved the credential work mark
healthy here so the UI clears immediately.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def mark_healthy(integration: str, tenant_id: int | None = None) -> None:
    try:
        _write(integration, tenant_id)
    except Exception:  # noqa: BLE001 — token persist must not fail because status I/O did
        log.warning("could not mark %s healthy", integration, exc_info=True)


def _write(integration: str, tenant_id: int | None) -> None:
    from app.models import IntegrationStatus, PlatformSessionLocal  # noqa: PLC0415

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    try:
        q = db.query(IntegrationStatus).filter(IntegrationStatus.integration == integration)
        q = q.filter(
            IntegrationStatus.tenant_id.is_(None) if tenant_id is None
            else IntegrationStatus.tenant_id == tenant_id
        )
        row = q.first()
        if row is None:
            row = IntegrationStatus(integration=integration, tenant_id=tenant_id)
            db.add(row)
        row.status = "healthy"
        row.last_ok = now
        row.last_checked = now
        row.last_error = None
        row.consecutive_failures = 0
        db.commit()
    finally:
        db.close()
