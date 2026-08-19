"""GET/PUT /me/nav — per-user sidebar pins live on user_settings, not the browser."""
import pytest
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.users import me_router
from app.models import SessionLocal, UserSetting, init_db

if not any(getattr(r, "path", None) == "/me" for r in appmod.app.routes):
    appmod.app.include_router(me_router)

AUTH = {"Authorization": "Bearer x"}


def _nav(**kw):
    body = {"pins": [], "sections": [], "collapsed": False}
    body.update(kw)
    return body


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    with SessionLocal() as db:
        db.query(UserSetting).delete()
        db.commit()


@pytest.fixture()
def alice():
    set_verifier(lambda t: {"uid": "u2", "email": "alice@test.com", "role": "sales"})
    return TestClient(appmod.app)


@pytest.fixture()
def bob():
    set_verifier(lambda t: {"uid": "u3", "email": "bob@test.com", "role": "admin"})
    return TestClient(appmod.app)


def test_get_nav_empty(alice):
    r = alice.get("/me/nav", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"pins": [], "sections": [], "collapsed": False, "saved": False}


def test_put_nav_persists(alice):
    body = _nav(pins=["search-ask", "clip-studio"], sections=["Knowledge Base"], collapsed=True)
    r = alice.put("/me/nav", json=body, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {**body, "saved": True}
    r = alice.get("/me/nav", headers=AUTH)
    assert r.json() == {**body, "saved": True}
    with SessionLocal() as db:
        row = db.get(UserSetting, "alice@test.com")
    assert row is not None
    assert row.nav["pins"] == ["search-ask", "clip-studio"]


def test_put_nav_sanitizes_junk(alice):
    r = alice.put(
        "/me/nav",
        json=_nav(pins=["search-ask", "NOPE", "search-ask"], sections=["Marketing"], collapsed="1"),
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json() == {"pins": ["search-ask"], "sections": ["Marketing"], "collapsed": True, "saved": True}


def test_get_nav_on_signature_only_row(alice):
    alice.put("/me/signature", json={"signature": "<p>x</p>"}, headers=AUTH)
    r = alice.get("/me/nav", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"pins": [], "sections": [], "collapsed": False, "saved": False}


def test_put_empty_nav_is_saved(alice):
    r = alice.put("/me/nav", json=_nav(), headers=AUTH)
    assert r.status_code == 200
    assert r.json()["saved"] is True
    assert alice.get("/me/nav", headers=AUTH).json()["saved"] is True


def test_put_nav_requires_all_fields(alice):
    r = alice.put("/me/nav", json={"pins": ["faq"]}, headers=AUTH)
    assert r.status_code == 422


def test_put_nav_does_not_wipe_signature(alice):
    alice.put("/me/signature", json={"signature": "<p>Alice</p>"}, headers=AUTH)
    alice.put("/me/nav", json=_nav(pins=["faq"]), headers=AUTH)
    sig = alice.get("/me/signature", headers=AUTH).json()
    nav = alice.get("/me/nav", headers=AUTH).json()
    assert sig["signature"] == "<p>Alice</p>"
    assert nav["pins"] == ["faq"]
    assert nav["saved"] is True


def test_put_signature_does_not_wipe_nav(alice):
    alice.put("/me/nav", json=_nav(pins=["archive"], collapsed=True), headers=AUTH)
    alice.put("/me/signature", json={"signature": "<p>later</p>"}, headers=AUTH)
    nav = alice.get("/me/nav", headers=AUTH).json()
    assert nav["pins"] == ["archive"]
    assert nav["collapsed"] is True
    assert nav["saved"] is True


def test_nav_is_per_user():
    set_verifier(lambda t: {"uid": "u2", "email": "alice@test.com", "role": "sales"})
    alice = TestClient(appmod.app)
    alice.put("/me/nav", json=_nav(pins=["search-ask"]), headers=AUTH)
    set_verifier(lambda t: {"uid": "u3", "email": "bob@test.com", "role": "admin"})
    bob = TestClient(appmod.app)
    assert bob.get("/me/nav", headers=AUTH).json() == {
        "pins": [], "sections": [], "collapsed": False, "saved": False,
    }
    bob.put("/me/nav", json=_nav(pins=["logs"]), headers=AUTH)
    set_verifier(lambda t: {"uid": "u2", "email": "alice@test.com", "role": "sales"})
    assert alice.get("/me/nav", headers=AUTH).json()["pins"] == ["search-ask"]


def test_nav_unauthenticated_is_401():
    set_verifier(lambda t: {})
    r = TestClient(appmod.app).get("/me/nav")
    assert r.status_code == 401
    r = TestClient(appmod.app).put("/me/nav", json=_nav(pins=["faq"]))
    assert r.status_code == 401


def test_nav_token_without_email_is_401():
    set_verifier(lambda t: {"uid": "u9", "role": "sales"})
    r = TestClient(appmod.app).get("/me/nav", headers=AUTH)
    assert r.status_code == 401
