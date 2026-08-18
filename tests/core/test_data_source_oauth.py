"""Knowify OAuth helpers."""
from __future__ import annotations

import json

from core import data_source_oauth as dso


def test_pkce_pair_is_s256():
    import base64, hashlib
    v, c = dso.pkce()
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def test_knowify_auth_url_binds_mcp_audience():
    url = dso.knowify_auth_url(
        client_id="cid", redirect_uri="https://api.example.com/oauth/knowify/callback",
        state="st", challenge="ch",
    )
    assert url.startswith(dso.KNOWIFY_AUTH)
    assert "resource=" in url
    assert "code_challenge=ch" in url


def test_persist_knowify_requires_refresh():
    try:
        dso.persist_knowify_mcp({"access_token": "a"}, "cid")
        assert False
    except RuntimeError:
        pass


def test_register_knowify_client_requires_id(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"{}"

    monkeypatch.setattr(dso.urllib.request, "urlopen", lambda *a, **k: _Resp())
    try:
        dso.register_knowify_client("https://api.example.com/cb")
        assert False
    except RuntimeError:
        pass


def test_persist_knowify_writes_mcp_blob(monkeypatch):
    seen = []

    def _save(blob):
        seen.append(blob)

    import core.knowify.tokens as T
    monkeypatch.setattr(T, "save_mcp_tokens", _save)
    monkeypatch.setattr("core.connection_status.mark_healthy", lambda *a, **k: None)
    dso.persist_knowify_mcp(
        {"access_token": "a", "refresh_token": "r", "expires_in": 10}, "cid",
    )
    assert seen[0]["clientId"] == "cid"
    assert seen[0]["accessToken"] == "a"
    assert seen[0]["refreshToken"] == "r"


def test_companycam_oauth_helpers_are_gone():
    assert not hasattr(dso, "persist_companycam")
    assert not hasattr(dso, "COMPANYCAM_AUTH")


def test_register_knowify_client(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"client_id": "new-cid"}).encode()

    monkeypatch.setattr(dso.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert dso.register_knowify_client("https://api.example.com/cb") == "new-cid"


def test_exchange_knowify(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"access_token": "a", "refresh_token": "r"}).encode()

    monkeypatch.setattr(dso.urllib.request, "urlopen", lambda *a, **k: _Resp())
    out = dso.exchange_knowify(code="c", client_id="id", redirect_uri="u", verifier="v")
    assert out["access_token"] == "a"
