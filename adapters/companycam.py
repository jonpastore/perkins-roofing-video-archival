"""CompanyCam photo-pull adapter.

Ahead-of-account scaffold: PAT not issued yet. ``configured()`` lets callers (the
sync job, health probes) degrade gracefully instead of crashing when the PAT is
unset. Every network call still raises RuntimeError on a missing PAT or a non-2xx
response, matching adapters/resend.py.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from core.companycam.rest import UA, photos_url, projects_url

log = logging.getLogger(__name__)


def configured() -> bool:
    return bool(os.getenv("COMPANYCAM_PAT"))


def _pat() -> str:
    pat = os.getenv("COMPANYCAM_PAT")
    if not pat:
        raise RuntimeError("COMPANYCAM_PAT environment variable is not set")
    return pat


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_pat()}",
            # Explicit UA — same Cloudflare-1010 gotcha as adapters/resend.py.
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        raise RuntimeError(f"CompanyCam API error {exc.code}: {raw}") from exc


def normalize_photo(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw CompanyCam photo dict into a stable shape for the mirror layer."""
    url = None
    for uri in raw.get("uris") or []:
        if uri.get("type") == "original":
            url = uri.get("uri")
            break
    coordinates = raw.get("coordinates") or {}
    return {
        "companycam_photo_id": str(raw["id"]),
        "project_id": str(raw.get("project_id")) if raw.get("project_id") is not None else None,
        "url": url,
        "captured_at": raw.get("captured_at"),
        "lat": coordinates.get("lat"),
        "lon": coordinates.get("lon"),
        "tags": raw.get("tags") or [],
        "raw": raw,
    }


def _get_all(url: str, per_page: int = 100) -> list[dict[str, Any]]:
    """Fetch every page of a CompanyCam list endpoint (paginated via page/per_page).

    Stops on the first short page. Without this, a project with >per_page photos silently
    drops the overflow — roofing projects routinely exceed 100 photos.
    """
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _get(url, {"page": page, "per_page": per_page})
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out


def list_projects() -> list[dict[str, Any]]:
    return _get_all(projects_url())


def list_photos(project_id: str) -> list[dict[str, Any]]:
    return [normalize_photo(p) for p in _get_all(photos_url(project_id))]
