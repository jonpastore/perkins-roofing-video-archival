"""Mint a new Knowify MCP OAuth pair via Playwright when refresh is dead.

Cloud Run does not ship a browser. This runs on a machine with Playwright
Chromium (cerberus / a laptop): `playwright install chromium`.

Flow: DCR client with a loopback redirect → headless login → intercept `code`
→ token exchange → persist_knowify_mcp. Never logs the password or tokens.
"""
from __future__ import annotations

import logging
import secrets
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


def _playwright_import():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return None
    return sync_playwright


def available() -> bool:
    from core.verified_secret import can_prompt  # noqa: PLC0415
    return _playwright_import() is not None and (login_vault.configured() or can_prompt())


def code_from_url(url: str) -> str | None:
    q = parse_qs(urlparse(url).query)
    if q.get("error"):
        return None
    vals = q.get("code") or []
    return vals[0] if vals else None


def _browser_get_code(auth_url: str, username: str, password: str, *, headless: bool) -> str:
    pw_mod = _playwright_import()
    if pw_mod is None:
        raise RuntimeError("playwright is not installed (pip install playwright && playwright install chromium)")
    with pw_mod() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        captured: dict[str, str] = {}

        def _capture(route):
            captured["url"] = route.request.url
            route.fulfill(status=200, content_type="text/html", body="<html>ok</html>")

        try:
            page.route("http://127.0.0.1:8765/**", _capture)
            page.goto(auth_url, wait_until="domcontentloaded", timeout=45_000)
            page.locator("#username").wait_for(timeout=20_000)
            page.locator("#username").fill(username)
            page.locator("#password").fill(password)
            page.get_by_role("button", name="Sign In").click()
            page.get_by_role("button", name="Allow Access").click(timeout=25_000)
            for _ in range(90):
                if captured.get("url") or "code=" in page.url or "error=" in page.url:
                    break
                page.wait_for_timeout(500)
            code = code_from_url(captured.get("url") or page.url)
            if not code:
                raise RuntimeError("Knowify login did not return an OAuth code (2FA or consent blocked?)")
            return code
        finally:
            browser.close()


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
