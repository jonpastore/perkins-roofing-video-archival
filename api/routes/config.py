"""Platform config routes — editable key/value store + secret manager integration.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements (all admin-only via manage_config):
  - GET  /config           → list editable settings rows merged with env defaults
  - PUT  /config           → upsert a single setting key/value
  - GET  /config/secrets   → list secret metadata (last-set time + who) — never the value
  - PUT  /config/secrets   → write a new Secret Manager version + record audit

NOTE: The API service account needs the following IAM roles for secret writes:
  - roles/secretmanager.secretVersionAdder  (to add new versions)
  - roles/secretmanager.viewer              (to list versions / get create_time)
Parent Terraform adds these bindings; no manual IAM needed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from app.config import settings
from app.models import PlatformConfig, SecretAudit, SessionLocal

router = APIRouter(prefix="/config", tags=["config"])

# ---------------------------------------------------------------------------
# Known-good model option lists returned to the UI for dropdowns.
# The UI shows a <select> + an "other…" free-text override for new releases.
# ---------------------------------------------------------------------------
KNOWN_LLM_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]
KNOWN_EMBED_MODELS = [
    "gemini-embedding-001",
    "text-embedding-004",
]

# ---------------------------------------------------------------------------
# Editable settings: env-var keys exposed through the settings UI.
# Maps env-var name → human label. Secrets are NOT in this list.
# ---------------------------------------------------------------------------
EDITABLE_KEYS: dict[str, str] = {
    "EMBED_BACKEND": "Embedding backend (ollama | vertex | anthropic)",
    "LLM_BACKEND": "LLM backend (ollama | vertex | anthropic)",
    "EMBED_MODEL": "Embedding model",
    "LLM_MODEL": "LLM model",
    "TRANSCRIPT_POLICY": "Transcript policy (caption_first | stt_only)",
    "ABSTAIN_THRESHOLD": "Abstain threshold (0–1 float)",
    "WP_URL": "WordPress site URL",
    "MAX_VIDEOS_PER_RUN": "Max videos per ingestion run",
    "PIPELINE_VERSION": "Pipeline version tag",
    "GRAPH_VERSION": "Graph version tag",
    "CHUNK_SIZE": "Chunk size (segments per chunk)",
}

# ---------------------------------------------------------------------------
# Allowed Secret Manager secret ids — mirrors infra/main.tf local.secret_ids
# plus the db-password that Terraform manages separately.
# ---------------------------------------------------------------------------
ALLOWED_SECRET_IDS: frozenset[str] = frozenset([
    "youtube-api-key",
    "serper-api-key",
    "resend-api-key",
    "wordpress-app-password",
    "meta-app-secret",
    "meta-system-user-token",
    "tiktok-client-secret",
    "tiktok-refresh-token",
    "google-idp-client-secret",
    "db-password",
    "internal-secret",
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_value(key: str) -> str:
    """Return the current live env value for a settings key (fallback to settings attr)."""
    return os.getenv(key, str(getattr(settings, key, "")))


def _db_overrides(db) -> dict[str, PlatformConfig]:
    return {r.key: r for r in db.query(PlatformConfig).all()}


def _secret_manager_client():
    """Return a google.cloud.secretmanager.SecretManagerServiceClient.
    Raises ImportError if the library is not installed (dev env without GCP libs)."""
    from google.cloud import secretmanager  # noqa: PLC0415
    return secretmanager.SecretManagerServiceClient()


def _gcp_project() -> str:
    """Resolve GCP project from env or application default credentials metadata."""
    proj = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
    if proj:
        return proj
    try:
        import google.auth  # noqa: PLC0415
        _, proj = google.auth.default()
        if proj:
            return proj
    except Exception:
        pass
    raise RuntimeError("Cannot determine GCP project; set GOOGLE_CLOUD_PROJECT env var")


def _secret_latest_create_time(client, project: str, secret_id: str) -> str | None:
    """Return the ISO-8601 create_time of the latest enabled secret version, or None."""
    try:
        parent = f"projects/{project}/secrets/{secret_id}"
        # List versions, filter ENABLED, pick the most recent by create_time.
        versions = list(client.list_secret_versions(
            request={"parent": parent, "filter": "state:ENABLED"},
        ))
        if not versions:
            return None
        latest = max(versions, key=lambda v: v.create_time)
        # create_time is a google.protobuf.Timestamp; convert to ISO string.
        return datetime.fromtimestamp(
            latest.create_time.timestamp(), tz=timezone.utc
        ).isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ConfigEntry(BaseModel):
    key: str
    value: str


class SecretEntry(BaseModel):
    key: str
    value: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def get_config(claims=Depends(require_role("manage_config"))):
    """Return all editable platform settings with source info + known model lists.

    Response shape:
      {
        "settings": [
          {"key": "EMBED_MODEL", "label": "...", "value": "...",
           "editable": true, "source": "db"|"env",
           "updated_at": "...", "updated_by": "..."}
        ],
        "known_models": {"llm": [...], "embed": [...]},
        "default_admins_note": "...",
        "default_admins": [...]
      }
    """
    with SessionLocal() as db:
        overrides = _db_overrides(db)

    result: list[dict[str, Any]] = []
    for key, label in EDITABLE_KEYS.items():
        if key in overrides:
            row = overrides[key]
            entry: dict[str, Any] = {
                "key": key,
                "label": label,
                "value": row.value,
                "editable": True,
                "source": "db",
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "updated_by": row.updated_by,
            }
        else:
            entry = {
                "key": key,
                "label": label,
                "value": _env_value(key),
                "editable": True,
                "source": "env",
                "updated_at": None,
                "updated_by": None,
            }
        result.append(entry)

    return {
        "settings": result,
        "known_models": {
            "llm": KNOWN_LLM_MODELS,
            "embed": KNOWN_EMBED_MODELS,
        },
        # DEFAULT_ADMINS is an env-driven config allowlist, not a user-management tool.
        # To grant/revoke admin access for individual users, go to the Users page.
        "default_admins_note": (
            "These emails receive admin access by default via env config. "
            "To manage per-user roles, use the Users page."
        ),
        "default_admins": sorted(settings.DEFAULT_ADMINS),
    }


@router.put("")
def upsert_config(entry: ConfigEntry, claims=Depends(require_role("manage_config"))):
    """Upsert a single editable platform_config row.

    Only keys in EDITABLE_KEYS are accepted. Model overrides (EMBED_MODEL, LLM_MODEL)
    are persisted immediately but take effect on next service restart since the running
    process read the env at boot — this is expected behaviour; persistence is the goal.

    Returns: {key, value, updated_at, updated_by}
    """
    if entry.key not in EDITABLE_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Key {entry.key!r} is not in the editable settings list.",
        )

    email = claims.get("email", "unknown")
    now = datetime.now(UTC).replace(tzinfo=None)

    with SessionLocal() as db:
        row = db.get(PlatformConfig, entry.key)
        if row is None:
            row = PlatformConfig(
                key=entry.key,
                value=entry.value,
                updated_at=now,
                updated_by=email,
            )
            db.add(row)
        else:
            row.value = entry.value
            row.updated_at = now
            row.updated_by = email
        db.commit()
        db.refresh(row)
        return {
            "key": row.key,
            "value": row.value,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }


@router.get("/secrets")
def get_secrets(claims=Depends(require_role("manage_config"))):
    """Return metadata for all known Secret Manager secrets.

    NEVER returns the secret value. For each secret:
      - last_set: ISO timestamp of the latest ENABLED version create_time (from GCP)
      - last_set_by: email of who last wrote it via this UI (from SecretAudit table)
      - gcp_last_set: ISO timestamp from GCP (may differ if written outside the UI)

    If GCP Secret Manager is unavailable (dev), last_set falls back to None.
    """
    with SessionLocal() as db:
        audits = {r.key: r for r in db.query(SecretAudit).all()}

    try:
        client = _secret_manager_client()
        project = _gcp_project()
        use_gcp = True
    except Exception:
        use_gcp = False
        client = None
        project = None

    results = []
    for secret_id in sorted(ALLOWED_SECRET_IDS):
        audit = audits.get(secret_id)
        gcp_last_set = (
            _secret_latest_create_time(client, project, secret_id)
            if use_gcp else None
        )
        results.append({
            "key": secret_id,
            "last_set": gcp_last_set,
            "last_set_by": audit.updated_by if audit else None,
            "ui_updated_at": audit.updated_at.isoformat() if (audit and audit.updated_at) else None,
        })

    return {"secrets": results}


@router.put("/secrets")
def upsert_secret(entry: SecretEntry, claims=Depends(require_role("manage_config"))):
    """Add a new version to a Secret Manager secret.

    The value is forwarded to Secret Manager and NEVER stored in the database.
    Only records audit metadata (who/when) in SecretAudit.

    Validates that key is in the allowed secret-id list.
    Returns: {key, last_set, last_set_by} — never the value.

    NOTE: The API service account requires:
      - roles/secretmanager.secretVersionAdder  (add versions)
      - roles/secretmanager.viewer              (list versions)
    """
    if entry.key not in ALLOWED_SECRET_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Secret {entry.key!r} is not in the allowed secret list.",
        )
    if not entry.value:
        raise HTTPException(status_code=422, detail="Secret value must not be empty.")

    email = claims.get("email", "unknown")
    now = datetime.now(UTC).replace(tzinfo=None)

    # Write new version to Secret Manager.
    try:
        client = _secret_manager_client()
        project = _gcp_project()
        secret_name = f"projects/{project}/secrets/{entry.key}"
        client.add_secret_version(
            request={
                "parent": secret_name,
                "payload": {"data": entry.value.encode("utf-8")},
            }
        )
        gcp_last_set = _secret_latest_create_time(client, project, entry.key)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Secret Manager client library not available in this environment.",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Secret Manager error: {exc}")

    # Record audit (upsert — one row per secret key).
    with SessionLocal() as db:
        audit = db.get(SecretAudit, entry.key)
        if audit is None:
            audit = SecretAudit(key=entry.key, updated_at=now, updated_by=email)
            db.add(audit)
        else:
            audit.updated_at = now
            audit.updated_by = email
        db.commit()

    return {
        "key": entry.key,
        "last_set": gcp_last_set,
        "last_set_by": email,
    }
