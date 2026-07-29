"""CompanyCam photo/video-pull adapter.

LIVE since 2026-07-28. ``COMPANYCAM_PAT`` holds an **Application Key** (bearer token tied to
the registered OAuth app "Perkins Platform (DeGenito)", Read & Write, no expiry) — not a
Personal Access Token, despite the env var and secret names, which are kept because GCP
secrets cannot be renamed. An app key is preferred over a PAT because a PAT dies with the
individual user account it belongs to.

``configured()`` lets callers (the sync job, health probes) degrade gracefully rather than
crash when the token is unset. Every network call still raises RuntimeError on a missing
token or a non-2xx response, matching adapters/resend.py.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from core.companycam.rest import UA, photos_url, projects_url, videos_url

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


def normalize_video(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw CompanyCam video into the same stable shape as normalize_photo.

    Videos are NOT photos with a different type: the payload has ``playback_url`` +
    ``thumbnail_urls`` (a dict of large/medium/small) where a photo has ``uris`` (a list of
    {type, uri}), and its timestamps are unix epoch ints. Shape verified against a live
    payload 2026-07-28.

    ``internal`` is carried through deliberately — CompanyCam lets a crew mark media
    internal-only, and anything internal must never reach a proposal or a public project
    page. Callers are expected to filter on it.
    """
    coordinates = raw.get("coordinates") or {}
    thumbs = raw.get("thumbnail_urls") or {}
    return {
        "companycam_video_id": str(raw["id"]),
        "project_id": str(raw.get("project_id")) if raw.get("project_id") is not None else None,
        "url": raw.get("playback_url"),
        "thumbnail_url": thumbs.get("large") or thumbs.get("medium") or thumbs.get("small"),
        "captured_at": raw.get("captured_at"),
        "lat": coordinates.get("lat"),
        "lon": coordinates.get("lon"),
        "status": raw.get("status"),
        "internal": bool(raw.get("internal")),
        "raw": raw,
    }


def list_videos(project_id: str) -> list[dict[str, Any]]:
    return [normalize_video(v) for v in _get_all(videos_url(project_id))]


def ping(per_page: int = 1) -> None:
    """Cheapest authenticated call — fetch a single page of projects to prove the PAT works.

    Raises RuntimeError on a missing PAT or a non-2xx response. The health probe MUST use this,
    NOT list_projects() — the latter paginates through EVERY page via _get_all().
    """
    _get(projects_url(), {"per_page": per_page})


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
