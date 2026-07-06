"""Behavioral tests for GET /logs in api/routes/logs.py.

Cloud Logging calls are mocked at the adapter boundary so no GCP creds are needed.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.app import app

AUTH = {"Authorization": "Bearer tok"}

_FAKE_ENTRIES = [
    {
        "timestamp": "2026-07-06T04:00:00+00:00",
        "severity": "ERROR",
        "resource": "video-archival-api",
        "message": "Something went wrong",
        "log_name": "projects/my-proj/logs/run.googleapis.com",
    }
]


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(app)


def _web_admin_client():
    set_verifier(lambda token: {"uid": "u2", "email": "webadmin@x.com", "role": "web_admin"})
    return TestClient(app)


def _sales_client():
    set_verifier(lambda token: {"uid": "u3", "email": "sales@x.com", "role": "sales"})
    return TestClient(app)


# ---------------------------------------------------------------------------
# Route shape + auth
# ---------------------------------------------------------------------------

def test_logs_admin_ok():
    """Admin can fetch logs; response has entries + project keys."""
    with patch("adapters.gcp_logging.recent_errors", return_value=_FAKE_ENTRIES):
        c = _admin_client()
        r = c.get("/logs", headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "entries" in data
    assert "project" in data
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["severity"] == "ERROR"
    assert entry["resource"] == "video-archival-api"
    assert "message" in entry
    assert "timestamp" in entry
    assert "log_name" in entry


def test_logs_web_admin_403():
    """web_admin does NOT have manage_config — logs endpoint must return 403."""
    with patch("adapters.gcp_logging.recent_errors", return_value=_FAKE_ENTRIES):
        c = _web_admin_client()
        r = c.get("/logs", headers=AUTH)
    assert r.status_code == 403, r.text


def test_logs_sales_403():
    """sales role lacks view_status — must receive 403."""
    with patch("adapters.gcp_logging.recent_errors", return_value=_FAKE_ENTRIES):
        c = _sales_client()
        r = c.get("/logs", headers=AUTH)
    assert r.status_code == 403, r.text


def test_logs_401_no_token():
    """No auth header → 401."""
    with patch("adapters.gcp_logging.recent_errors", return_value=_FAKE_ENTRIES):
        c = _admin_client()
        r = c.get("/logs")
    assert r.status_code == 401, r.text


def test_logs_empty_entries():
    """Empty result from adapter returns empty list, not an error."""
    with patch("adapters.gcp_logging.recent_errors", return_value=[]):
        c = _admin_client()
        r = c.get("/logs", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["entries"] == []


def test_logs_503_on_runtime_error():
    """RuntimeError from adapter (lib missing / no creds) becomes 503 with generic message."""
    with patch("adapters.gcp_logging.recent_errors", side_effect=RuntimeError("no creds")):
        c = _admin_client()
        r = c.get("/logs", headers=AUTH)
    assert r.status_code == 503, r.text
    # Must NOT leak the raw exception string to the client
    assert r.json()["detail"] == "log query failed"


def test_logs_query_params_forwarded():
    """hours/severity/limit query params are forwarded to the adapter."""
    captured = {}

    def fake_recent_errors(hours, severity, limit):
        captured["hours"] = hours
        captured["severity"] = severity
        captured["limit"] = limit
        return []

    with patch("adapters.gcp_logging.recent_errors", side_effect=fake_recent_errors):
        c = _admin_client()
        r = c.get("/logs?hours=6&severity=WARNING&limit=50", headers=AUTH)
    assert r.status_code == 200, r.text
    assert captured["hours"] == 6
    assert captured["severity"] == "WARNING"
    assert captured["limit"] == 50


def test_logs_hours_cap():
    """hours > 168 is rejected with 422."""
    with patch("adapters.gcp_logging.recent_errors", return_value=[]):
        c = _admin_client()
        r = c.get("/logs?hours=9999", headers=AUTH)
    assert r.status_code == 422, r.text


def test_logs_limit_cap():
    """limit > 500 is rejected with 422."""
    with patch("adapters.gcp_logging.recent_errors", return_value=[]):
        c = _admin_client()
        r = c.get("/logs?limit=9999", headers=AUTH)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Adapter unit tests (mocked at google.cloud boundary)
# ---------------------------------------------------------------------------

def test_adapter_missing_library():
    """recent_errors raises RuntimeError when google-cloud-logging is absent."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "google.cloud.logging_v2":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        # Re-import inside the patch so the ImportError fires
        import importlib
        import adapters.gcp_logging as mod
        importlib.reload(mod)
        try:
            with pytest.raises(RuntimeError, match="not installed"):
                mod.recent_errors()
        finally:
            importlib.reload(mod)  # restore


def test_adapter_no_gcp_project(monkeypatch):
    """recent_errors raises RuntimeError when no project can be resolved."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)

    def fake_auth_default(*a, **kw):
        return (None, None)

    with patch("google.auth.default", side_effect=Exception("no creds")):
        from adapters.gcp_logging import _gcp_project
        with pytest.raises(RuntimeError, match="Cannot determine GCP project"):
            _gcp_project()


# ---------------------------------------------------------------------------
# Severity pattern validation
# ---------------------------------------------------------------------------

def test_logs_severity_invalid_422():
    """Non-allowlist severity value must be rejected with 422."""
    with patch("adapters.gcp_logging.recent_errors", return_value=[]):
        c = _admin_client()
        r = c.get("/logs?severity=GARBAGE", headers=AUTH)
    assert r.status_code == 422, r.text


def test_logs_severity_injection_422():
    """Attempted injection via severity param must be rejected with 422."""
    with patch("adapters.gcp_logging.recent_errors", return_value=[]):
        c = _admin_client()
        r = c.get("/logs?severity=ERROR%20OR%201%3D1", headers=AUTH)
    assert r.status_code == 422, r.text


def test_logs_severity_valid_values():
    """All valid severity values must be accepted."""
    valid = ["DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
    for sev in valid:
        with patch("adapters.gcp_logging.recent_errors", return_value=[]):
            c = _admin_client()
            r = c.get(f"/logs?severity={sev}", headers=AUTH)
        assert r.status_code == 200, f"Expected 200 for severity={sev}, got {r.status_code}"
