"""Platform config routes — editable key/value store merged with read-only runtime info.

Export ``router`` only; mount onto the main app in api/app.py.

Role requirements:
  - GET /config   → view_status (admin)
  - PUT /config   → manage_templates (admin)
"""
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import require_role
from app.config import settings
from app.models import PlatformConfig, SessionLocal

router = APIRouter(prefix="/config", tags=["config"])


class ConfigEntry(BaseModel):
    key: str
    value: str


@router.get("")
def get_config(claims=Depends(require_role("manage_config"))):
    """Return all editable platform_config rows merged with read-only runtime info."""
    with SessionLocal() as db:
        rows = db.query(PlatformConfig).all()
        editable = {r.key: r.value for r in rows}

    runtime = {
        "embed_model": settings.EMBED_MODEL,
        "llm_model": settings.LLM_MODEL,
        "default_admins": sorted(settings.DEFAULT_ADMINS),
    }
    wp_url = os.getenv("WP_URL")
    if wp_url:
        runtime["wp_url"] = wp_url

    return {"settings": editable, "runtime": runtime}


@router.put("")
def upsert_config(entry: ConfigEntry, claims=Depends(require_role("manage_config"))):
    """Upsert a single platform_config row. Returns the stored row."""
    with SessionLocal() as db:
        row = db.get(PlatformConfig, entry.key)
        if row is None:
            row = PlatformConfig(key=entry.key, value=entry.value)
            db.add(row)
        else:
            row.value = entry.value
        db.commit()
        db.refresh(row)
        return {"key": row.key, "value": row.value}
