from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.auth import require_role, set_verifier


def _client(role):
    set_verifier(lambda token: {"uid": "u", "email": "e@x", "role": role})
    app = FastAPI()

    @app.get("/admin-only", dependencies=[Depends(require_role("manage_users"))])
    def _admin():
        return {"ok": True}

    @app.get("/search", dependencies=[Depends(require_role("search"))])
    def _search():
        return {"ok": True}

    return TestClient(app)


def test_403_for_insufficient_role():
    c = _client("sales")
    assert c.get("/admin-only", headers={"Authorization": "Bearer x"}).status_code == 403


def test_200_for_permitted_action():
    c = _client("sales")
    assert c.get("/search", headers={"Authorization": "Bearer x"}).status_code == 200


def test_401_for_missing_token():
    c = _client("admin")
    assert c.get("/search").status_code == 401


def test_admin_allowed_everywhere():
    c = _client("admin")
    assert c.get("/admin-only", headers={"Authorization": "Bearer x"}).status_code == 200
