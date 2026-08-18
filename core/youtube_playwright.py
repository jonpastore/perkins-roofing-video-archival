"""Mint a YouTube reply refresh token via Playwright when the vaulted one is dead.

Cloud Run does not ship a browser. Run on cerberus / a laptop:
`playwright install chromium`.

Flow: Google OAuth (offline + consent) → loopback `code` → token exchange →
verify channels?mine=true is the Perkins channel → vault refresh + login.
Google 2FA / "browser not secure" fails headless — use `--headed`.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.verified_secret import update_after_verify
from core.youtube_creds import (
    configured,
    load_login,
    vault_refresh_after_verify,
)

log = logging.getLogger(__name__)

LOOPBACK = "http://localhost:8765/"
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _playwright_import():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return None
    return sync_playwright


def available() -> bool:
    from core.verified_secret import can_prompt  # noqa: PLC0415
    return _playwright_import() is not None and (configured() or can_prompt())


def code_from_url(url: str) -> str | None:
    q = parse_qs(urlparse(url).query)
    if q.get("error"):
        return None
    vals = q.get("code") or []
    return vals[0] if vals else None


def auth_url(client_id: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": LOOPBACK,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })


def _fill_google_login(page, username: str, password: str) -> None:
    page.locator("#identifierId").wait_for(timeout=20_000)
    page.locator("#identifierId").fill(username)
    page.locator("#identifierNext").click()
    page.locator("input[name='Passwd']").wait_for(timeout=20_000)
    page.locator("input[name='Passwd']").fill(password)
    page.locator("#passwordNext").click()


def _browser_get_code(auth: str, username: str, password: str, *, headless: bool) -> str:
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
            page.route("http://localhost:8765/**", _capture)
            page.goto(auth, wait_until="domcontentloaded", timeout=45_000)
            _fill_google_login(page, username, password)
            page.get_by_role("button", name="Allow").click(timeout=25_000)
            for _ in range(90):
                if captured.get("url") or "code=" in page.url or "error=" in page.url:
                    break
                page.wait_for_timeout(500)
            code = code_from_url(captured.get("url") or page.url)
            if not code:
                raise RuntimeError("YouTube login did not return an OAuth code (2FA or consent blocked?)")
            return code
        finally:
            browser.close()


def exchange_code(*, code: str, client_id: str, client_secret: str, urlopen=None) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": LOOPBACK,
        "grant_type": "authorization_code",
    }).encode()
    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with opener(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def relogin(*, headless: bool = True, creds: dict[str, str] | None = None,
            persist_login: bool = True) -> dict[str, Any]:
    used = creds or load_login()
    client_id = os.getenv("OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError("OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET are required")
    code = _browser_get_code(auth_url(client_id), used["username"], used["password"], headless=headless)
    tokens = exchange_code(code=code, client_id=client_id, client_secret=client_secret)
    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        raise RuntimeError("YouTube did not return a refresh token — secret not updated")
    vault_refresh_after_verify(refresh)
    if persist_login:
        update_after_verify(
            "youtube-login", used,
            verify=lambda _b: True,
            save=lambda _sid, blob: _save_login(blob),
        )
    log.info("youtube playwright relogin: refresh token written")
    return {"ok": True}


def _save_login(blob: dict) -> None:
    from core.youtube_creds import save_login  # noqa: PLC0415
    save_login(blob["username"], blob["password"])


def relogin_or_prompt(*, headless: bool = True, force_prompt: bool = False) -> dict[str, Any]:
    from core.verified_secret import can_prompt, prompt_username_password  # noqa: PLC0415

    if force_prompt:
        return relogin(headless=headless, creds=prompt_username_password())
    try:
        return relogin(headless=headless)
    except Exception as exc:
        if not can_prompt():
            raise
        log.warning("vaulted YouTube login failed (%s) — prompting", type(exc).__name__)
        return relogin(headless=headless, creds=prompt_username_password())
