import pytest
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.app import app

#: Tim is a default admin. Since #359, "default admin" means a row in `tenant_default_admins`
#: for this tenant, not membership of the deployment-wide `settings.DEFAULT_ADMINS` frozenset —
#: /me resolves roles the same way the gates do, and the gates read the table. Verified against
#: prod 2026-08-02: the table holds exactly jon/tim/amber@perkinsroofing.net for tenant 1, the
#: same three the frozenset defaults to, and nothing overrides DEFAULT_ADMINS in deploy.sh or
#: terraform — so this is a change of mechanism, not of who is an admin.
TIM = "tim@perkinsroofing.net"


@pytest.fixture(autouse=True)
def _seed_admin():
    """The SQLite test DB is create_all, not migrated, so the seed that prod got from the
    identity migration has to be made explicit here."""
    from app.models import PlatformSessionLocal, TenantDefaultAdmin, init_db
    init_db()
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        if db.query(TenantDefaultAdmin).filter_by(tenant_id=1, email=TIM).one_or_none() is None:
            db.add(TenantDefaultAdmin(tenant_id=1, email=TIM))
            db.commit()


def _client(email, role, email_verified=True):
    set_verifier(lambda token: {"uid": "u", "email": email, "role": role,
                                "email_verified": email_verified})
    return TestClient(app)


def test_me_default_admin_email_is_admin_without_claim():
    # a VERIFIED granted email with no assigned claim still resolves to admin
    c = _client(TIM, "")
    r = c.get("/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_me_default_admin_email_NOT_admin_when_unverified():
    # security: an UNVERIFIED default-admin email must not be elevated (self-registration guard)
    c = _client(TIM, "", email_verified=False)
    r = c.get("/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["role"] is None


def test_me_regular_user_keeps_claim_role():
    c = _client("stranger@example.com", "sales")
    assert c.get("/me", headers={"Authorization": "Bearer x"}).json()["role"] == "sales"


def test_me_no_role_user_returns_null():
    c = _client("stranger@example.com", "")
    assert c.get("/me", headers={"Authorization": "Bearer x"}).json()["role"] is None


def test_me_requires_token():
    c = _client("stranger@example.com", "")
    assert c.get("/me").status_code == 401
