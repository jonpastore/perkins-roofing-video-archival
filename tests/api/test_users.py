"""Tests for GET /admin/users and POST /admin/users/role.

Firebase auth calls are monkeypatched — no live Firebase needed.
Admin role required; sales gets 403.
"""
import types
import pytest
from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from api.routes.users import router as users_router
from app.models import init_db

# Mount the users router onto the shared app once (idempotent: skip if already present).
if not any(getattr(r, "path", None) == "/admin/users" for r in appmod.app.routes):
    appmod.app.include_router(users_router)


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


def _make_user(uid, email, role=None, display_name=None):
    """Build a minimal fake Firebase UserRecord-like object."""
    u = types.SimpleNamespace()
    u.uid = uid
    u.email = email
    u.display_name = display_name
    u.custom_claims = {"role": role} if role else {}
    return u


def _make_list_page(users):
    """Build a fake ListUsersPage with iterate_all()."""
    page = types.SimpleNamespace()
    page.iterate_all = lambda: iter(users)
    return page


# ---------------------------------------------------------------------------
# GET /admin/users
# ---------------------------------------------------------------------------

def test_list_users_admin_ok(admin_client, monkeypatch):
    fake_users = [
        _make_user("uid1", "alice@test.com", "admin", display_name="Alice Admin"),
        _make_user("uid2", "bob@test.com", "sales"),
        _make_user("uid3", "charlie@test.com", None),
    ]

    import api.routes.users as users_mod
    from app.config import settings
    # Isolate from the real DEFAULT_ADMINS so this test is deterministic.
    monkeypatch.setattr(settings, "DEFAULT_ADMINS", frozenset())
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=lambda max_results=200: _make_list_page(fake_users),
            get_user_by_email=None,
            set_custom_user_claims=None,
        ),
    )

    r = admin_client.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert body[0] == {"uid": "uid1", "email": "alice@test.com", "display_name": "Alice Admin", "role": "admin", "signature": None, "is_default_admin": False}
    assert body[1] == {"uid": "uid2", "email": "bob@test.com", "display_name": None, "role": "sales", "signature": None, "is_default_admin": False}
    assert body[2] == {"uid": "uid3", "email": "charlie@test.com", "display_name": None, "role": None, "signature": None, "is_default_admin": False}


def test_list_users_filters_blank_email(admin_client, monkeypatch):
    """Users with a blank/null email (anonymous accounts) must be excluded from results."""
    fake_users = [
        _make_user("uid1", "alice@test.com", "admin"),
        _make_user("uid_anon", "", None),    # blank email — should be filtered
        _make_user("uid_none", None, None),  # None email — should be filtered
    ]

    import api.routes.users as users_mod
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_ADMINS", frozenset())
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=lambda max_results=200: _make_list_page(fake_users),
            get_user_by_email=None,
            set_custom_user_claims=None,
        ),
    )

    r = admin_client.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["email"] == "alice@test.com"


def test_list_users_merges_default_admins(admin_client, monkeypatch):
    """DEFAULT_ADMINS not present in Firebase appear as synthetic admin entries."""
    # Firebase has jon (signed in) but not tim or amber
    fake_users = [
        _make_user("uid_jon", "jon@perkinsroofing.net", "admin", display_name="Jon"),
    ]

    import api.routes.users as users_mod
    from app.config import settings
    monkeypatch.setattr(
        settings,
        "DEFAULT_ADMINS",
        frozenset({"jon@perkinsroofing.net", "tim@perkinsroofing.net", "amber@perkinsroofing.net"}),
    )
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=lambda max_results=200: _make_list_page(fake_users),
            get_user_by_email=None,
            set_custom_user_claims=None,
        ),
    )

    r = admin_client.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()

    emails = {u["email"] for u in body}
    assert "jon@perkinsroofing.net" in emails
    assert "tim@perkinsroofing.net" in emails
    assert "amber@perkinsroofing.net" in emails

    # jon should appear only once (no duplicate)
    assert sum(1 for u in body if u["email"] == "jon@perkinsroofing.net") == 1

    # synthetic entries for tim and amber have uid prefix and role=admin
    for u in body:
        if u["email"] in {"tim@perkinsroofing.net", "amber@perkinsroofing.net"}:
            assert u["uid"].startswith("default:")
            assert u["role"] == "admin"
            assert u["display_name"] is None

    # jon's real Firebase entry is preserved
    jon = next(u for u in body if u["email"] == "jon@perkinsroofing.net")
    assert jon["uid"] == "uid_jon"
    assert jon["display_name"] == "Jon"


def test_list_users_sales_forbidden(sales_client):
    r = sales_client.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


def test_list_users_unauthenticated():
    r = TestClient(appmod.app).get("/admin/users")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /admin/users/role
# ---------------------------------------------------------------------------

def test_set_role_grant(admin_client, monkeypatch):
    fake_user = _make_user("uid1", "alice@test.com", None)
    captured = {}

    def fake_set_claims(uid, claims):
        captured["uid"] = uid
        captured["claims"] = claims

    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=lambda email: fake_user,
            set_custom_user_claims=fake_set_claims,
        ),
    )

    r = admin_client.post(
        "/admin/users/role",
        json={"email": "alice@test.com", "role": "admin"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"uid": "uid1", "email": "alice@test.com", "role": "admin"}
    assert captured["claims"] == {"role": "admin"}


def test_set_role_clear(admin_client, monkeypatch):
    fake_user = _make_user("uid1", "alice@test.com", "sales")
    captured = {}

    def fake_set_claims(uid, claims):
        captured["uid"] = uid
        captured["claims"] = claims

    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=lambda email: fake_user,
            set_custom_user_claims=fake_set_claims,
        ),
    )

    r = admin_client.post(
        "/admin/users/role",
        json={"email": "alice@test.com", "role": None},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"uid": "uid1", "email": "alice@test.com", "role": None}
    # role key should be removed from claims
    assert "role" not in captured["claims"]


def test_set_role_user_not_found(admin_client, monkeypatch):
    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=lambda email: (_ for _ in ()).throw(Exception("not found")),
            set_custom_user_claims=None,
        ),
    )

    r = admin_client.post(
        "/admin/users/role",
        json={"email": "nobody@test.com", "role": "sales"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 404


def test_set_role_invalid_role(admin_client, monkeypatch):
    fake_user = _make_user("uid1", "alice@test.com", None)

    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=lambda email: fake_user,
            set_custom_user_claims=lambda uid, claims: None,
        ),
    )

    r = admin_client.post(
        "/admin/users/role",
        json={"email": "alice@test.com", "role": "superuser"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422


def test_set_role_sales_forbidden(sales_client):
    r = sales_client.post(
        "/admin/users/role",
        json={"email": "x@test.com", "role": "sales"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /admin/users/invite
# ---------------------------------------------------------------------------

def test_invite_creates_new_user(admin_client, monkeypatch):
    """When the email has no Firebase record, create_user is called and role is set."""
    created = {}
    claims_set = {}
    new_user = _make_user("uid_new", "external@example.com", display_name="External User")

    def fake_get_by_email(email):
        raise Exception("not found")

    def fake_create_user(**kwargs):
        created.update(kwargs)
        return new_user

    def fake_set_claims(uid, claims):
        claims_set["uid"] = uid
        claims_set["claims"] = claims

    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=fake_get_by_email,
            create_user=fake_create_user,
            set_custom_user_claims=fake_set_claims,
        ),
    )

    r = admin_client.post(
        "/admin/users/invite",
        json={"email": "external@example.com", "role": "web_admin", "display_name": "External User"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == "uid_new"
    assert body["email"] == "external@example.com"
    assert body["role"] == "web_admin"
    assert created["email"] == "external@example.com"
    assert created["display_name"] == "External User"
    assert claims_set["claims"] == {"role": "web_admin"}


def test_invite_existing_user_sets_role(admin_client, monkeypatch):
    """When the email already has a Firebase record, no create_user; just set claims."""
    existing = _make_user("uid_existing", "existing@example.com", role=None, display_name="Existing Person")
    claims_set = {}

    def fake_set_claims(uid, claims):
        claims_set["uid"] = uid
        claims_set["claims"] = claims

    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=lambda email: existing,
            create_user=None,  # must NOT be called
            set_custom_user_claims=fake_set_claims,
        ),
    )

    r = admin_client.post(
        "/admin/users/invite",
        json={"email": "existing@example.com", "role": "sales"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == "uid_existing"
    assert body["role"] == "sales"
    assert claims_set["claims"] == {"role": "sales"}


def test_invite_invalid_role(admin_client, monkeypatch):
    """Invalid role is rejected with 422 before any Firebase call."""
    import api.routes.users as users_mod
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=None,
            get_user_by_email=lambda email: _make_user("uid1", email),
            create_user=None,
            set_custom_user_claims=None,
        ),
    )

    r = admin_client.post(
        "/admin/users/invite",
        json={"email": "x@example.com", "role": "superuser"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 422


def test_invite_sales_forbidden(sales_client):
    """Sales role cannot call the invite endpoint."""
    r = sales_client.post(
        "/admin/users/invite",
        json={"email": "x@example.com", "role": "sales"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403
