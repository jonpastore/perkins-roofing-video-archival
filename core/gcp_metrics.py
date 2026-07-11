"""Pure helpers for admin metrics: active-user windowing and BQ billing aggregation.

Both helpers are importable without live GCP credentials — callers pass in pre-fetched
data so the logic is unit-testable. The I/O (Firebase list_users, BQ query) lives in
api/routes/admin_metrics.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any  # noqa: TCH003

# ---------------------------------------------------------------------------
# Active-user helpers
# ---------------------------------------------------------------------------

def filter_active_users(
    users: list[dict[str, Any]],
    window_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split *users* into (active_in_window, recent_20).

    Each user dict must have: email, last_sign_in (datetime | None), disabled (bool).
    Returns:
      - active: users whose last_sign_in is within *window_days* of now (UTC).
      - recent: up to 20 of *active*, sorted newest-first.
    """
    now = datetime.now(timezone.utc)
    cutoff_seconds = window_days * 86_400
    active = []
    for u in users:
        ts = u.get("last_sign_in")
        if ts is None:
            continue
        # Accept both aware and naive datetimes (Firebase SDK returns aware).
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).total_seconds()
        if age <= cutoff_seconds:
            active.append(u)
    active.sort(key=lambda u: u["last_sign_in"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    recent = active[:20]
    return active, recent


# ---------------------------------------------------------------------------
# GCP spend helpers
# ---------------------------------------------------------------------------

def aggregate_bq_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate BQ billing-export rows into the spend response shape.

    Expected row keys: service_description (str), cost (float), currency (str).
    Returns { total, currency, by_service }.
    """
    total = 0.0
    currency = "USD"
    by_service: dict[str, float] = {}
    for row in rows:
        svc = str(row.get("service_description") or "Unknown")
        cost = float(row.get("cost") or 0.0)
        cur = str(row.get("currency") or "USD")
        by_service[svc] = by_service.get(svc, 0.0) + cost
        total += cost
        currency = cur  # all rows share the same currency in a billing export

    return {
        "total": round(total, 4),
        "currency": currency,
        "by_service": [
            {"service": svc, "cost": round(cost, 4)}
            for svc, cost in sorted(by_service.items(), key=lambda x: x[1], reverse=True)
        ],
    }
