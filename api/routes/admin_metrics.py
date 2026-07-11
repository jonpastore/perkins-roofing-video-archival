"""Admin-only metrics routes.

GET /admin/metrics/active-users?days=30
    Firebase Auth user list with active-in-window count.
    Requires: admin role (knowify_admin action — admin-only via '*' wildcard).
    Degrades gracefully when Firebase Admin SDK is unavailable.

GET /admin/metrics/gcp-spend?days=30
    GCP billing export via BigQuery (requires BILLING_BQ_TABLE env var).
    Requires: admin role (knowify_admin action — admin-only via '*' wildcard).
    Degrades gracefully when BILLING_BQ_TABLE is unset or BQ query fails.
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
    except Exception as exc:  # noqa: BLE001
        log.warning("BQ billing query failed: %s", exc)
        return {"configured": True, "error": str(exc), "window_days": days}

    agg = aggregate_bq_rows(rows)
    return {
        "configured": True,
        "window_days": days,
        **agg,
    }


def _query_billing(table: str, days: int) -> list[dict]:
    """Run a parameterized BQ query against the billing export table.

    *table* format: project.dataset.table (backtick-quoted in SQL).
    LIMIT 500 is a safety bound — billing exports rarely exceed a few hundred
    service rows per month even for large GCP projects.
    # ponytail: LIMIT 500 is generous; narrow to 200 if query costs become a concern.
    """
    from google.cloud import bigquery  # deferred: optional dep

    client = bigquery.Client()
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
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)]
    )
    result = client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]
