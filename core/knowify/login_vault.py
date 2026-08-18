"""Knowify website login (email + password) in Secret Manager.

Used only by the Playwright relogin path when the OAuth refresh token is dead.
Never log the password. Secret id `knowify-login`, JSON:
  {"username": "jon@perkinsroofing.net", "password": "..."}
`email` is accepted as an alias for username.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

SECRET_ID = "knowify-login"


def parse_login_blob(blob: dict) -> dict:
    user = (blob.get("username") or blob.get("email") or "").strip()
    password = blob.get("password") or ""
    if not user or not password:
        raise RuntimeError("knowify-login secret must have username/email and password")
    return {"username": user, "password": password}


def _project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""


def _client():
    from google.cloud import secretmanager  # noqa: PLC0415
    return secretmanager.SecretManagerServiceClient()


def load_login() -> dict:
    name = f"projects/{_project()}/secrets/{SECRET_ID}/versions/latest"
    version = _client().access_secret_version(name=name)
    return parse_login_blob(json.loads(version.payload.data.decode()))


def configured() -> bool:
    try:
        load_login()
        return True
    except Exception:  # noqa: BLE001
        return False


def save_login(username: str, password: str) -> None:
    parent = f"projects/{_project()}/secrets/{SECRET_ID}"
    payload = json.dumps({"username": username.strip(), "password": password}).encode()
    _client().add_secret_version(
        request={"parent": parent, "payload": {"data": payload}}
    )
    log.info("knowify-login: wrote new secret version")
