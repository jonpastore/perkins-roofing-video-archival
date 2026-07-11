"""Knowify token-lifecycle tests (TRD §3/§4) — network + Secret Manager MOCKED.

This is an OAuth/secret module: the golden rule under test is that a token VALUE
(access_token / refresh_token string) is NEVER logged. Every test that touches the
refresh/validate path also asserts no token substring leaked into captured logs.

Fail-loud contract (Wave-0 reality — Knowify OAuth is 500-ing on the RFC 8707
`resource` param and 401-ing tokens minted without it): a persistent 401, a 500, or a
400 invalid_grant on refresh -> `auth_error`, refresh attempted AT MOST ONCE, and no
dead token written as `latest`.
"""
from __future__ import annotations

import io
import json
import logging
import runpy
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from core.knowify import tokens as T

ACCESS = "acc_SECRETVALUE_12345"
REFRESH = "ref_SECRETVALUE_67890"
NEW_ACCESS = "acc_ROTATED_aaaaa"
NEW_REFRESH = "ref_ROTATED_bbbbb"

TOK = {
    "client_id": "cid-1",
    "access_token": ACCESS,
    "refresh_token": REFRESH,
    "scope": "read",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _sm_client(secret_value: dict) -> MagicMock:
    """A mock SecretManagerServiceClient whose access_secret_version returns JSON."""
    client = MagicMock()
    version = MagicMock()
    version.payload.data = json.dumps(secret_value).encode()
    client.access_secret_version.return_value = version
    return client


def _http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


class _Resp:
    """Minimal urlopen context-manager returning a fixed JSON body / status."""

    def __init__(self, body: dict, status: int = 200):
        self._body = json.dumps(body).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _assert_no_token_leak(caplog):
    blob = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (ACCESS, REFRESH, NEW_ACCESS, NEW_REFRESH):
        assert secret not in blob, f"token value {secret!r} leaked into logs"


# --------------------------------------------------------------------------- #
# load_tokens
# --------------------------------------------------------------------------- #

def test_load_tokens_reads_latest_version():
    sm = _sm_client(TOK)
    tok = T.load_tokens(sm_client=sm, project="proj")
    assert tok["access_token"] == ACCESS
    assert tok["refresh_token"] == REFRESH
    # must read the LATEST version of knowify-tokens
    name = str(sm.access_secret_version.call_args)
    assert "knowify-tokens" in name
    assert "versions/latest" in name


# --------------------------------------------------------------------------- #
# is_valid — /api/v2/valid preflight
# --------------------------------------------------------------------------- #

def test_is_valid_true_on_200(caplog):
    caplog.set_level(logging.DEBUG)
    with patch.object(T.urllib.request, "urlopen", return_value=_Resp({}, 200)):
        assert T.is_valid(TOK) is True
    _assert_no_token_leak(caplog)


def test_is_valid_false_on_401(caplog):
    caplog.set_level(logging.DEBUG)
    with patch.object(T.urllib.request, "urlopen", side_effect=_http_error(401)):
        assert T.is_valid(TOK) is False
    _assert_no_token_leak(caplog)


# --------------------------------------------------------------------------- #
# refresh — happy path: rotate + write new version
# --------------------------------------------------------------------------- #

def test_refresh_rotates_and_saves_new_version(caplog):
    caplog.set_level(logging.DEBUG)
    sm = _sm_client(TOK)
    new = {"access_token": NEW_ACCESS, "refresh_token": NEW_REFRESH}
    with patch.object(T.urllib.request, "urlopen", return_value=_Resp(new, 200)):
        out = T.refresh(dict(TOK), sm_client=sm, project="proj")
    assert out["access_token"] == NEW_ACCESS
    assert out["refresh_token"] == NEW_REFRESH
    # rotated blob written as a NEW secret version via save_tokens/add_secret_version
    assert sm.add_secret_version.called
    written = sm.add_secret_version.call_args.kwargs["request"]["payload"]["data"]
    assert json.loads(written)["refresh_token"] == NEW_REFRESH
    _assert_no_token_leak(caplog)


def test_refresh_posts_resource_param():
    """RFC 8707 resource param bound to the REST API is sent on the refresh grant."""
    sm = _sm_client(TOK)
    new = {"access_token": NEW_ACCESS, "refresh_token": NEW_REFRESH}
    captured = {}

    def _fake_urlopen(req, timeout=0):
        captured["data"] = req.data.decode()
        return _Resp(new, 200)

    with patch.object(T.urllib.request, "urlopen", side_effect=_fake_urlopen):
        T.refresh(dict(TOK), sm_client=sm, project="proj")
    assert "grant_type=refresh_token" in captured["data"]
    assert "resource=" in captured["data"]


# --------------------------------------------------------------------------- #
# fail-loud: 500 / 400 invalid_grant / persistent 401 -> auth_error, no dead write
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("code,body", [
    (500, b"{}"),
    (400, b'{"error":"invalid_grant"}'),
    (401, b"{}"),
])
def test_refresh_fail_loud_sets_auth_error_and_writes_nothing(code, body, caplog):
    caplog.set_level(logging.DEBUG)
    sm = _sm_client(TOK)
    calls = {"n": 0}

    def _fail(req, timeout=0):
        calls["n"] += 1
        raise _http_error(code, body)

    with patch.object(T.urllib.request, "urlopen", side_effect=_fail):
        with pytest.raises(T.AuthError):
            T.refresh(dict(TOK), sm_client=sm, project="proj")
    # refreshed AT MOST ONCE — no retry-loop, no token burn
    assert calls["n"] == 1
    # never wrote a dead token as latest
    assert not sm.add_secret_version.called
    _assert_no_token_leak(caplog)


# --------------------------------------------------------------------------- #
# AC-9 race: refresh+rotate+write wrapped in advisory lock 8274125
# --------------------------------------------------------------------------- #

def _sql_and_key(call):
    """Extract the SQL string + bound :k value from a session.execute(text(...), {..}) call."""
    clause = call.args[0]
    params = call.args[1] if len(call.args) > 1 else {}
    return getattr(clause, "text", str(clause)), params.get("k")


def test_with_token_lock_uses_key_8274125():
    session = MagicMock()
    session.bind.dialect.name = "postgresql"
    with T.with_token_lock(session):
        pass
    stmts = [_sql_and_key(c) for c in session.execute.call_args_list]
    joined = "\n".join(s for s, _ in stmts)
    keys = {k for _, k in stmts}
    assert "pg_advisory_lock" in joined
    assert 8274125 in keys
    # blocking lock (not try_) so a second concurrent refresh WAITS, then unlock
    assert "pg_try_advisory_lock" not in joined
    assert "pg_advisory_unlock" in joined


def test_with_token_lock_acquire_before_write_release_after():
    """Lock is acquired around the write: acquire, then the body's write, then release."""
    session = MagicMock()
    session.bind.dialect.name = "postgresql"
    order = []
    session.execute.side_effect = lambda *a, **k: order.append(
        getattr(a[0], "text", str(a[0]))
    )
    with T.with_token_lock(session):
        order.append("WRITE")
    assert "pg_advisory_lock" in order[0]
    assert "pg_advisory_lock" in order[order.index("WRITE") - 1]
    assert "pg_advisory_unlock" in order[-1]


def test_with_token_lock_noop_on_sqlite():
    session = MagicMock()
    session.bind.dialect.name = "sqlite"
    with T.with_token_lock(session):
        pass
    # no advisory-lock SQL issued on sqlite (dev)
    joined = "\n".join(
        getattr(c.args[0], "text", str(c.args[0])) for c in session.execute.call_args_list
    )
    assert "advisory" not in joined


# --------------------------------------------------------------------------- #
# save_tokens writes a new version and never logs the value
# --------------------------------------------------------------------------- #

def test_save_tokens_adds_new_version_no_leak(caplog):
    caplog.set_level(logging.DEBUG)
    sm = MagicMock()
    T.save_tokens(dict(TOK), sm_client=sm, project="proj")
    req = sm.add_secret_version.call_args.kwargs["request"]
    assert req["parent"].endswith("secrets/knowify-tokens")
    assert json.loads(req["payload"]["data"])["access_token"] == ACCESS
    _assert_no_token_leak(caplog)


# --------------------------------------------------------------------------- #
# is_valid re-raises non-401 (e.g. the Wave-0 500) — must not be swallowed as "valid"
# --------------------------------------------------------------------------- #

def test_is_valid_reraises_500():
    with patch.object(T.urllib.request, "urlopen", side_effect=_http_error(500)):
        with pytest.raises(urllib.error.HTTPError):
            T.is_valid(TOK)


# --------------------------------------------------------------------------- #
# project / client resolution fallbacks
# --------------------------------------------------------------------------- #

def test_project_falls_back_to_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "env-proj")
    assert T._project("") == "env-proj"


def test_client_passthrough_when_provided():
    fake = MagicMock()
    assert T._client(fake) is fake


def test_client_builds_real_when_none():
    fake_mod = MagicMock()
    fake_mod.SecretManagerServiceClient.return_value = "REAL"
    with patch.dict("sys.modules", {"google.cloud.secretmanager": fake_mod}):
        assert T._client(None) == "REAL"


# --------------------------------------------------------------------------- #
# refresh_only keep-warm entrypoint (SessionLocal + SM mocked)
# --------------------------------------------------------------------------- #

def _patch_session():
    session = MagicMock()
    session.bind.dialect.name = "postgresql"
    return session


def test_refresh_only_noop_when_valid(monkeypatch):
    monkeypatch.setattr(T, "load_tokens", lambda: dict(TOK))
    monkeypatch.setattr(T, "is_valid", lambda tok: True)
    monkeypatch.setattr("app.models.SessionLocal", lambda: _patch_session())
    assert T.refresh_only() == 0


def test_refresh_only_refreshes_dead_token_under_lock(monkeypatch):
    session = _patch_session()
    monkeypatch.setattr("app.models.SessionLocal", lambda: session)
    monkeypatch.setattr(T, "load_tokens", lambda **k: dict(TOK))
    # dead before, dead on re-read under lock -> must refresh
    monkeypatch.setattr(T, "is_valid", lambda tok: False)
    called = {}
    monkeypatch.setattr(T, "refresh", lambda tok: called.setdefault("r", True))
    assert T.refresh_only() == 0
    assert called.get("r")


def test_refresh_only_returns_1_on_auth_error(monkeypatch):
    session = _patch_session()
    monkeypatch.setattr("app.models.SessionLocal", lambda: session)
    monkeypatch.setattr(T, "load_tokens", lambda **k: dict(TOK))
    monkeypatch.setattr(T, "is_valid", lambda tok: False)

    def _boom(tok):
        raise T.AuthError("dead")

    monkeypatch.setattr(T, "refresh", _boom)
    assert T.refresh_only() == 1


def test_refresh_only_valid_on_reread_skips_refresh(monkeypatch):
    """First is_valid False (preflight), but valid on re-read under lock -> no refresh."""
    session = _patch_session()
    monkeypatch.setattr("app.models.SessionLocal", lambda: session)
    monkeypatch.setattr(T, "load_tokens", lambda **k: dict(TOK))
    states = iter([False, True])  # preflight dead, then live under lock
    monkeypatch.setattr(T, "is_valid", lambda tok: next(states))
    monkeypatch.setattr(T, "refresh", lambda tok: pytest.fail("should not refresh"))
    assert T.refresh_only() == 0


# --------------------------------------------------------------------------- #
# __main__ dispatch — usage error without the flag; refresh-only wiring
# --------------------------------------------------------------------------- #

def test_main_usage_error_without_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["tokens"])
    with pytest.raises(SystemExit) as ei:
        runpy.run_module("core.knowify.tokens", run_name="__main__")
    assert "usage" in str(ei.value)


def test_main_refresh_only_dispatch(monkeypatch):
    """--refresh-only dispatches to refresh_only() and sys.exit()s its code (line 202-203).

    runpy re-execs the module in a fresh namespace, so we patch only shared collaborators
    the fresh copy reaches: SessionLocal, urllib (shared module -> /valid returns 200), and
    the SM client via sys.modules (so load_tokens reads our fixture). Live token -> exit 0.
    """
    monkeypatch.setattr("app.models.SessionLocal", lambda: _patch_session())
    monkeypatch.setattr(sys, "argv", ["tokens", "--refresh-only"])
    fake_sm = _sm_client(TOK)
    fake_mod = MagicMock()
    fake_mod.SecretManagerServiceClient.return_value = fake_sm
    with patch.dict("sys.modules", {"google.cloud.secretmanager": fake_mod}), \
         patch.object(T.urllib.request, "urlopen", return_value=_Resp({}, 200)):
        with pytest.raises(SystemExit) as ei:
            runpy.run_module("core.knowify.tokens", run_name="__main__")
    assert ei.value.code == 0


# --------------------------------------------------------------------------- #
# MCP-token path (STOPGAP) — own secret knowify-mcp-tokens, camelCase blob,
# refresh with resource=MCP audience, single-use rotate, fail-loud, expiry-gated.
# --------------------------------------------------------------------------- #

_FUTURE_MS = 32503680000000  # ~year 3000
_PAST_MS = 1

MCP_TOK = {
    "clientId": "cid-1",
    "accessToken": ACCESS,
    "refreshToken": REFRESH,
    "expiresAt": _FUTURE_MS,
    "scope": "admin read write offline_access",
}


def test_load_mcp_tokens_reads_latest_version():
    sm = _sm_client(MCP_TOK)
    tok = T.load_mcp_tokens(sm_client=sm, project="proj")
    assert tok["accessToken"] == ACCESS
    name = str(sm.access_secret_version.call_args)
    assert "knowify-mcp-tokens" in name
    assert "versions/latest" in name


def test_save_mcp_tokens_adds_new_version_no_leak(caplog):
    caplog.set_level(logging.DEBUG)
    sm = MagicMock()
    T.save_mcp_tokens(dict(MCP_TOK), sm_client=sm, project="proj")
    req = sm.add_secret_version.call_args.kwargs["request"]
    assert req["parent"].endswith("secrets/knowify-mcp-tokens")
    assert json.loads(req["payload"]["data"])["accessToken"] == ACCESS
    _assert_no_token_leak(caplog)


def test_mcp_expired_true_without_expiresAt():
    assert T._mcp_expired({"accessToken": ACCESS}) is True


def test_mcp_expired_true_when_past():
    assert T._mcp_expired({"expiresAt": _PAST_MS}) is True


def test_mcp_expired_false_when_far_future():
    assert T._mcp_expired({"expiresAt": _FUTURE_MS}) is False


def test_refresh_mcp_uses_mcp_resource_and_rotates(caplog):
    caplog.set_level(logging.DEBUG)
    sm = _sm_client(MCP_TOK)
    new = {"access_token": NEW_ACCESS, "refresh_token": NEW_REFRESH, "expires_in": 3600}
    captured = {}

    def _fake_urlopen(req, timeout=0):
        captured["data"] = req.data.decode()
        return _Resp(new, 200)

    with patch.object(T.urllib.request, "urlopen", side_effect=_fake_urlopen):
        out = T.refresh_mcp(dict(MCP_TOK), sm_client=sm, project="proj")
    # resource bound to the MCP audience (…/api/v2/mcp), NOT the REST /api/v2 that 500s
    assert "grant_type=refresh_token" in captured["data"]
    assert "v2%2Fmcp" in captured["data"]
    assert out["accessToken"] == NEW_ACCESS
    assert out["refreshToken"] == NEW_REFRESH  # single-use rotation
    assert out["expiresAt"] > _PAST_MS  # recomputed from expires_in
    assert sm.add_secret_version.called
    _assert_no_token_leak(caplog)


@pytest.mark.parametrize("code,body", [
    (500, b"{}"),
    (400, b'{"error":"invalid_grant"}'),
    (401, b"{}"),
])
def test_refresh_mcp_fail_loud_writes_nothing(code, body, caplog):
    caplog.set_level(logging.DEBUG)
    sm = _sm_client(MCP_TOK)
    calls = {"n": 0}

    def _fail(req, timeout=0):
        calls["n"] += 1
        raise _http_error(code, body)

    with patch.object(T.urllib.request, "urlopen", side_effect=_fail):
        with pytest.raises(T.AuthError):
            T.refresh_mcp(dict(MCP_TOK), sm_client=sm, project="proj")
    assert calls["n"] == 1  # AT MOST ONCE — no token burn
    assert not sm.add_secret_version.called
    _assert_no_token_leak(caplog)


def test_mcp_access_token_returns_when_valid(monkeypatch):
    monkeypatch.setattr(T, "load_mcp_tokens", lambda: dict(MCP_TOK))
    # far-future expiry -> no session, no refresh
    monkeypatch.setattr("app.models.SessionLocal",
                        lambda: pytest.fail("must not open a session when token is valid"))
    assert T.mcp_access_token() == ACCESS


def test_mcp_access_token_refreshes_under_lock(monkeypatch):
    session = _patch_session()
    monkeypatch.setattr("app.models.SessionLocal", lambda: session)
    monkeypatch.setattr(T, "load_mcp_tokens", lambda **k: dict(MCP_TOK, expiresAt=_PAST_MS))
    refreshed = {"accessToken": NEW_ACCESS}
    called = {}

    def _fake_refresh(tok):
        called["r"] = True
        return refreshed

    monkeypatch.setattr(T, "refresh_mcp", _fake_refresh)
    assert T.mcp_access_token() == NEW_ACCESS
    assert called.get("r")


def test_mcp_refresh_only_noop_when_valid(monkeypatch):
    monkeypatch.setattr(T, "load_mcp_tokens", lambda: dict(MCP_TOK))
    monkeypatch.setattr("app.models.SessionLocal", lambda: _patch_session())
    assert T.mcp_refresh_only() == 0


def test_mcp_refresh_only_refreshes_dead(monkeypatch):
    session = _patch_session()
    monkeypatch.setattr("app.models.SessionLocal", lambda: session)
    monkeypatch.setattr(T, "load_mcp_tokens", lambda **k: dict(MCP_TOK, expiresAt=_PAST_MS))
    called = {}
    monkeypatch.setattr(T, "refresh_mcp", lambda tok: called.setdefault("r", True))
    assert T.mcp_refresh_only() == 0
    assert called.get("r")


def test_mcp_refresh_only_returns_1_on_auth_error(monkeypatch):
    session = _patch_session()
    monkeypatch.setattr("app.models.SessionLocal", lambda: session)
    monkeypatch.setattr(T, "load_mcp_tokens", lambda **k: dict(MCP_TOK, expiresAt=_PAST_MS))

    def _boom(tok):
        raise T.AuthError("dead")

    monkeypatch.setattr(T, "refresh_mcp", _boom)
    assert T.mcp_refresh_only() == 1
