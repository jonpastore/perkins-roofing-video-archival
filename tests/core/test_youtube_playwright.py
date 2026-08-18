"""YouTube Playwright relogin — browser is injected; no live Google."""
from core import youtube_playwright as R


def test_code_from_url():
    assert R.code_from_url("http://localhost:8765/?code=abc&state=s") == "abc"
    assert R.code_from_url("http://localhost:8765/?error=access_denied") is None


def test_unavailable_without_playwright(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: None)
    assert R.available() is False


def test_available_with_vault(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: object)
    monkeypatch.setattr(R, "configured", lambda: True)
    assert R.available() is True


def test_available_with_prompt(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: object)
    monkeypatch.setattr(R, "configured", lambda: False)
    monkeypatch.setattr("core.verified_secret.can_prompt", lambda: True)
    assert R.available() is True


def test_relogin_requires_oauth_client(monkeypatch):
    monkeypatch.setattr(R, "load_login", lambda: {"username": "u", "password": "p"})
    monkeypatch.delenv("OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)
    try:
        R.relogin()
        assert False
    except RuntimeError:
        pass


def test_save_login_wrapper(monkeypatch):
    seen = []
    monkeypatch.setattr("core.youtube_creds.save_login", lambda u, p: seen.append((u, p)))
    R._save_login({"username": "u", "password": "p"})
    assert seen == [("u", "p")]


def test_relogin_or_prompt_uses_vault(monkeypatch):
    monkeypatch.setattr(R, "relogin", lambda **k: {"ok": True, "via": "vault"})
    assert R.relogin_or_prompt()["via"] == "vault"


def test_relogin_exchanges_and_vaults(monkeypatch):
    monkeypatch.setattr(R, "load_login", lambda: {"username": "u", "password": "p"})
    monkeypatch.setattr(R, "_browser_get_code", lambda *a, **k: "THECODE")
    monkeypatch.setattr(
        R, "exchange_code",
        lambda **k: {"access_token": "AT", "refresh_token": "RT"},
    )
    vaulted = []
    monkeypatch.setattr(R, "vault_refresh_after_verify", lambda rt, **k: vaulted.append(("rt", rt)))
    monkeypatch.setattr(
        R, "update_after_verify",
        lambda sid, blob, **k: vaulted.append(("login", blob["username"])),
    )
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")
    assert R.relogin()["ok"] is True
    assert ("rt", "RT") in vaulted
    assert ("login", "u") in vaulted


def test_relogin_skips_login_vault_when_disabled(monkeypatch):
    monkeypatch.setattr(R, "load_login", lambda: {"username": "u", "password": "p"})
    monkeypatch.setattr(R, "_browser_get_code", lambda *a, **k: "C")
    monkeypatch.setattr(R, "exchange_code", lambda **k: {"refresh_token": "RT", "access_token": "AT"})
    monkeypatch.setattr(R, "vault_refresh_after_verify", lambda *a, **k: True)
    saved = []
    monkeypatch.setattr(R, "update_after_verify", lambda *a, **k: saved.append(1))
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")
    R.relogin(persist_login=False)
    assert saved == []


def test_relogin_requires_refresh(monkeypatch):
    monkeypatch.setattr(R, "load_login", lambda: {"username": "u", "password": "p"})
    monkeypatch.setattr(R, "_browser_get_code", lambda *a, **k: "C")
    monkeypatch.setattr(R, "exchange_code", lambda **k: {"access_token": "AT"})
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "sec")
    try:
        R.relogin()
        assert False
    except RuntimeError:
        pass


def test_relogin_or_prompt_falls_back(monkeypatch):
    def _rel(*, headless=True, creds=None, persist_login=True):
        if creds:
            return {"ok": True, "via": creds["username"]}
        raise RuntimeError("vault dead")

    monkeypatch.setattr(R, "relogin", _rel)
    monkeypatch.setattr("core.verified_secret.can_prompt", lambda: True)
    monkeypatch.setattr(
        "core.verified_secret.prompt_username_password",
        lambda: {"username": "typed", "password": "p"},
    )
    assert R.relogin_or_prompt()["via"] == "typed"


def test_relogin_or_prompt_reraise(monkeypatch):
    monkeypatch.setattr(R, "relogin", lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("core.verified_secret.can_prompt", lambda: False)
    try:
        R.relogin_or_prompt()
        assert False
    except RuntimeError:
        pass


def test_relogin_or_prompt_force(monkeypatch):
    seen = []
    monkeypatch.setattr(R, "relogin", lambda **k: seen.append(k) or {"ok": True})
    monkeypatch.setattr(
        "core.verified_secret.prompt_username_password",
        lambda: {"username": "n", "password": "w"},
    )
    R.relogin_or_prompt(force_prompt=True)
    assert seen[0]["creds"]["username"] == "n"


class _Loc:
    def wait_for(self, timeout=0):
        return None

    def fill(self, _v):
        return None

    def click(self, timeout=0):
        return None


class _Route:
    def __init__(self, url):
        self.request = type("R", (), {"url": url})()

    def fulfill(self, **_k):
        return None


class _Page:
    def __init__(self, redirect):
        self.url = "https://accounts.google.com"
        self._redirect = redirect
        self._handler = None

    def route(self, _pat, fn):
        self._handler = fn

    def goto(self, *_a, **_k):
        return None

    def locator(self, _sel):
        return _Loc()

    def get_by_role(self, *_a, **_k):
        return _Loc()

    def wait_for_timeout(self, _ms):
        if self._handler:
            self._handler(_Route(self._redirect))
            self._handler = None


class _Browser:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page

    def close(self):
        return None


class _PW:
    def __init__(self, page):
        self.chromium = type("C", (), {"launch": lambda self, headless=True: _Browser(page)})()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_browser_get_code(monkeypatch):
    page = _Page("http://localhost:8765/?code=THECODE")
    monkeypatch.setattr(R, "_playwright_import", lambda: (lambda: _PW(page)))
    assert R._browser_get_code("https://auth", "u", "p", headless=True) == "THECODE"


def test_browser_requires_playwright(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: None)
    try:
        R._browser_get_code("https://auth", "u", "p", headless=True)
        assert False
    except RuntimeError:
        pass


def test_browser_no_code(monkeypatch):
    page = _Page("http://localhost:8765/?error=access_denied")
    monkeypatch.setattr(R, "_playwright_import", lambda: (lambda: _PW(page)))
    try:
        R._browser_get_code("https://auth", "u", "p", headless=True)
        assert False
    except RuntimeError:
        pass


def test_playwright_import_stub(monkeypatch):
    import sys
    import types

    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = object()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    assert R._playwright_import() is api.sync_playwright


def test_playwright_import_error(monkeypatch):
    import builtins
    orig = builtins.__import__

    def _imp(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("missing")
        return orig(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _imp)
    assert R._playwright_import() is None


def test_auth_url_has_consent():
    url = R.auth_url("cid")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "youtube.force-ssl" in url


def test_exchange_code(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"refresh_token":"RT","access_token":"AT"}'

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: _Resp(),
    )
    tok = R.exchange_code(code="c", client_id="cid", client_secret="sec")
    assert tok["refresh_token"] == "RT"
