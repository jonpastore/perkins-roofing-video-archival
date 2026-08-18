"""YouTube API key + reply refresh token: verify, then vault."""
import json
import urllib.error

from core import youtube_creds as Y


class _Resp:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_verify_api_key_empty():
    assert Y.verify_api_key("") is False
    assert Y.verify_api_key("   ") is False


def test_verify_api_key_200_perkins():
    def _open(req, timeout=0):
        assert Y.CHANNEL_ID in req.full_url
        return _Resp({"items": [{"id": Y.CHANNEL_ID}]})

    assert Y.verify_api_key("AIza-ok", urlopen=_open) is True


def test_verify_api_key_wrong_or_empty_items():
    def _open(req, timeout=0):
        return _Resp({"items": []})

    assert Y.verify_api_key("AIza-x", urlopen=_open) is False


def test_verify_api_key_http_error():
    def _open(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", hdrs=None, fp=None)

    assert Y.verify_api_key("AIza-bad", urlopen=_open) is False


def test_verify_refresh_requires_client(monkeypatch):
    monkeypatch.delenv("OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)
    assert Y.verify_refresh_token("rt") is False


def test_verify_refresh_perkins_channel(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")
    calls = []

    def _open(req, timeout=0):
        calls.append(req.full_url)
        if "oauth2.googleapis.com/token" in req.full_url:
            return _Resp({"access_token": "AT"})
        return _Resp({"items": [{"id": Y.CHANNEL_ID, "snippet": {"title": "Perkins"}}]})

    assert Y.verify_refresh_token("rt", urlopen=_open) is True
    assert any("token" in u for u in calls)


def test_verify_refresh_wrong_channel(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")

    def _open(req, timeout=0):
        if "oauth2.googleapis.com/token" in req.full_url:
            return _Resp({"access_token": "AT"})
        return _Resp({"items": [{"id": "UCother", "snippet": {"title": "Nope"}}]})

    assert Y.verify_refresh_token("rt", urlopen=_open) is False


def test_verify_refresh_exchange_fail(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")

    def _open(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "invalid_grant", hdrs=None, fp=None)

    assert Y.verify_refresh_token("rt", urlopen=_open) is False


def test_load_refresh_prefers_gsm(monkeypatch):
    class _Ver:
        payload = type("P", (), {"data": b"  GSM-RT  "})()

    class _C:
        def access_secret_version(self, name):
            assert name.endswith("youtube-oauth-refresh-token/versions/latest")
            return _Ver()

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("YOUTUBE_OAUTH_REFRESH_TOKEN", "ENV-RT")
    monkeypatch.setattr(Y, "_client", lambda: _C())
    assert Y.load_refresh_token() == "GSM-RT"


def test_load_refresh_empty_gsm_uses_env(monkeypatch):
    class _Ver:
        payload = type("P", (), {"data": b"   "})()

    class _C:
        def access_secret_version(self, name):
            return _Ver()

    monkeypatch.setenv("YOUTUBE_OAUTH_REFRESH_TOKEN", "ENV-RT")
    monkeypatch.setattr(Y, "_client", lambda: _C())
    assert Y.load_refresh_token() == "ENV-RT"


def test_load_refresh_falls_back_to_env(monkeypatch):
    class _C:
        def access_secret_version(self, name):
            raise RuntimeError("missing")

    monkeypatch.setenv("YOUTUBE_OAUTH_REFRESH_TOKEN", "ENV-RT")
    monkeypatch.setattr(Y, "_client", lambda: _C())
    assert Y.load_refresh_token() == "ENV-RT"


def test_vault_api_key_skips_bad():
    saved = []
    try:
        Y.vault_api_key_after_verify(
            "bad",
            urlopen=lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("x")),
            save=lambda sid, t: saved.append(t),
        )
        assert False
    except RuntimeError:
        pass
    assert saved == []


def test_vault_api_key_writes():
    saved = []
    assert Y.vault_api_key_after_verify(
        "AIza-ok",
        urlopen=lambda *a, **k: _Resp({"items": [{"id": Y.CHANNEL_ID}]}),
        save=lambda sid, t: saved.append((sid, t)),
    )
    assert saved == [(Y.API_KEY_SECRET, "AIza-ok")]


def test_vault_refresh_writes(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setattr("core.connection_status.mark_healthy", lambda *a, **k: None)
    saved = []

    def _open(req, timeout=0):
        if "oauth2.googleapis.com/token" in req.full_url:
            return _Resp({"access_token": "AT"})
        return _Resp({"items": [{"id": Y.CHANNEL_ID, "snippet": {"title": "P"}}]})

    assert Y.vault_refresh_after_verify(
        "RT", urlopen=_open, save=lambda sid, t: saved.append((sid, t)),
    )
    assert saved == [(Y.REFRESH_SECRET, "RT")]


def test_parse_login_blob():
    assert Y.parse_login_blob({"email": "a@b.c", "password": "x"})["username"] == "a@b.c"
    try:
        Y.parse_login_blob({})
        assert False
    except RuntimeError:
        pass


def test_load_and_save_login(monkeypatch):
    class _Ver:
        payload = type("P", (), {"data": b'{"username":"u","password":"p"}'})()

    calls = []

    class _C:
        def access_secret_version(self, name):
            assert name.endswith("youtube-login/versions/latest")
            return _Ver()

        def add_secret_version(self, request):
            calls.append(request)

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setattr(Y, "_client", lambda: _C())
    assert Y.load_login() == {"username": "u", "password": "p"}
    assert Y.configured() is True
    Y.save_login("u", "p")
    assert calls[0]["parent"] == "projects/proj/secrets/youtube-login"


def test_configured_false(monkeypatch):
    class _C:
        def access_secret_version(self, name):
            raise RuntimeError("missing")

    monkeypatch.setattr(Y, "_client", lambda: _C())
    assert Y.configured() is False


def test_client_and_project(monkeypatch):
    import google.cloud.secretmanager as sm  # noqa: PLC0415
    monkeypatch.setattr(sm, "SecretManagerServiceClient", lambda: "CLIENT")
    assert Y._client() == "CLIENT"
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "alt")
    assert Y._project() == "alt"


def test_posting_channel_no_access(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")

    def _open(req, timeout=0):
        return _Resp({"access_token": ""})

    assert Y.posting_channel("rt", urlopen=_open) is None


def test_posting_channel_empty_items(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")

    def _open(req, timeout=0):
        if "oauth2.googleapis.com/token" in req.full_url:
            return _Resp({"access_token": "AT"})
        return _Resp({"items": []})

    assert Y.posting_channel("rt", urlopen=_open) is None


def test_prompt_and_vault_api_key(monkeypatch):
    saved = []
    monkeypatch.setattr(Y.getpass, "getpass", lambda _p: "AIza-ok")
    assert Y.prompt_and_vault_api_key(
        urlopen=lambda *a, **k: _Resp({"items": [{"id": Y.CHANNEL_ID}]}),
        save=lambda sid, t: saved.append(t),
    )
    assert saved == ["AIza-ok"]
