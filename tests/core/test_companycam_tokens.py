from core.companycam.tokens import load_bearer


def test_load_bearer_prefers_env(monkeypatch):
    monkeypatch.setenv("COMPANYCAM_PAT", "env-tok")
    assert load_bearer() == "env-tok"


def test_save_bearer_writes_application_key_only(monkeypatch):
    seen = []

    class _C:
        def add_secret_version(self, request):
            seen.append(request)

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    from core.companycam import tokens as T
    T.save_bearer("tok", sm_client=_C())
    assert len(seen) == 1
    assert seen[0]["parent"].endswith("companycam-pat")
    assert not hasattr(T, "save_oauth")


def test_load_bearer_from_sm(monkeypatch):
    class _Ver:
        payload = type("P", (), {"data": b"sm-tok"})()

    class _C:
        def access_secret_version(self, name):
            return _Ver()

    monkeypatch.delenv("COMPANYCAM_PAT", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    from core.companycam import tokens as T
    monkeypatch.setattr(T, "_client", lambda: _C())
    assert T.load_bearer() == "sm-tok"


def test_load_bearer_empty_without_env_or_project(monkeypatch):
    monkeypatch.delenv("COMPANYCAM_PAT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    assert load_bearer() == ""
