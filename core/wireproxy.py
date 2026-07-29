"""Userspace WireGuard egress for yt-dlp (pure-ish: process + socket, no DB/network fetch).

WHY THIS EXISTS
YouTube bot-blocks datacenter egress. Every download from Cloud Run failed with "Sign in to
confirm you're not a bot" (archive-52md7 / -ksm4d: 15/15), while the same videos pull fine from
a residential IP. Cookies do NOT help — measured 2026-07-29 with the channel-owner jar verified
loaded ("using cookie jar ... 6791 bytes") and still 15/15 blocked. It is the IP, not the identity.

WHY USERSPACE
A kernel WireGuard tunnel needs a TUN device and NET_ADMIN, which Cloud Run containers do not
get. wireproxy implements WireGuard in userspace (netstack) and exposes a SOCKS5 listener, so it
needs no privileges at all — verified in a container run with neither --cap-add NET_ADMIN nor
--device /dev/net/tun. yt-dlp then just takes --proxy socks5://127.0.0.1:PORT.

WHY ROTATION
A Proton exit is STICKY per server config, not per connection: reconnecting the same config five
times gave the same blocked exit five times. Different server configs land in different ranges,
and blocking is per-range. Measured 2026-07-29:

    185.159.158.164 -> 149.102.228.71   blocked 5/5
    185.159.158.153 -> 79.127.160.162   ok 3/3
    185.159.158.81  -> 79.127.136.197   ok 3/3

So rotating configs is the strategy, not retrying one config back-to-back.

BUT A BLOCK IS NOT PERMANENT — corrected 2026-07-29 from execution archive-trl5x, where BOTH
configs downloaded successfully minutes after being bot-blocked (3 successes in 26 attempts).
The block behaves like per-IP rate limiting that decays, not a fixed range ban, so
adapters/yt_dlp walks the bundle EGRESS_PASSES (default 2) times instead of once.

Two configs at that hit rate is still thin. Ranges do get blocked over time, so the bundle is
expected to need refreshing with more/newer Proton servers — that is maintenance, not a bug,
which is why exhaustion raises loudly instead of degrading to a direct connection.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import tempfile
import time

log = logging.getLogger(__name__)

# One secret holds every config, concatenated. Each block starts at its own [Interface].
_BLOCK_MARKER = "[Interface]"
_BIND_HOST = "127.0.0.1"
_STARTUP_TIMEOUT_S = 25


def load_configs(path: str | None = None) -> list[str]:
    """Split the mounted bundle into individual WireGuard configs.

    Returns [] when unset/absent/empty so callers degrade to a direct connection rather than
    crash — a missing bundle must not take down a job that might not need the proxy at all.
    """
    path = path or os.getenv("WIREGUARD_CONFIGS_FILE") or ""
    if not path:
        return []
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as exc:
        log.warning("wireproxy: WIREGUARD_CONFIGS_FILE=%s unreadable (%s)", path, exc)
        return []
    blocks = [b.strip() for b in raw.split(_BLOCK_MARKER) if b.strip()]
    return [f"{_BLOCK_MARKER}\n{b}" for b in blocks]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((_BIND_HOST, 0))
        return s.getsockname()[1]


class Tunnel:
    """A running wireproxy process exposing SOCKS5 on 127.0.0.1.

    Use as a context manager; the process is always reaped, including on exception, so a
    rotation loop cannot leak one process per attempt.
    """

    def __init__(self, config: str):
        self._config = config
        self.port = _free_port()
        self._proc: subprocess.Popen | None = None
        self._dir: tempfile.TemporaryDirectory | None = None

    @property
    def proxy_url(self) -> str:
        return f"socks5://{_BIND_HOST}:{self.port}"

    def __enter__(self) -> "Tunnel":
        self._dir = tempfile.TemporaryDirectory()
        # wireproxy's config IS the WireGuard config plus a [Socks5] section.
        conf = os.path.join(self._dir.name, "wireproxy.ini")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write(self._config.rstrip() + f"\n\n[Socks5]\nBindAddress = {_BIND_HOST}:{self.port}\n")
        os.chmod(conf, 0o600)  # contains a private key

        self._proc = subprocess.Popen(  # noqa: S603
            [os.getenv("WIREPROXY_BIN", "wireproxy"), "-c", conf],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if not self._wait_for_listener():
            err = ""
            if self._proc.poll() is not None and self._proc.stderr:
                err = self._proc.stderr.read().decode("utf-8", "replace")[-400:]
            self.__exit__(None, None, None)
            raise RuntimeError(f"wireproxy failed to start on port {self.port}: {err or 'timeout'}")
        return self

    def _wait_for_listener(self) -> bool:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc and self._proc.poll() is not None:
                return False  # died — no point waiting out the timeout
            try:
                with socket.create_connection((_BIND_HOST, self.port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.4)
        return False

    def __exit__(self, *_exc) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        if self._proc and self._proc.stderr:
            self._proc.stderr.close()
        if self._dir:
            self._dir.cleanup()
        self._proc, self._dir = None, None
