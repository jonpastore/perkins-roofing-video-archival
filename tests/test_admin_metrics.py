"""Tests for core/gcp_metrics.py helpers and GET /admin/metrics/* routes.

Pure-unit tests: no real Firebase or BigQuery calls. External clients are mocked.
Coverage target: core/gcp_metrics.py >= 97% (adapters/api layers are omitted per .coveragerc).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.admin_metrics import router as admin_metrics_router
from core.gcp_metrics import aggregate_bq_rows, filter_active_users

# Mount router once (idempotent guard).
if not any(
    getattr(r, "path", None) == "/admin/metrics/active-users"
    for r in appmod.app.routes
):
    appmod.app.include_router(admin_metrics_router)

client = TestClient(appmod.app, raise_server_exceptions=True)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _admin_headers():
    set_verifier(lambda _token: {"email": "admin@test.com", "role": "admin", "email_verified": True})
    return {"Authorization": "Bearer faketoken"}


def _sales_headers():
    set_verifier(lambda _token: {"email": "sales@test.com", "role": "sales", "email_verified": True})
    return {"Authorization": "Bearer faketoken"}


# ---------------------------------------------------------------------------
# core/gcp_metrics — filter_active_users
# ---------------------------------------------------------------------------

def _make_user(days_ago: float | None, disabled: bool = False) -> dict:
    ts = None
    if days_ago is not None:
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"email": f"user_{days_ago}@x.com", "last_sign_in": ts, "disabled": disabled}


def test_filter_active_users_basic():
    users = [
        _make_user(1),    # active (within 30d)
        _make_user(15),   # active
        _make_user(31),   # outside window
        _make_user(None), # never signed in — excluded
    ]
    active, recent = filter_active_users(users, window_days=30)
    assert len(active) == 2
    # sorted newest-first
    assert active[0]["email"] == "user_1@x.com"


def test_filter_active_users_empty():
    active, recent = filter_active_users([], window_days=30)
    assert active == []
    assert recent == []


def test_filter_active_users_recent_capped_at_20():
    users = [_make_user(i * 0.1) for i in range(1, 35)]  # 34 active users
    active, recent = filter_active_users(users, window_days=30)
    assert len(active) == 34
    assert len(recent) == 20


def test_filter_active_users_just_inside_boundary():
    """User signed in 1 second inside the window should be included."""
    ts = datetime.now(timezone.utc) - timedelta(days=30) + timedelta(seconds=2)
    users = [{"email": "boundary@x.com", "last_sign_in": ts, "disabled": False}]
    active, _ = filter_active_users(users, window_days=30)
    assert len(active) == 1


def test_filter_active_users_naive_datetime():
    """Naive datetimes (no tzinfo) are treated as UTC."""
    ts = datetime.utcnow() - timedelta(days=5)  # naive
    users = [{"email": "naive@x.com", "last_sign_in": ts, "disabled": False}]
    active, _ = filter_active_users(users, window_days=30)
    assert len(active) == 1


def test_filter_active_users_window_1d():
    users = [_make_user(0.5), _make_user(1.5)]
    active, _ = filter_active_users(users, window_days=1)
    assert len(active) == 1
    assert active[0]["email"] == "user_0.5@x.com"


# ---------------------------------------------------------------------------
# core/gcp_metrics — aggregate_bq_rows
# ---------------------------------------------------------------------------

def test_aggregate_bq_rows_basic():
    rows = [
        {"service_description": "Cloud Run", "cost": 10.50, "currency": "USD"},
        {"service_description": "Cloud SQL", "cost": 5.25, "currency": "USD"},
        {"service_description": "Cloud Run", "cost": 3.00, "currency": "USD"},
    ]
    result = aggregate_bq_rows(rows)
    assert result["total"] == round(18.75, 4)
    assert result["currency"] == "USD"
    assert result["daily"] == []
    svc_map = {s["service"]: s["cost"] for s in result["by_service"]}
    assert svc_map["Cloud Run"] == round(13.50, 4)
    assert svc_map["Cloud SQL"] == round(5.25, 4)
    # sorted descending by cost
    assert result["by_service"][0]["service"] == "Cloud Run"


def test_aggregate_bq_rows_empty():
    result = aggregate_bq_rows([])
    assert result["total"] == 0.0
    assert result["by_service"] == []
    assert result["daily"] == []


def test_aggregate_bq_rows_none_cost():
    rows = [{"service_description": "BigQuery", "cost": None, "currency": "USD"}]
    result = aggregate_bq_rows(rows)
    assert result["total"] == 0.0


def test_aggregate_bq_rows_none_service():
    rows = [{"service_description": None, "cost": 7.0, "currency": "USD"}]
    result = aggregate_bq_rows(rows)
    assert result["by_service"][0]["service"] == "Unknown"


def test_aggregate_bq_rows_daily_series():
    rows = [
        {"service_description": "Cloud Run", "cost": 10.0, "currency": "USD"},
        {"service_description": "Cloud SQL", "cost": 7.5, "currency": "USD"},
    ]
    daily_rows = [
        {"usage_date": "2026-08-02", "cost": 7.5, "currency": "USD"},
        {"usage_date": "2026-08-01", "cost": 4.0, "currency": "USD"},
        {"usage_date": "2026-08-01", "cost": 6.0, "currency": "USD"},
    ]
    result = aggregate_bq_rows(rows, daily_rows)
    assert result["total"] == 17.5
    assert result["daily"] == [
        {"date": "2026-08-01", "cost": 10.0},
        {"date": "2026-08-02", "cost": 7.5},
    ]


def test_aggregate_bq_rows_daily_from_row_dates():
    """When daily_rows is omitted, usage_date on the service rows is used."""
    rows = [
        {"service_description": "Cloud Run", "cost": 4.0, "currency": "USD", "usage_date": "2026-08-01"},
        {"service_description": "Cloud SQL", "cost": 6.0, "currency": "USD", "usage_date": "2026-08-01"},
        {"service_description": "Cloud Run", "cost": 3.0, "currency": "USD", "usage_date": "2026-08-02"},
    ]
    result = aggregate_bq_rows(rows)
    assert result["daily"] == [
        {"date": "2026-08-01", "cost": 10.0},
        {"date": "2026-08-02", "cost": 3.0},
    ]


def test_aggregate_bq_rows_daily_date_object():
    result = aggregate_bq_rows([], [{"usage_date": date(2026, 8, 1), "cost": 1.5}])
    assert result["daily"] == [{"date": "2026-08-01", "cost": 1.5}]


def test_aggregate_bq_rows_daily_empty_list_not_inferred():
    """Explicit empty daily_rows must not fall back to inferring from service rows."""
    rows = [
        {"service_description": "Cloud Run", "cost": 4.0, "currency": "USD", "usage_date": "2026-08-01"},
    ]
    result = aggregate_bq_rows(rows, [])
    assert result["daily"] == []
    assert result["total"] == 4.0


def test_aggregate_bq_rows_skips_blank_dates():
    result = aggregate_bq_rows([], [
        {"usage_date": None, "cost": 1.0},
        {"usage_date": "", "cost": 2.0},
        {"usage_date": "2026-08-03", "cost": 3.0},
    ])
    assert result["daily"] == [{"date": "2026-08-03", "cost": 3.0}]


def test_aggregate_bq_rows_daily_datetime():
    result = aggregate_bq_rows([], [{"usage_date": datetime(2026, 8, 1, 12, 0), "cost": 1.25}])
    assert result["daily"] == [{"date": "2026-08-01", "cost": 1.25}]


# ---------------------------------------------------------------------------
# Route: GET /admin/metrics/active-users
# ---------------------------------------------------------------------------

def _fake_firebase_user(email: str, days_ago: float | None, disabled: bool = False):
    u = MagicMock()
    u.email = email
    u.disabled = disabled
    if days_ago is not None:
        ts_ms = int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp() * 1000)
        u.user_metadata = MagicMock()
        u.user_metadata.last_sign_in_timestamp = ts_ms
    else:
        u.user_metadata = MagicMock()
        u.user_metadata.last_sign_in_timestamp = None
    return u


def _make_page(users, next_page=None):
    page = MagicMock()
    page.users = users
    page.get_next_page.return_value = next_page
    return page


def test_active_users_endpoint_success():
    headers = _admin_headers()
    fake_users = [
        _fake_firebase_user("a@x.com", 5),
        _fake_firebase_user("b@x.com", 45),  # outside 30d
    ]
    page = _make_page(fake_users)

    with patch("api.routes.admin_metrics._list_firebase_users") as mock_list:
        mock_list.return_value = [
            {"email": "a@x.com", "last_sign_in": datetime.now(timezone.utc) - timedelta(days=5), "disabled": False},
            {"email": "b@x.com", "last_sign_in": datetime.now(timezone.utc) - timedelta(days=45), "disabled": False},
        ]
        resp = client.get("/admin/metrics/active-users?days=30", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 2
    assert data["active_users"] == 1
    assert data["window_days"] == 30
    assert len(data["recent"]) == 1
    assert data["recent"][0]["email"] == "a@x.com"


def test_active_users_endpoint_firebase_unavailable():
    headers = _admin_headers()
    with patch("api.routes.admin_metrics._list_firebase_users", side_effect=RuntimeError("SDK not init")):
        resp = client.get("/admin/metrics/active-users", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["total_users"] == 0


def test_active_users_endpoint_forbidden_for_sales():
    headers = _sales_headers()
    with patch("api.routes.admin_metrics._list_firebase_users", return_value=[]):
        resp = client.get("/admin/metrics/active-users", headers=headers)
    assert resp.status_code == 403


def test_active_users_endpoint_no_auth():
    resp = client.get("/admin/metrics/active-users")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Route: GET /admin/metrics/gcp-spend
# ---------------------------------------------------------------------------

def test_gcp_spend_unconfigured():
    headers = _admin_headers()
    env = {k: v for k, v in os.environ.items() if k != "BILLING_BQ_TABLE"}
    with patch.dict(os.environ, env, clear=True):
        resp = client.get("/admin/metrics/gcp-spend", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert "BILLING_BQ_TABLE" in data["note"]


def test_gcp_spend_configured_success():
    headers = _admin_headers()
    fake_rows = [
        {"service_description": "Cloud Run", "cost": 12.34, "currency": "USD"},
        {"service_description": "Cloud SQL", "cost": 5.00, "currency": "USD"},
    ]
    fake_daily = [
        {"usage_date": "2026-08-01", "cost": 10.00, "currency": "USD"},
        {"usage_date": "2026-08-02", "cost": 7.34, "currency": "USD"},
    ]
    with patch.dict(os.environ, {"BILLING_BQ_TABLE": "proj.dataset.table"}):
        with patch("api.routes.admin_metrics._query_billing", return_value=fake_rows):
            with patch("api.routes.admin_metrics._query_billing_daily", return_value=fake_daily):
                resp = client.get("/admin/metrics/gcp-spend?days=30", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["window_days"] == 30
    assert data["total"] == round(17.34, 4)
    assert len(data["by_service"]) == 2
    assert data["by_service"][0]["service"] == "Cloud Run"
    assert data["daily"] == [
        {"date": "2026-08-01", "cost": 10.0},
        {"date": "2026-08-02", "cost": 7.34},
    ]


def test_gcp_spend_empty_export():
    """Configured table with no rows still returns the series shape, not an error."""
    headers = _admin_headers()
    with patch.dict(os.environ, {"BILLING_BQ_TABLE": "proj.dataset.table"}):
        with patch("api.routes.admin_metrics._query_billing", return_value=[]):
            with patch("api.routes.admin_metrics._query_billing_daily", return_value=[]):
                resp = client.get("/admin/metrics/gcp-spend?days=30", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["total"] == 0.0
    assert data["by_service"] == []
    assert data["daily"] == []
    assert "error" not in data


def test_gcp_spend_bq_error_degrades():
    headers = _admin_headers()
    with patch.dict(os.environ, {"BILLING_BQ_TABLE": "proj.dataset.table"}):
        with patch("api.routes.admin_metrics._query_billing", side_effect=Exception("BQ unavail")):
            resp = client.get("/admin/metrics/gcp-spend", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert "error" in data


def test_gcp_spend_forbidden_for_sales():
    headers = _sales_headers()
    resp = client.get("/admin/metrics/gcp-spend", headers=headers)
    assert resp.status_code == 403


def test_gcp_spend_no_auth():
    resp = client.get("/admin/metrics/gcp-spend")
    assert resp.status_code == 401
