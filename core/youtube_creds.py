"""YouTube API key + reply OAuth: verify, then vault.

API key (`youtube-api-key`) is read-only Data API. Reply posting uses a
refresh token (`youtube-oauth-refresh-token`) that must authorize the Perkins
channel. Google login JSON (`youtube-login`) is only for Playwright relogin.
Never log the password or tokens.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from core.verified_secret import update_after_verify, update_text_after_verify

log = logging.getLogger(__name__)

CHANNEL_ID = "UChJZpBYXOuR0j1EHJugv5hg"
API_KEY_SECRET = "youtube-api-key"
REFRESH_SECRET = "youtube-oauth-refresh-token"
LOGIN_SECRET = "youtube-login"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_MINE = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
_UA = "perkins-platform/1.0 (+https://perkinsroofing.net)"


def _project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""


def _client():
    from google.cloud import secretmanager  # noqa: PLC0415
    return secretmanager.SecretManagerServiceClient()


def verify_api_key(key: str, *, urlopen=None) -> bool:
    key = (key or "").strip()
    if not key:
        return False
    url = (
        "https://www.googleapis.com/youtube/v3/channels?"
        + urllib.parse.urlencode({"part": "id", "id": CHANNEL_ID, "key": key})
    )
    opener = urlopen or urllib.request.urlopen
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with opener(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("items") or []
        return bool(items and items[0].get("id") == CHANNEL_ID)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def posting_channel(
    refresh: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    urlopen=None,
) -> dict | None:
    cid = client_id or os.getenv("OAUTH_CLIENT_ID", "")
    secret = client_secret or os.getenv("OAUTH_CLIENT_SECRET", "")
    refresh = (refresh or "").strip()
    if not (refresh and cid and secret):
        return None
    opener = urlopen or urllib.request.urlopen
    try:
        body = urllib.parse.urlencode({
            "client_id": cid,
            "client_secret": secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }).encode()
        tok_req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        with opener(tok_req, timeout=20) as resp:
            access = json.loads(resp.read().decode()).get("access_token") or ""
        if not access:
            return None
        ch_req = urllib.request.Request(
            CHANNELS_MINE, headers={"Authorization": f"Bearer {access}", "User-Agent": _UA},
        )
        with opener(ch_req, timeout=20) as resp:
            items = json.loads(resp.read().decode()).get("items") or []
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    if not items:
        return None
    ch = items[0]
    return {"id": ch.get("id"), "title": (ch.get("snippet") or {}).get("title", "")}


def verify_refresh_token(
    refresh: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    urlopen=None,
) -> bool:
    ch = posting_channel(
        refresh, client_id=client_id, client_secret=client_secret, urlopen=urlopen,
    )
    return bool(ch and ch.get("id") == CHANNEL_ID)


def vault_api_key_after_verify(key: str, *, urlopen=None, save=None) -> bool:
    return update_text_after_verify(
        API_KEY_SECRET,
        (key or "").strip(),
        verify=lambda text: verify_api_key(text, urlopen=urlopen),
        save=save,
    )


def vault_refresh_after_verify(
    refresh: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    urlopen=None,
    save=None,
) -> bool:
    ok = update_text_after_verify(
        REFRESH_SECRET,
        (refresh or "").strip(),
        verify=lambda text: verify_refresh_token(
            text, client_id=client_id, client_secret=client_secret, urlopen=urlopen,
        ),
        save=save,
    )
    from core.connection_status import mark_healthy  # noqa: PLC0415
    mark_healthy("youtube_reply")
    return ok


def prompt_and_vault_api_key(*, urlopen=None, save=None) -> bool:
    key = getpass.getpass("YouTube API key: ").strip()
    return vault_api_key_after_verify(key, urlopen=urlopen, save=save)


def parse_login_blob(blob: dict) -> dict:
    user = (blob.get("username") or blob.get("email") or "").strip()
    password = blob.get("password") or ""
    if not user or not password:
        raise RuntimeError("youtube-login secret must have username/email and password")
    return {"username": user, "password": password}


def load_refresh_token() -> str:
    """GSM :latest, then env. A just-vaulted token must win over a stale mount."""
    try:
        name = f"projects/{_project()}/secrets/{REFRESH_SECRET}/versions/latest"
        version = _client().access_secret_version(name=name)
        text = (version.payload.data or b"").decode().strip()
        if text:
            return text
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN") or "").strip()


def load_login() -> dict:
    name = f"projects/{_project()}/secrets/{LOGIN_SECRET}/versions/latest"
    version = _client().access_secret_version(name=name)
    return parse_login_blob(json.loads(version.payload.data.decode()))


def configured() -> bool:
    try:
        load_login()
        return True
    except Exception:  # noqa: BLE001
        return False


def save_login(username: str, password: str) -> None:
    update_after_verify(
        LOGIN_SECRET,
        {"username": username.strip(), "password": password},
        verify=lambda _b: True,
        save=lambda _sid, blob: _write_login(blob),
    )


def _write_login(blob: dict) -> None:
    parent = f"projects/{_project()}/secrets/{LOGIN_SECRET}"
    payload = json.dumps({
        "username": blob["username"], "password": blob["password"],
    }).encode()
    _client().add_secret_version(request={"parent": parent, "payload": {"data": payload}})
    log.info("youtube-login: wrote new secret version")
