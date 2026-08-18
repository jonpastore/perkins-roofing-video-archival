"""Broken creds: prompt, verify, then vault. Never write a password that failed."""
from core import verified_secret as VS


def test_update_after_verify_skips_save_when_verify_fails():
    saved = []
    try:
        VS.update_after_verify(
            "some-secret",
            {"username": "u", "password": "bad"},
            verify=lambda blob: False,
            save=lambda sid, blob: saved.append((sid, blob)),
        )
        assert False, "must raise"
    except RuntimeError:
        pass
    assert saved == []


def test_update_after_verify_writes_only_after_success():
    saved = []
    out = VS.update_after_verify(
        "some-secret",
        {"username": "u", "password": "ok"},
        verify=lambda blob: blob["password"] == "ok",
        save=lambda sid, blob: saved.append((sid, blob)),
    )
    assert out is True
    assert saved == [("some-secret", {"username": "u", "password": "ok"})]


def test_update_after_verify_default_save(monkeypatch):
    saved = []
    monkeypatch.setattr(VS, "save_json_secret", lambda sid, blob: saved.append((sid, blob)))
    assert VS.update_after_verify(
        "sid", {"username": "u", "password": "p"}, verify=lambda _b: True,
    )
    assert saved == [("sid", {"username": "u", "password": "p"})]


def test_parse_prompt_pair():
    assert VS.normalize_login("  a@b.c  ", " x ") == {"username": "a@b.c", "password": " x "}
    try:
        VS.normalize_login("", "x")
        assert False
    except RuntimeError:
        pass
    try:
        VS.normalize_login("u", "")
        assert False
    except RuntimeError:
        pass


def test_update_text_after_verify_skips_bad():
    saved = []
    try:
        VS.update_text_after_verify(
            "wordpress-app-password", "bad",
            verify=lambda t: False,
            save=lambda sid, t: saved.append(t),
        )
        assert False
    except RuntimeError:
        pass
    assert saved == []


def test_update_text_after_verify_writes(monkeypatch):
    saved = []
    monkeypatch.setattr(VS, "save_text_secret", lambda sid, text: saved.append((sid, text)))
    assert VS.update_text_after_verify("sid", "ok", verify=lambda t: t == "ok")
    assert saved == [("sid", "ok")]


def test_can_prompt_true_and_false(monkeypatch):
    monkeypatch.setattr(VS.sys, "stdin", type("S", (), {"isatty": lambda self: True})())
    assert VS.can_prompt() is True
    monkeypatch.setattr(VS.sys, "stdin", type("S", (), {"isatty": lambda self: False})())
    assert VS.can_prompt() is False
    monkeypatch.setattr(VS.sys, "stdin", None)
    assert VS.can_prompt() is False


def test_prompt_username_password_uses_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "")
    monkeypatch.setattr(VS.getpass, "getpass", lambda _p: "secret")
    assert VS.prompt_username_password(default_user="jon") == {
        "username": "jon", "password": "secret",
    }


def test_prompt_username_password_typed(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "  a@b.c  ")
    monkeypatch.setattr(VS.getpass, "getpass", lambda _p: "pw")
    assert VS.prompt_username_password() == {"username": "a@b.c", "password": "pw"}


def test_prompt_and_update(monkeypatch):
    saved = []
    monkeypatch.setattr(
        VS, "prompt_username_password",
        lambda **k: {"username": "u", "password": "p"},
    )
    assert VS.prompt_and_update(
        "sid",
        verify=lambda b: b["username"] == "u",
        save=lambda sid, blob: saved.append((sid, blob)),
    )
    assert saved == [("sid", {"username": "u", "password": "p"})]


def test_save_json_and_text_secret(monkeypatch):
    calls = []

    class _C:
        def add_secret_version(self, request):
            calls.append(request)

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    import google.cloud.secretmanager as sm  # noqa: PLC0415
    monkeypatch.setattr(sm, "SecretManagerServiceClient", lambda: _C())
    VS.save_json_secret("sid", {"username": "u", "password": "p"})
    VS.save_text_secret("sid", "plain")
    assert calls[0]["parent"] == "projects/proj/secrets/sid"
    assert b'"username"' in calls[0]["payload"]["data"]
    assert calls[1]["payload"]["data"] == b"plain"


def test_save_secret_falls_back_to_gcp_project(monkeypatch):
    calls = []

    class _C:
        def add_secret_version(self, request):
            calls.append(request)

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "alt")
    import google.cloud.secretmanager as sm  # noqa: PLC0415
    monkeypatch.setattr(sm, "SecretManagerServiceClient", lambda: _C())
    VS.save_text_secret("sid", "x")
    assert calls[0]["parent"] == "projects/alt/secrets/sid"
