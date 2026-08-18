"""Headless Knowify OAuth relogin — browser is injected; no live Playwright."""
from core.knowify import playwright_relogin as R


def test_extract_code_from_redirect():
    assert R.code_from_url("http://127.0.0.1:8765/callback?code=abc&state=s") == "abc"
    assert R.code_from_url("http://127.0.0.1:8765/callback?error=access_denied") is None


def test_playwright_import_returns_sync_api(monkeypatch):
    import sys
    import types

    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = object()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    assert R._playwright_import() is api.sync_playwright


def test_playwright_import_returns_none_on_import_error(monkeypatch):
    import builtins
    orig = builtins.__import__

    def _imp(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("missing")
        return orig(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _imp)
    assert R._playwright_import() is None


def test_available_when_vault_configured(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: object)
    monkeypatch.setattr(R.login_vault, "configured", lambda: True)
    assert R.available() is True


def test_relogin_unavailable_without_playwright(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: None)
    assert R.available() is False


def test_relogin_exchanges_and_persists(monkeypatch):
    monkeypatch.setattr(R, "available", lambda: True)
    monkeypatch.setattr(R.login_vault, "load_login",
                        lambda: {"username": "u", "password": "p"})
    monkeypatch.setattr(R, "register_knowify_client", lambda uri: "cid")
    monkeypatch.setattr(R, "pkce", lambda: ("ver", "chal"))
    monkeypatch.setattr(R, "knowify_auth_url", lambda **k: "https://auth.example/x")
    monkeypatch.setattr(R, "_browser_get_code", lambda *a, **k: "THECODE")
    monkeypatch.setattr(R, "exchange_knowify",
                        lambda **k: {"access_token": "AT", "refresh_token": "RT", "expires_in": 60})
    saved = []
    monkeypatch.setattr(R, "persist_knowify_mcp", lambda tokens, cid: saved.append((tokens, cid)))
    vaulted = []
    monkeypatch.setattr(
        R.login_vault, "save_login",
        lambda u, p: vaulted.append((u, p)),
    )
    out = R.relogin()
    assert out["ok"] is True
    assert saved[0][1] == "cid"
    assert saved[0][0]["access_token"] == "AT"
    assert vaulted == [("u", "p")]


def test_relogin_skips_vault_when_persist_login_false(monkeypatch):
    monkeypatch.setattr(R.login_vault, "load_login",
                        lambda: {"username": "u", "password": "p"})
    monkeypatch.setattr(R, "register_knowify_client", lambda uri: "cid")
    monkeypatch.setattr(R, "pkce", lambda: ("ver", "chal"))
    monkeypatch.setattr(R, "knowify_auth_url", lambda **k: "https://auth.example/x")
    monkeypatch.setattr(R, "_browser_get_code", lambda *a, **k: "THECODE")
    monkeypatch.setattr(R, "exchange_knowify",
                        lambda **k: {"access_token": "AT", "refresh_token": "RT", "expires_in": 60})
    monkeypatch.setattr(R, "persist_knowify_mcp", lambda tokens, cid: None)
    vaulted = []
    monkeypatch.setattr(R.login_vault, "save_login", lambda u, p: vaulted.append((u, p)))
    assert R.relogin(persist_login=False)["ok"] is True
    assert vaulted == []


def test_available_when_prompt_possible(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: object)
    monkeypatch.setattr(R.login_vault, "configured", lambda: False)
    monkeypatch.setattr("core.verified_secret.can_prompt", lambda: True)
    assert R.available() is True


def test_relogin_or_prompt_uses_vault(monkeypatch):
    monkeypatch.setattr(R, "relogin", lambda **k: {"ok": True, "via": "vault"})
    assert R.relogin_or_prompt()["via"] == "vault"


def test_relogin_or_prompt_falls_back_on_tty(monkeypatch):
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


def test_relogin_or_prompt_reraise_without_tty(monkeypatch):
    monkeypatch.setattr(R, "relogin", lambda **k: (_ for _ in ()).throw(RuntimeError("dead")))
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
        self.url = "https://app.knowify.com/oauth"
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
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _PW:
    def __init__(self, page):
        self.chromium = type("C", (), {"launch": lambda self, headless=True: _Browser(page)})()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_browser_get_code_from_loopback(monkeypatch):
    page = _Page("http://127.0.0.1:8765/callback?code=THECODE&state=s")
    monkeypatch.setattr(R, "_playwright_import", lambda: (lambda: _PW(page)))
    assert R._browser_get_code("https://auth", "u", "p", headless=True) == "THECODE"


def test_browser_get_code_from_page_url(monkeypatch):
    page = _Page("http://unused")
    page.url = "http://127.0.0.1:8765/callback?code=FROMURL"
    page.route = lambda *_a, **_k: None
    page.wait_for_timeout = lambda _ms: None
    monkeypatch.setattr(R, "_playwright_import", lambda: (lambda: _PW(page)))
    assert R._browser_get_code("https://auth", "u", "p", headless=True) == "FROMURL"


def test_browser_get_code_raises_without_code(monkeypatch):
    page = _Page("http://127.0.0.1:8765/callback?error=access_denied")
    monkeypatch.setattr(R, "_playwright_import", lambda: (lambda: _PW(page)))
    try:
        R._browser_get_code("https://auth", "u", "p", headless=True)
        assert False
    except RuntimeError:
        pass


def test_browser_get_code_requires_playwright(monkeypatch):
    monkeypatch.setattr(R, "_playwright_import", lambda: None)
    try:
        R._browser_get_code("https://auth", "u", "p", headless=True)
        assert False
    except RuntimeError:
        pass


def test_keepwarm_hook_runs_relogin_on_auth_error(monkeypatch):
    from core.knowify import tokens as T

    calls = []
    monkeypatch.setattr(T, "load_mcp_tokens", lambda: {"expiresAt": 1, "accessToken": "x"})
    monkeypatch.setattr(T, "_mcp_expired", lambda tok: True)

    class _Lock:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(T, "with_token_lock", lambda session: _Lock())
    monkeypatch.setattr(T, "refresh_mcp", lambda tok: (_ for _ in ()).throw(T.AuthError("dead")))

    import core.knowify.playwright_relogin as PR
    monkeypatch.setattr(PR, "available", lambda: True)
    monkeypatch.setattr(PR, "relogin", lambda: calls.append("relogin") or {"ok": True})

    class _Sess:
        info = {}
        def close(self):
            pass

    import app.models as models
    monkeypatch.setattr(models, "SessionLocal", lambda: _Sess())
    assert T.mcp_refresh_only() == 0
    assert calls == ["relogin"]
