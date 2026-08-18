"""CompanyCam Application Key in Secret Manager (env name COMPANYCAM_PAT is historical).

load_bearer() reads SM at call time so a key rotation is picked up without a deploy.
There is no user OAuth flow — persist_companycam / save_oauth were removed.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

PAT_SECRET = "companycam-pat"


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
