"""Behavioral validation for the keyless domain-wide-delegation token minting
(api.routes.users._directory_access_token). Mocks google.auth + urllib; asserts the
delegated JWT claims and the token exchange. R1 behavioral check for new I/O."""
import json

from api.routes import users as U

_SCOPE = "https://www.googleapis.com/auth/admin.directory.user.readonly"


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_keyless_token_signs_delegated_jwt_and_exchanges(monkeypatch):
    import urllib.request

    import google.auth

    class _ADC:
        token = "adc-token"
        service_account_email = "api-run-sa@proj.iam.gserviceaccount.com"

        def refresh(self, _req):
            pass

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (_ADC(), "proj"))

    seen = {}

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        body = req.data.decode() if req.data else ""
        if "signJwt" in url:
            claims = json.loads(json.loads(body)["payload"])
            seen.update(claims)
            # signed with the running SA's own ADC token → keyless
            assert req.headers["Authorization"] == "Bearer adc-token"
            return _Resp({"signedJwt": "SIGNED.JWT"})
        if "oauth2.googleapis.com/token" in url:
            assert "assertion=SIGNED.JWT" in body
            assert "jwt-bearer" in body
            return _Resp({"access_token": "final-token"})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    tok = U._directory_access_token("admin@perkinsroofing.net", _SCOPE, "")

    assert tok == "final-token"
    assert seen["iss"] == "api-run-sa@proj.iam.gserviceaccount.com"
    assert seen["sub"] == "admin@perkinsroofing.net"          # the impersonated Workspace admin
    assert seen["scope"] == _SCOPE
    assert seen["aud"] == "https://oauth2.googleapis.com/token"
    assert seen["exp"] > seen["iat"]


def test_key_file_path_uses_service_account_credentials(monkeypatch):
    from google.oauth2 import service_account

    class _Creds:
        token = "key-token"

        def refresh(self, _req):
            pass

    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_file",
        lambda f, scopes=None, subject=None: _Creds(),
    )
    assert U._directory_access_token("admin@x.com", _SCOPE, "/path/key.json") == "key-token"
