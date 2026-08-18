"""Admin-only metrics routes.

GET /admin/metrics/active-users?days=30
    Firebase Auth user list with active-in-window count.
    Requires: admin role (knowify_admin action — admin-only via '*' wildcard).
    Degrades gracefully when Firebase Admin SDK is unavailable.

GET /admin/metrics/gcp-spend?days=30
    GCP billing export via BigQuery (requires BILLING_BQ_TABLE env var).
    Returns total, by_service, and a daily {date, cost} series for the window.
    Requires: admin role (knowify_admin action — admin-only via '*' wildcard).
    Degrades gracefully when BILLING_BQ_TABLE is unset, the export is empty, or BQ fails.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Query

from api.auth import require_role
from core.gcp_metrics import aggregate_bq_rows, filter_active_users

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/metrics", tags=["admin-metrics"])

# Admin-only action: admin has "*" which satisfies any action string.
# "knowify_admin" is the strictest existing admin-only action pattern in this codebase.
_ADMIN_ACTION = "knowify_admin"


# ---------------------------------------------------------------------------
# GET /admin/metrics/active-users
# ---------------------------------------------------------------------------

@router.get("/active-users")
def get_active_users(
    days: int = Query(default=30, ge=1, le=365),
    _claims=Depends(require_role(_ADMIN_ACTION)),
):
    """List Firebase Auth users active within *days*. Admin-only."""
    try:
        users = _list_firebase_users()
    except Exception as exc:  # noqa: BLE001
        log.warning("Firebase Admin unavailable: %s", exc)
        return {
            "error": f"Firebase Admin unavailable: {exc}",
            "total_users": 0,
            "active_users": 0,
            "window_days": days,
            "recent": [],
        }

    active, recent = filter_active_users(users, days)
    recent_out = [
        {
            "email": u.get("email"),
            "last_sign_in": u["last_sign_in"].isoformat() if u.get("last_sign_in") else None,
            "disabled": u.get("disabled", False),
        }
        for u in recent
    ]
    return {
        "total_users": len(users),
        "active_users": len(active),
        "window_days": days,
        "recent": recent_out,
    }


def _list_firebase_users() -> list[dict]:
    """Paginate Firebase Auth list_users() → list of user dicts.

    Reuses the module-level _app singleton from adapters.firebase so we never
    double-initialize Firebase Admin SDK.
    """
    from adapters.firebase import _ensure  # reuse singleton init
    _ensure()
    from firebase_admin import auth

    users = []
    page = auth.list_users()
    while page:
        for u in page.users:
            last_sign_in = None
            if u.user_metadata and u.user_metadata.last_sign_in_timestamp:
                from datetime import timezone
                last_sign_in = __import__("datetime").datetime.fromtimestamp(
                    u.user_metadata.last_sign_in_timestamp / 1000,
                    tz=timezone.utc,
                )
            users.append({
                "email": u.email,
                "last_sign_in": last_sign_in,
                "disabled": u.disabled,
            })
        page = page.get_next_page()
    return users


# ---------------------------------------------------------------------------
# GET /admin/metrics/gcp-spend
# ---------------------------------------------------------------------------

_UNCONFIGURED = {
    "configured": False,
    "note": "Enable BigQuery billing export and set BILLING_BQ_TABLE (format: project.dataset.table)",
}


@router.get("/gcp-spend")
def get_gcp_spend(
    days: int = Query(default=30, ge=1, le=365),
    _claims=Depends(require_role(_ADMIN_ACTION)),
):
    """GCP spend from BigQuery billing export. Admin-only. Degrades when unconfigured."""
    table = os.getenv("BILLING_BQ_TABLE", "").strip()
    if not table:
        return _UNCONFIGURED

    try:
        rows = _query_billing(table, days)
        daily_rows = _query_billing_daily(table, days)
        span = _query_export_span(table)
    except Exception as exc:  # noqa: BLE001
        log.warning("BQ billing query failed: %s", exc)
        return {"configured": True, "error": str(exc), "window_days": days}

    note = None
    if not rows and not daily_rows and span and span.get("n"):
        first, last = span["first"], span["last"]
        try:
            rows = _query_billing_range(table, first, last)
            daily_rows = _query_billing_daily_range(table, first, last)
            note = (
                f"Showing latest export ({first} – {last}). "
                "Google cannot force a billing dump; current days are not in BigQuery yet."
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BQ billing fallback query failed: %s", exc)
            return {"configured": True, "error": str(exc), "window_days": days}

    agg = aggregate_bq_rows(rows, daily_rows)
    out = {
        "configured": True,
        "window_days": days,
        **agg,
    }
    if span:
        out["export_first"] = span.get("first")
        out["export_last"] = span.get("last")
    if note:
        out["note"] = note
    return out


def _run_billing_query(sql: str, days: int) -> list[dict]:
    """Execute a parameterized billing-export SQL and return row dicts."""
    from google.cloud import bigquery  # deferred: optional dep

    client = bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)]
    )
    result = client.query(sql, job_config=job_config).result()
    return [dict(row) for row in result]


def _query_billing(table: str, days: int) -> list[dict]:
    """Run a parameterized BQ query against the billing export table.

    *table* format: project.dataset.table (backtick-quoted in SQL).
    LIMIT 500 is a safety bound — billing exports rarely exceed a few hundred
    service rows per month even for large GCP projects.
    # ponytail: LIMIT 500 is generous; narrow to 200 if query costs become a concern.
    """
    query = f"""
        SELECT
            service.description AS service_description,
            SUM(cost) AS cost,
            currency
        FROM `{table}`
        WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        GROUP BY service_description, currency
        ORDER BY cost DESC
        LIMIT 500
    """
    return _run_billing_query(query, days)


def _query_billing_daily(table: str, days: int) -> list[dict]:
    """Daily SUM(cost) for the spend chart. Empty export → []."""
    query = f"""
        SELECT
            DATE(usage_start_time) AS usage_date,
            SUM(cost) AS cost,
            currency
        FROM `{table}`
        WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        GROUP BY usage_date, currency
        ORDER BY usage_date
        LIMIT 400
    """
    return _run_billing_query(query, days)


def _query_export_span(table: str) -> dict:
    """MIN/MAX usage dates in the export table. Empty table → {n: 0}."""
    from google.cloud import bigquery  # deferred: optional dep

    sql = f"""
        SELECT
            MIN(DATE(usage_start_time)) AS first_day,
            MAX(DATE(usage_start_time)) AS last_day,
            COUNT(*) AS n
        FROM `{table}`
    """
    client = bigquery.Client()
    row = list(client.query(sql).result())[0]
    first = row["first_day"]
    last = row["last_day"]
    return {
        "first": first.isoformat() if first is not None else None,
        "last": last.isoformat() if last is not None else None,
        "n": int(row["n"] or 0),
    }


def _query_billing_range(table: str, first: str, last: str) -> list[dict]:
    sql = f"""
        SELECT
            service.description AS service_description,
            SUM(cost) AS cost,
            currency
        FROM `{table}`
        WHERE DATE(usage_start_time) BETWEEN @first AND @last
        GROUP BY service_description, currency
        ORDER BY cost DESC
        LIMIT 500
    """
    return _run_billing_range_query(sql, first, last)


def _query_billing_daily_range(table: str, first: str, last: str) -> list[dict]:
    sql = f"""
        SELECT
            DATE(usage_start_time) AS usage_date,
            SUM(cost) AS cost,
            currency
        FROM `{table}`
        WHERE DATE(usage_start_time) BETWEEN @first AND @last
        GROUP BY usage_date, currency
        ORDER BY usage_date
        LIMIT 400
    """
    return _run_billing_range_query(sql, first, last)


def _run_billing_range_query(sql: str, first: str, last: str) -> list[dict]:
    from google.cloud import bigquery  # deferred: optional dep

    client = bigquery.Client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("first", "DATE", first),
            bigquery.ScalarQueryParameter("last", "DATE", last),
        ]
    )
    return [dict(row) for row in client.query(sql, job_config=job_config).result()]
