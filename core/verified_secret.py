"""Prompt → verify → vault. Never store a login that did not work.

When a credential is broken and we ask a human for username/password, write
Secret Manager only after the verify callback succeeds. Failed attempts stay
out of :latest so a typo cannot overwrite a still-useful previous version.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Login = dict[str, str]
VerifyFn = Callable[[Login], bool]
SaveFn = Callable[[str, Login], None]


def normalize_login(username: str, password: str) -> Login:
    user = (username or "").strip()
    if not user or not password:
        raise RuntimeError("username and password are required")
    return {"username": user, "password": password}


def prompt_username_password(*, default_user: str = "") -> Login:
    """Interactive stdin prompt. Do not call this from a non-TTY agent session
    unless the operator is at the keyboard (`python -m jobs.knowify_relogin --prompt`)."""
    hint = f" [{default_user}]" if default_user else ""
    raw = input(f"Username{hint}: ").strip()
    user = raw or default_user
    password = getpass.getpass("Password: ")
    return normalize_login(user, password)


def can_prompt() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


def prompt_and_update(
    secret_id: str,
    *,
    verify: VerifyFn,
    default_user: str = "",
    save: SaveFn | None = None,
) -> bool:
    """Prompt on a TTY, verify, then vault. The one operator path for a broken login."""
    return update_after_verify(
        secret_id,
        prompt_username_password(default_user=default_user),
        verify=verify,
        save=save,
    )


def update_after_verify(
    secret_id: str,
    blob: Login,
    *,
    verify: VerifyFn,
    save: SaveFn | None = None,
) -> bool:
    """Run verify(blob). On success, save. On failure, do not write and raise."""
    if not verify(blob):
        raise RuntimeError(f"{secret_id}: credentials did not verify — secret not updated")
    writer = save or save_json_secret
    writer(secret_id, blob)
    log.info("%s: verified login, wrote new secret version", secret_id)
    return True


def save_json_secret(secret_id: str, blob: dict[str, Any]) -> None:
    from google.cloud import secretmanager  # noqa: PLC0415

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""
    parent = f"projects/{project}/secrets/{secret_id}"
    client = secretmanager.SecretManagerServiceClient()
    client.add_secret_version(
        request={"parent": parent, "payload": {"data": json.dumps(blob).encode()}}
    )


def save_text_secret(secret_id: str, text: str) -> None:
    from google.cloud import secretmanager  # noqa: PLC0415

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or ""
    parent = f"projects/{project}/secrets/{secret_id}"
    client = secretmanager.SecretManagerServiceClient()
    client.add_secret_version(
        request={"parent": parent, "payload": {"data": text.encode()}}
    )


def update_text_after_verify(
    secret_id: str,
    text: str,
    *,
    verify: Callable[[str], bool],
    save: Callable[[str, str], None] | None = None,
) -> bool:
    if not verify(text):
        raise RuntimeError(f"{secret_id}: credentials did not verify — secret not updated")
    writer = save or save_text_secret
    writer(secret_id, text)
    log.info("%s: verified, wrote new secret version", secret_id)
    return True
