"""Behavioral tests for the scheduling CRUD API.

Uses an isolated temp SQLite DB (via tests/conftest.py) and a fake token verifier
so no live Firebase or real DB is needed.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.scheduling import router
from app.models import Base, engine, init_db


def _make_client(role: str) -> TestClient:
    set_verifier(lambda token: {"uid": "u", "email": "e@x.com", "role": role})
    app = FastAPI()
    app.include_router(router)
    init_db()
    return TestClient(app)


ADMIN_HDR = {"Authorization": "Bearer tok"}
SALES_HDR = {"Authorization": "Bearer tok"}

ITEM_BODY = {
    "kind": "reel",
    "ref_id": "vid-001",
    "publish_at": "2026-08-01T10:00:00",
    "target": "instagram",
}


# ---------------------------------------------------------------------------
# Admin happy path: create -> list -> update -> delete
# ---------------------------------------------------------------------------

def test_admin_create_returns_201():
    client = _make_client("admin")
    r = client.post("/scheduling", json=ITEM_BODY, headers=ADMIN_HDR)
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "reel"
    assert data["ref_id"] == "vid-001"
    assert data["status"] == "scheduled"
    assert data["target"] == "instagram"
    assert "id" in data


def test_admin_list_returns_items():
    client = _make_client("admin")
    # create one first
    create_r = client.post("/scheduling", json=ITEM_BODY, headers=ADMIN_HDR)
    assert create_r.status_code == 201
    created_id = create_r.json()["id"]

    r = client.get("/scheduling", headers=ADMIN_HDR)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    # Find the item we just created (shared DB may have other rows from parallel tests)
    matching = [i for i in items if i["id"] == created_id]
    assert len(matching) == 1
    assert matching[0]["kind"] == "reel"


def test_admin_list_filter_by_status():
    client = _make_client("admin")
    client.post("/scheduling", json=ITEM_BODY, headers=ADMIN_HDR)

    r = client.get("/scheduling?status=scheduled", headers=ADMIN_HDR)
    assert r.status_code == 200
    for item in r.json():
        assert item["status"] == "scheduled"

    r2 = client.get("/scheduling?status=published", headers=ADMIN_HDR)
    assert r2.status_code == 200
    assert r2.json() == []


def test_admin_update_item():
    client = _make_client("admin")
    created = client.post("/scheduling", json=ITEM_BODY, headers=ADMIN_HDR).json()
    item_id = created["id"]

    r = client.put(
        f"/scheduling/{item_id}",
        json={"status": "published", "target": "tiktok"},
        headers=ADMIN_HDR,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "published"
    assert data["target"] == "tiktok"
    assert data["id"] == item_id


def test_admin_delete_item():
    client = _make_client("admin")
    created = client.post("/scheduling", json=ITEM_BODY, headers=ADMIN_HDR).json()
    item_id = created["id"]

    r = client.delete(f"/scheduling/{item_id}", headers=ADMIN_HDR)
    assert r.status_code == 204

    # confirm gone
    r2 = client.get("/scheduling", headers=ADMIN_HDR)
    ids = [i["id"] for i in r2.json()]
    assert item_id not in ids


# ---------------------------------------------------------------------------
# 404 on missing id
# ---------------------------------------------------------------------------

def test_update_missing_id_returns_404():
    client = _make_client("admin")
    r = client.put("/scheduling/999999", json={"status": "error"}, headers=ADMIN_HDR)
    assert r.status_code == 404


def test_delete_missing_id_returns_404():
    client = _make_client("admin")
    r = client.delete("/scheduling/999999", headers=ADMIN_HDR)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Sales role gets 403 on all endpoints
# ---------------------------------------------------------------------------

def test_sales_create_403():
    client = _make_client("sales")
    r = client.post("/scheduling", json=ITEM_BODY, headers=SALES_HDR)
    assert r.status_code == 403


def test_sales_list_403():
    client = _make_client("sales")
    r = client.get("/scheduling", headers=SALES_HDR)
    assert r.status_code == 403


def test_sales_update_403():
    client = _make_client("sales")
    r = client.put("/scheduling/1", json={"status": "published"}, headers=SALES_HDR)
    assert r.status_code == 403


def test_sales_delete_403():
    client = _make_client("sales")
    r = client.delete("/scheduling/1", headers=SALES_HDR)
    assert r.status_code == 403
