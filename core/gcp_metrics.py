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

def _as_iso_date(value: Any) -> str | None:
    """Normalize a BQ DATE / datetime / ISO string to YYYY-MM-DD, or None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())[:10]
    text = str(value).strip()
    return text[:10] if text else None


def _daily_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum cost by usage_date. Rows without a date are skipped."""
    by_day: dict[str, float] = {}
    for row in rows:
        day = _as_iso_date(row.get("usage_date"))
        if day is None:
            continue
        by_day[day] = by_day.get(day, 0.0) + float(row.get("cost") or 0.0)
    return [
        {"date": day, "cost": round(cost, 4)}
        for day, cost in sorted(by_day.items())
    ]


def aggregate_bq_rows(
    rows: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate BQ billing-export rows into the spend response shape.

    Expected row keys: service_description (str), cost (float), currency (str).
    Optional daily_rows keys: usage_date (date|str), cost (float).
    When daily_rows is None, usage_date on *rows* (if present) is used instead.
    Returns { total, currency, by_service, daily }.
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

    source = rows if daily_rows is None else daily_rows
    return {
        "total": round(total, 4),
        "currency": currency,
        "by_service": [
            {"service": svc, "cost": round(cost, 4)}
            for svc, cost in sorted(by_service.items(), key=lambda x: x[1], reverse=True)
        ],
        "daily": _daily_series(source),
    }
