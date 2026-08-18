"""CompanyCam bearer + OAuth blob in Secret Manager.

The sync adapter still speaks a Bearer token (COMPANYCAM_PAT). Browser OAuth
writes a new :latest version so running jobs pick it up on the next process
start, and load_bearer() reads SM at call time so a reconnect works without
waiting for a deploy.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

PAT_SECRET = "companycam-pat"
OAUTH_SECRET = "companycam-tokens"


def _project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""


def _client():
    from google.cloud import secretmanager  # noqa: PLC0415
    return secretmanager.SecretManagerServiceClient()


def load_bearer() -> str:
    env = (os.getenv("COMPANYCAM_PAT") or "").strip()
    if env:
        return env
    project = _project()
    if not project:
        return ""
    try:
        name = f"projects/{project}/secrets/{PAT_SECRET}/versions/latest"
        version = _client().access_secret_version(name=name)
        return version.payload.data.decode().strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("companycam tokens: SM read failed: %s", exc)
        return ""


def save_bearer(token: str, sm_client=None) -> None:
    client = sm_client or _client()
    parent = f"projects/{_project()}/secrets/{PAT_SECRET}"
    client.add_secret_version(
        request={"parent": parent, "payload": {"data": token.encode()}}
    )
    log.info("companycam-pat: wrote new secret version")


def save_oauth(blob: dict[str, Any], sm_client=None) -> None:
    client = sm_client or _client()
    parent = f"projects/{_project()}/secrets/{OAUTH_SECRET}"
    client.add_secret_version(
        request={"parent": parent, "payload": {"data": json.dumps(blob).encode()}}
    )
    log.info("companycam-tokens: wrote new secret version")
