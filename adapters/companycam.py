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


class CompanyCamNotFound(RuntimeError):
    """404 from CompanyCam.

    On a project's media sub-resource this means "this project has none" — NOT a failure.
    Measured 2026-07-29: 4 of 3,684 projects 404 on /videos while appearing in the project
    list. Counting that as an error made the sync exit 1, Cloud Run retry it to the cap, and
    those projects never get stamped media-synced — so they were re-fetched, re-failed and
    re-retried on every run, forever, with a red job each time.
    """


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
        if exc.code == 404:
            raise CompanyCamNotFound(f"CompanyCam API error 404: {raw}") from exc
        raise RuntimeError(f"CompanyCam API error {exc.code}: {raw}") from exc


# 200 pages x 50/page = 10,000 items per endpoint. Perkins' account is ~150 projects and the
# biggest project ~330 photos, so this is a runaway guard, not a real ceiling.
_MAX_PAGES = 200


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
    """Every video on a project. A 404 means the project has no video resource — empty, not an
    error (see CompanyCamNotFound). Any other HTTP failure still raises."""
    try:
        return [normalize_video(v) for v in _get_all(videos_url(project_id))]
    except CompanyCamNotFound:
        log.info("companycam: project %s has no videos resource (404)", project_id)
        return []


def ping(per_page: int = 1) -> None:
    """Cheapest authenticated call — fetch a single page of projects to prove the PAT works.

    Raises RuntimeError on a missing PAT or a non-2xx response. The health probe MUST use this,
    NOT list_projects() — the latter paginates through EVERY page via _get_all().
    """
    _get(projects_url(), {"per_page": per_page})


def _get_all(url: str, per_page: int = 100) -> list[dict[str, Any]]:
    """Fetch every page of a CompanyCam list endpoint (paginated via page/per_page).

    Stops on the first EMPTY page, never on a short one. ⚠️ A short page does NOT mean the
    last page: /v2/projects silently caps per_page at 50, so asking for 100 returns 50 — and
    the previous "stop when len(batch) < per_page" rule read that as the end and mirrored only
    the first 50 projects of the account. Measured 2026-07-29: pages 1, 2 and 3 each returned
    50 more projects, and 11 of 13 portfolio candidates were missing entirely as a result.
    That failure is invisible — every request succeeds, the job exits 0, and the mirror just
    stops early — which is why the rule is now "empty page ends it".

    _MAX_PAGES bounds the loop, and a repeated first id detects an endpoint that ignores the
    page param (which would otherwise spin forever). Both RAISE rather than returning a
    quietly-truncated list.
    """
    out: list[dict[str, Any]] = []
    page = 1
    seen_first: set[str] = set()
    while True:
        batch = _get(url, {"page": page, "per_page": per_page})
        if not isinstance(batch, list) or not batch:
            return out

        first_id = str(batch[0].get("id", ""))
        if first_id and first_id in seen_first:
            raise RuntimeError(
                f"companycam: {url} returned the same first id ({first_id}) on page {page} — "
                "the endpoint is ignoring the page param; refusing to loop or truncate."
            )
        seen_first.add(first_id)

        out.extend(batch)
        page += 1
        if page > _MAX_PAGES:
            raise RuntimeError(
                f"companycam: {url} exceeded {_MAX_PAGES} pages ({len(out)} items). Raising "
                "rather than returning a partial mirror — raise _MAX_PAGES if the account "
                "really is this large."
            )


def list_projects() -> list[dict[str, Any]]:
    return _get_all(projects_url())


def list_photos(project_id: str) -> list[dict[str, Any]]:
    """Every photo on a project. A 404 means the project has no photo resource — empty, not an
    error (see CompanyCamNotFound). Any other HTTP failure still raises."""
    try:
        return [normalize_photo(p) for p in _get_all(photos_url(project_id))]
    except CompanyCamNotFound:
        log.info("companycam: project %s has no photos resource (404)", project_id)
        return []
