"""Behavioral test for GET /config/production-readiness.

Admin-gated (manage_config). Facts gathering (env/DB/Secret Manager/DNS) is
monkeypatched — the gate *logic* itself is covered exhaustively in
tests/core/test_production_gates.py; this test only proves the route wires
gathered facts into evaluate_gates()/summary() and returns them correctly.
"""
import pytest
from fastapi.testclient import TestClient

import api.routes.config as config_mod
from api import app as appmod
from api.auth import set_verifier
from api.routes.config import router as config_router
from app.models import init_db

if not any(getattr(r, "path", None) == "/config/production-readiness" for r in appmod.app.routes):
    appmod.app.include_router(config_router)


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@test.com", "role": "admin"})
    return TestClient(appmod.app)


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@test.com", "role": "sales"})
    return TestClient(appmod.app)


_ALL_OK_FACTS = {
    "email_send_mode": "live",
    "wp_user_set": True,
    "wp_app_pwd_set": True,
    "wp_is_staging": False,
    "rls_enforceable": True,
    "dmarc_policy": "reject",
    "missing_secrets": [],
    "integration_statuses": [],
    "capture_configured": True,
    "search_indexing_enabled": True,
    "indexnow_key_set": True,
    "google_indexing_creds_set": True,
}


def test_sales_role_forbidden(sales_client):
    r = sales_client.get("/config/production-readiness", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_all_ok_facts_yield_ready_summary(admin_client, monkeypatch):
    monkeypatch.setattr(config_mod, "_gather_production_readiness_facts", lambda: _ALL_OK_FACTS)
    r = admin_client.get("/config/production-readiness", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["gates"]) == 8
    assert all(g["state"] == "ok" for g in body["gates"])
    assert body["summary"] == {"ok": 8, "warn": 0, "blocker": 0, "total": 8, "ready": True}


def test_blocker_facts_surface_in_response(admin_client, monkeypatch):
    facts = {
        **_ALL_OK_FACTS,
        "rls_enforceable": False,
        "missing_secrets": ["db-password"],
        "email_send_mode": "test",
    }
    monkeypatch.setattr(config_mod, "_gather_production_readiness_facts", lambda: facts)
    r = admin_client.get("/config/production-readiness", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["blocker"] == 2
    assert body["summary"]["warn"] == 1
    assert body["summary"]["ready"] is False

    by_id = {g["id"]: g for g in body["gates"]}
    assert by_id["rls_security"]["state"] == "blocker"
    assert "migration 0018" in by_id["rls_security"]["remediation"]
    assert by_id["secrets_present"]["state"] == "blocker"
    assert "db-password" in by_id["secrets_present"]["detail"]
    assert by_id["email_mode"]["state"] == "warn"


def test_gather_facts_degrades_without_gcp_or_integration_table(admin_client, monkeypatch):
    """The real _gather_production_readiness_facts must not crash when Secret Manager
    is unavailable (dev/local, no ADC) and/or the integration_status table/model is
    absent — both degrade to a non-blocking default rather than 500."""
    monkeypatch.setattr(config_mod, "_secret_manager_client", lambda: (_ for _ in ()).throw(ImportError("no gcp libs")))
    r = admin_client.get("/config/production-readiness", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    by_id = {g["id"]: g for g in body["gates"]}
    assert by_id["integrations"]["state"] == "ok"  # no known integrations -> not a blocker
