"""Knowify login vault — username/password in Secret Manager, never logged."""
from core.knowify import login_vault as V


def test_parse_login_blob_requires_both():
    try:
        V.parse_login_blob({})
        assert False
    except RuntimeError:
        pass
    try:
        V.parse_login_blob({"username": "a"})
        assert False
    except RuntimeError:
        pass


def test_parse_login_blob_accepts_email_alias():
    out = V.parse_login_blob({"email": "jon@perkinsroofing.net", "password": "x"})
    assert out["username"] == "jon@perkinsroofing.net"
    assert out["password"] == "x"


def test_load_login_reads_latest_secret(monkeypatch):
    class _Ver:
        payload = type("P", (), {"data": b'{"username":"u","password":"p"}'})()

    class _C:
        def access_secret_version(self, name):
            assert name.endswith("knowify-login/versions/latest")
            return _Ver()

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setattr(V, "_client", lambda: _C())
    assert V.load_login() == {"username": "u", "password": "p"}


def test_save_login_writes_json(monkeypatch):
    calls = []

    class _C:
        def add_secret_version(self, request):
            calls.append(request)

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setattr(V, "_client", lambda: _C())
    V.save_login("u", "p")
    assert calls[0]["parent"] == "projects/proj/secrets/knowify-login"
    assert b'"username": "u"' in calls[0]["payload"]["data"]


def test_configured_true(monkeypatch):
    monkeypatch.setattr(V, "load_login", lambda: {"username": "u", "password": "p"})
    assert V.configured() is True


def test_client_constructs(monkeypatch):
    import google.cloud.secretmanager as sm  # noqa: PLC0415
    monkeypatch.setattr(sm, "SecretManagerServiceClient", lambda: "CLIENT")
    assert V._client() == "CLIENT"


def test_project_falls_back_to_gcp_project(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "alt")
    assert V._project() == "alt"


def test_configured_false_when_secret_missing(monkeypatch):
    class _C:
        def access_secret_version(self, name):
            raise RuntimeError("not found")

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setattr(V, "_client", lambda: _C())
    assert V.configured() is False
