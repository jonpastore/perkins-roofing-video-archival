"""Monday digest: audit actions + quotes under the $2,500 profit minimum.

POST /internal/weekly-digest (Cloud Scheduler). EMAIL_SEND_MODE still gates recipients.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from app.models import SessionLocal
from core.weekly_digest import collect_digest, send_digest

log = logging.getLogger(__name__)


def _ensure_stdout_logging() -> None:
    if getattr(log, "_perkins_stdout_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log._perkins_stdout_configured = True


def run(now=None) -> dict:
    _ensure_stdout_logging()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        payload = collect_digest(db, now=now)
        ids = send_digest(payload, tenant_id=1)
        n = len(payload.get("profit_below_minimum") or [])
        log.info("weekly-digest sent below_floor=%s audit=%s", n, payload.get("audit_count"))
        return {"ok": True, "message_ids": ids, **{k: payload[k] for k in (
            "since", "until", "audit_count", "estimates") if k in payload},
                "profit_below_count": n}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
