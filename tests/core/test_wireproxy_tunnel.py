"""Tunnel lifecycle — the process/socket half of core/wireproxy.

This code gates EVERY archive download (yt-dlp only reaches YouTube through it) and was at
41% coverage: the start, listener-wait, failure and teardown paths were all untested. A stub
binary standing in for wireproxy makes them testable without a real WireGuard peer — the stub
reads the same generated config and binds the same SOCKS port, which is exactly the contract
Tunnel depends on.
"""
import os
import socket
import sys
import textwrap

import pytest

from core.wireproxy import Tunnel

_CONFIG = "[Interface]\nPrivateKey = aaa=\nAddress = 10.2.0.2/32\n\n[Peer]\nEndpoint = 1.1.1.1:51820\n"


def _stub(tmp_path, body: str) -> str:
    """Write a python stub that behaves like `wireproxy -c <conf>` and return its path."""
    path = tmp_path / "fake_wireproxy.py"
    path.write_text(textwrap.dedent(body))
    launcher = tmp_path / "fake_wireproxy.sh"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{path}" "$@"\n')
    launcher.chmod(0o755)
    return str(launcher)


_BINDS_THE_PORT = """
    import socket, sys, time
    conf = sys.argv[sys.argv.index("-c") + 1]
    line = [x for x in open(conf) if x.startswith("BindAddress")][0]
    port = int(line.rsplit(":", 1)[1])
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(5)
    time.sleep(60)
"""


def test_tunnel_starts_exposes_socks5_and_reaps_the_process(tmp_path, monkeypatch):
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, _BINDS_THE_PORT))

    with Tunnel(_CONFIG) as tunnel:
        assert tunnel.proxy_url == f"socks5://127.0.0.1:{tunnel.port}"
        with socket.create_connection(("127.0.0.1", tunnel.port), timeout=2):
            pass  # the listener is real
        proc = tunnel._proc
        assert proc is not None and proc.poll() is None

    # Context exit must always reap — a rotation loop would otherwise leak one process per attempt.
    assert proc.poll() is not None


def test_the_generated_config_is_the_wireguard_config_plus_a_socks_section(tmp_path, monkeypatch):
    """wireproxy's config IS the WireGuard config with [Socks5] appended, and it holds a
    PRIVATE KEY — so it must never be world-readable."""
    seen: dict = {}
    body = """
    import sys
    conf = sys.argv[sys.argv.index("-c") + 1]
    print(conf)
    import socket, time
    line = [x for x in open(conf) if x.startswith("BindAddress")][0]
    port = int(line.rsplit(":", 1)[1])
    s = socket.socket(); s.bind(("127.0.0.1", port)); s.listen(5)
    time.sleep(60)
    """
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, body))

    with Tunnel(_CONFIG) as tunnel:
        conf_path = os.path.join(tunnel._dir.name, "wireproxy.ini")
        content = open(conf_path).read()
        seen["mode"] = os.stat(conf_path).st_mode & 0o777

    assert "[Interface]" in content and "PrivateKey" in content
    assert f"[Socks5]\nBindAddress = 127.0.0.1:{tunnel.port}" in content
    assert seen["mode"] == 0o600, "config carries a private key"


def test_a_binary_that_dies_raises_with_its_stderr(tmp_path, monkeypatch):
    """A dead process must fail FAST and say why, not wait out the startup timeout."""
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, """
    import sys
    sys.stderr.write("bad config: no peer\\n")
    sys.exit(2)
    """))

    with pytest.raises(RuntimeError, match="wireproxy failed to start") as err:
        with Tunnel(_CONFIG):
            pass
    assert "bad config: no peer" in str(err.value)


def test_a_binary_that_never_listens_times_out(tmp_path, monkeypatch):
    """Alive but not listening is still unusable — rotation needs the failure, not a hang."""
    monkeypatch.setattr("core.wireproxy._STARTUP_TIMEOUT_S", 1)
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, "import time\ntime.sleep(60)\n"))

    with pytest.raises(RuntimeError, match="wireproxy failed to start"):
        with Tunnel(_CONFIG):
            pass


def test_the_temp_config_is_removed_after_use(tmp_path, monkeypatch):
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, _BINDS_THE_PORT))
    with Tunnel(_CONFIG) as tunnel:
        conf_dir = tunnel._dir.name
        assert os.path.exists(conf_dir)
    assert not os.path.exists(conf_dir), "a private key must not be left on disk"


def test_each_tunnel_takes_its_own_free_port(tmp_path, monkeypatch):
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, _BINDS_THE_PORT))
    with Tunnel(_CONFIG) as a, Tunnel(_CONFIG) as b:
        assert a.port != b.port, "two concurrent rotations must not collide"


def test_a_process_that_ignores_sigterm_is_killed(tmp_path, monkeypatch):
    """terminate() then kill(): a wedged tunnel must not survive the context manager, or a
    rotation loop leaks one running process per attempt."""
    monkeypatch.setattr("core.wireproxy._TERM_TIMEOUT_S", 1)
    monkeypatch.setenv("WIREPROXY_BIN", _stub(tmp_path, """
    import signal, socket, sys, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    conf = sys.argv[sys.argv.index("-c") + 1]
    line = [x for x in open(conf) if x.startswith("BindAddress")][0]
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", int(line.rsplit(":", 1)[1]))); s.listen(5)
    time.sleep(60)
    """))

    with Tunnel(_CONFIG) as tunnel:
        proc = tunnel._proc
    assert proc.poll() is not None, "SIGTERM was ignored, so it must have been SIGKILLed"
