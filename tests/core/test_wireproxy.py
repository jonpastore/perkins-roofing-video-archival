"""core/wireproxy config parsing + adapters.yt_dlp egress rotation.

The rotation rules are load-bearing and easy to get subtly wrong:
  - rotate ONLY on a bot-block (any other error fails identically on every exit)
  - stop at the first success
  - raise loudly when configs are exhausted, never fall back to a direct connection
  - with no configs, behave exactly as before (one direct attempt)
"""
import subprocess

import pytest

import adapters.yt_dlp as Y
from core.wireproxy import load_configs

_CFG_A = "[Interface]\nPrivateKey = aaa=\nAddress = 10.2.0.2/32\n\n[Peer]\nEndpoint = 1.1.1.1:51820\n"
_CFG_B = "[Interface]\nPrivateKey = bbb=\nAddress = 10.2.0.2/32\n\n[Peer]\nEndpoint = 2.2.2.2:51820\n"

_BOT = b"ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies"
_GONE = b"ERROR: [youtube] x: Video unavailable"


class _Proc:
    def __init__(self, rc, stderr=b""):
        self.returncode, self.stderr = rc, stderr


class _FakeTunnel:
    """Stands in for a real wireproxy process; records which configs were tried."""
    tried: list[str] = []

    def __init__(self, config):
        self.config = config
        self.proxy_url = "socks5://127.0.0.1:9"

    def __enter__(self):
        _FakeTunnel.tried.append(self.config)
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _FakeTunnel.tried = []
    monkeypatch.setattr("core.wireproxy.Tunnel", _FakeTunnel)
    yield


def _patch_configs(monkeypatch, configs):
    monkeypatch.setattr("core.wireproxy.load_configs", lambda *a, **k: configs)


def _patch_runs(monkeypatch, results):
    """results: list of _Proc returned in order."""
    seq = list(results)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return seq.pop(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


# --- config parsing --------------------------------------------------------

def test_load_configs_splits_the_bundle(tmp_path):
    p = tmp_path / "b.conf"
    p.write_text(_CFG_A + "\n" + _CFG_B)
    out = load_configs(str(p))
    assert len(out) == 2
    assert all(c.startswith("[Interface]") for c in out)
    assert "1.1.1.1" in out[0] and "2.2.2.2" in out[1]


def test_load_configs_absent_or_unset_is_empty_not_an_error(tmp_path):
    assert load_configs("") == []
    assert load_configs(str(tmp_path / "nope.conf")) == []


# --- rotation --------------------------------------------------------------

def test_no_configs_makes_one_direct_attempt(monkeypatch):
    _patch_configs(monkeypatch, [])
    calls = _patch_runs(monkeypatch, [_Proc(0)])
    Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert len(calls) == 1
    assert "--proxy" not in calls[0], "added a proxy with no configs mounted"
    assert _FakeTunnel.tried == []


def test_rotates_to_the_next_config_on_bot_block(monkeypatch):
    _patch_configs(monkeypatch, [_CFG_A, _CFG_B])
    calls = _patch_runs(monkeypatch, [_Proc(1, _BOT), _Proc(0)])
    Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert _FakeTunnel.tried == [_CFG_A, _CFG_B]
    assert all("--proxy" in c for c in calls)


def test_stops_at_the_first_success(monkeypatch):
    _patch_configs(monkeypatch, [_CFG_A, _CFG_B])
    _patch_runs(monkeypatch, [_Proc(0)])
    Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert _FakeTunnel.tried == [_CFG_A], "kept rotating after a success"


def test_non_bot_error_does_not_rotate(monkeypatch):
    """A removed video fails on every exit — rotating would burn the job timeout."""
    _patch_configs(monkeypatch, [_CFG_A, _CFG_B])
    _patch_runs(monkeypatch, [_Proc(1, _GONE)])
    with pytest.raises(RuntimeError, match="Video unavailable"):
        Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert _FakeTunnel.tried == [_CFG_A]


def test_exhausting_every_config_raises_and_names_the_remedy(monkeypatch):
    _patch_configs(monkeypatch, [_CFG_A, _CFG_B])
    _patch_runs(monkeypatch, [_Proc(1, _BOT), _Proc(1, _BOT)])
    with pytest.raises(RuntimeError, match="egress config\\(s\\) exhausted") as e:
        Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert "wireguard-configs" in str(e.value), "error should say how to fix it"
    assert _FakeTunnel.tried == [_CFG_A, _CFG_B]


def test_never_silently_falls_back_to_direct(monkeypatch):
    """Exhaustion must RAISE. Falling back to a direct connection would look like it worked
    on a dev box and be permanently bot-blocked in prod."""
    _patch_configs(monkeypatch, [_CFG_A])
    calls = _patch_runs(monkeypatch, [_Proc(1, _BOT)])
    with pytest.raises(RuntimeError):
        Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert len(calls) == 1
    assert "--proxy" in calls[0]


def test_a_tunnel_that_fails_to_start_rotates_on(monkeypatch):
    class _Broken(_FakeTunnel):
        def __enter__(self):
            _FakeTunnel.tried.append(self.config)
            raise RuntimeError("wireproxy failed to start")

    seen = {"n": 0}

    def pick(config):
        seen["n"] += 1
        return _Broken(config) if seen["n"] == 1 else _FakeTunnel(config)

    monkeypatch.setattr("core.wireproxy.Tunnel", pick)
    _patch_configs(monkeypatch, [_CFG_A, _CFG_B])
    _patch_runs(monkeypatch, [_Proc(0)])
    Y._run_ytdlp(["yt-dlp", "url"], "vid")
    assert _FakeTunnel.tried == [_CFG_A, _CFG_B]
