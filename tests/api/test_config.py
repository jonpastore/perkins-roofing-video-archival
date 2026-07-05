"""Tests for GET /config and PUT /config.

Admin-only — sales role must get 403.
Editable key/value rows are stored in platform_config; runtime info is read-only.
"""
import pytest
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.config import router as config_router
from app.models import init_db

# Mount the config router onto the shared app once (idempotent: skip if already present).
if not any(getattr(r, "path", None) == "/config" for r in appmod.app.routes):
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


def test_get_config_admin_ok(admin_client):
    r = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert "settings" in body
    assert "runtime" in body
    # runtime always has model info
    assert "embed_model" in body["runtime"]
    assert "llm_model" in body["runtime"]
    assert "default_admins" in body["runtime"]


def test_get_config_sales_forbidden(sales_client):
    r = sales_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_get_config_unauthenticated():
    client = TestClient(appmod.app)
    r = client.get("/config")
    assert r.status_code == 401


def test_put_config_upsert(admin_client):
    # Create a new key
    r = admin_client.put(
        "/config",
        json={"key": "wp_url", "value": "https://perkins.example.com"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "wp_url"
    assert body["value"] == "https://perkins.example.com"

    # Read it back — should appear in settings dict
    r2 = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r2.status_code == 200
    assert r2.json()["settings"]["wp_url"] == "https://perkins.example.com"


def test_put_config_update_existing(admin_client):
    # Seed
    admin_client.put(
        "/config",
        json={"key": "publish_cadence_days", "value": "7"},
        headers={"Authorization": "Bearer x"},
    )
    # Update
    r = admin_client.put(
        "/config",
        json={"key": "publish_cadence_days", "value": "14"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert r.json()["value"] == "14"

    r2 = admin_client.get("/config", headers={"Authorization": "Bearer x"})
    assert r2.json()["settings"]["publish_cadence_days"] == "14"


def test_put_config_sales_forbidden(sales_client):
    r = sales_client.put(
        "/config",
        json={"key": "x", "value": "y"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403
