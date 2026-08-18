"""WordPress Application Password: verify REST, then vault.

WP_USER stays in env. Only `wordpress-app-password` is a secret. Never vault the
wp-admin login password — that is a different field (1Password `password`).
"""
from __future__ import annotations

import base64
import logging
import os
import urllib.error
import urllib.request

from core.verified_secret import (
    prompt_username_password,
    update_text_after_verify,
)

log = logging.getLogger(__name__)

SECRET_ID = "wordpress-app-password"
_UA = "perkins-platform/1.0 (+https://perkinsroofing.net)"


def users_me_url(wp_url: str) -> str:
    return wp_url.rstrip("/") + "/wp-json/wp/v2/users/me?context=edit"


def verify_app_password(
    username: str,
    password: str,
    *,
    wp_url: str,
    urlopen=None,
) -> bool:
    user = (username or "").strip()
    pwd = (password or "").replace(" ", "")
    if not user or not pwd or not (wp_url or "").strip():
        return False
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    req = urllib.request.Request(
        users_me_url(wp_url),
        headers={"Authorization": f"Basic {token}", "User-Agent": _UA},
    )
    opener = urlopen or urllib.request.urlopen
    try:
        with opener(req, timeout=15) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 300
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def vault_after_verify(
    username: str,
    password: str,
    *,
    wp_url: str,
    urlopen=None,
    save=None,
) -> bool:
    pwd = (password or "").replace(" ", "")
    return update_text_after_verify(
        SECRET_ID,
        pwd,
        verify=lambda text: verify_app_password(username, text, wp_url=wp_url, urlopen=urlopen),
        save=save,
    )


def prompt_and_vault(*, wp_url: str, default_user: str = "", urlopen=None, save=None) -> bool:
    login = prompt_username_password(default_user=default_user or os.getenv("WP_USER", ""))
    return vault_after_verify(
        login["username"], login["password"], wp_url=wp_url, urlopen=urlopen, save=save,
    )
