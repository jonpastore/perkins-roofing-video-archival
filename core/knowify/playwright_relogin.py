"""Agent Knowify reconnect: vaulted login + real localhost callback + browser.

Dashboard Log in is the human path. This is the CLI an agent can run when
`knowify-login` is vaulted. A real HTTPServer on 127.0.0.1:8765 receives the
OAuth `code` — do not intercept the loopback (that never got a code).

Cloud Run has no browser; keep-warm must not call this.
"""
from __future__ import annotations

import http.server
import logging
import secrets
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.data_source_oauth import (
    exchange_knowify,
    knowify_auth_url,
    persist_knowify_mcp,
    pkce,
    register_knowify_client,
)
from core.knowify import login_vault

log = logging.getLogger(__name__)

LOOPBACK = "http://127.0.0.1:8765/callback"
_HOST, _PORT = "127.0.0.1", 8765


def _playwright_import():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return None
    return sync_playwright


def available() -> bool:
    """True when an agent can finish login without a human (browser + vault)."""
    return _playwright_import() is not None and login_vault.configured()


def code_from_url(url: str) -> str | None:
    q = parse_qs(urlparse(url).query)
    if q.get("error"):
        return None
    vals = q.get("code") or []
    return vals[0] if vals else None


def _start_callback_server() -> tuple[dict[str, str | None], http.server.HTTPServer]:
    box: dict[str, str | None] = {"code": None, "error": None}

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = code_from_url("http://127.0.0.1" + self.path)
            if parsed:
                box["code"] = parsed
            else:
                q = parse_qs(urlparse(self.path).query)
                box["error"] = (q.get("error") or ["missing_code"])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_a):
            pass

    srv = http.server.HTTPServer((_HOST, _PORT), _H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    return box, srv


def _browser_get_code(auth_url: str, username: str, password: str, *, headless: bool) -> str:
    pw_mod = _playwright_import()
    if pw_mod is None:
        raise RuntimeError("playwright is not installed (pip install playwright && playwright install chromium)")
    box, srv = _start_callback_server()
    with pw_mod() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(auth_url, wait_until="domcontentloaded", timeout=45_000)
            page.locator("#username").wait_for(timeout=20_000)
            page.locator("#username").fill(username)
            page.locator("#password").fill(password)
            page.get_by_role("button", name="Sign In").click()
            page.get_by_role("button", name="Allow Access").click(timeout=25_000)
            for _ in range(90):
                if box.get("code") or box.get("error"):
                    break
                page.wait_for_timeout(500)
            code = box.get("code")
            if not code:
                raise RuntimeError("Knowify login did not return an OAuth code (2FA or consent blocked?)")
            return code
        finally:
            browser.close()
            srv.server_close()


def relogin(*, headless: bool = True, creds: dict[str, str] | None = None,
            persist_login: bool = True) -> dict[str, Any]:
    from core.verified_secret import update_after_verify  # noqa: PLC0415

    used = creds or login_vault.load_login()
    client_id = register_knowify_client(LOOPBACK)
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(16)
    auth_url = knowify_auth_url(
        client_id=client_id, redirect_uri=LOOPBACK, state=state, challenge=challenge,
    )
    code = _browser_get_code(auth_url, used["username"], used["password"], headless=headless)
    tokens = exchange_knowify(
        code=code, client_id=client_id, redirect_uri=LOOPBACK, verifier=verifier,
    )
    persist_knowify_mcp(tokens, client_id)
    if persist_login:
        update_after_verify(
            login_vault.SECRET_ID, used,
            verify=lambda _b: True,
            save=lambda _sid, blob: login_vault.save_login(blob["username"], blob["password"]),
        )
    log.info("knowify playwright relogin: new MCP tokens written")
    return {"ok": True}


def relogin_or_prompt(*, headless: bool = True, force_prompt: bool = False) -> dict[str, Any]:
    """Use the vault, or prompt if missing/broken. Successful logins are re-vaulted."""
    from core.verified_secret import can_prompt, prompt_username_password  # noqa: PLC0415

    if force_prompt:
        return relogin(headless=headless, creds=prompt_username_password())
    try:
        return relogin(headless=headless)
    except Exception as exc:
        if not can_prompt():
            raise
        log.warning("vaulted Knowify login failed (%s) — prompting", type(exc).__name__)
        return relogin(headless=headless, creds=prompt_username_password())
