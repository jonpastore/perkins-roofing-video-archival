"""WP Application Password is vaulted only after GET /users/me succeeds."""
import urllib.error

from core import wordpress_creds as W


class _Resp:
    def __init__(self, status=200):
        self.status = status

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_users_me_url_strips_slash():
    assert W.users_me_url("https://ex.com/") == (
        "https://ex.com/wp-json/wp/v2/users/me?context=edit"
    )


def test_verify_rejects_empty():
    assert W.verify_app_password("", "p", wp_url="https://ex.com") is False
    assert W.verify_app_password("u", "", wp_url="https://ex.com") is False
    assert W.verify_app_password("u", "p", wp_url="") is False


def test_verify_uses_getcode_when_no_status():
    class _OnlyGetcode:
        def getcode(self):
            return 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert W.verify_app_password(
        "jon", "p", wp_url="https://ex.com",
        urlopen=lambda *a, **k: _OnlyGetcode(),
    )


def test_verify_200(monkeypatch):
    seen = {}

    def _open(req, timeout=0):
        seen["url"] = req.full_url
        seen["ua"] = req.get_header("User-agent")
        seen["auth"] = req.get_header("Authorization")
        return _Resp(200)

    assert W.verify_app_password("jon", "ab cd", wp_url="https://ex.com", urlopen=_open)
    assert seen["url"].endswith("/users/me?context=edit")
    assert "perkins-platform" in seen["ua"]
    assert seen["auth"].startswith("Basic ")


def test_verify_401():
    def _open(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "no", hdrs=None, fp=None)

    assert W.verify_app_password("jon", "bad", wp_url="https://ex.com", urlopen=_open) is False


def test_verify_network_error():
    def _open(req, timeout=0):
        raise urllib.error.URLError("down")

    assert W.verify_app_password("jon", "p", wp_url="https://ex.com", urlopen=_open) is False


def test_vault_after_verify_skips_bad():
    saved = []
    try:
        W.vault_after_verify(
            "jon", "bad", wp_url="https://ex.com",
            urlopen=lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("x")),
            save=lambda sid, t: saved.append(t),
        )
        assert False
    except RuntimeError:
        pass
    assert saved == []


def test_vault_after_verify_writes():
    saved = []
    assert W.vault_after_verify(
        "jon", "ok ok", wp_url="https://ex.com",
        urlopen=lambda *a, **k: _Resp(200),
        save=lambda sid, t: saved.append((sid, t)),
    )
    assert saved == [(W.SECRET_ID, "okok")]


def test_prompt_and_vault(monkeypatch):
    saved = []
    monkeypatch.setattr(
        W, "prompt_username_password",
        lambda **k: {"username": "jon", "password": "app-pw"},
    )
    assert W.prompt_and_vault(
        wp_url="https://ex.com",
        urlopen=lambda *a, **k: _Resp(200),
        save=lambda sid, t: saved.append(t),
    )
    assert saved == ["app-pw"]
