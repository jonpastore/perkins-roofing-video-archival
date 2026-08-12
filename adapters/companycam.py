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
import urllib.parse
import urllib.request
from typing import Any

from core.companycam.rest import (
    UA,
    photos_index_url,
    photos_url,
    projects_url,
    tags_url,
    videos_index_url,
    videos_url,
)

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


# CompanyCam tag ids that mark media for the PUBLIC project pages: "Projects" for photos,
# "ProjectsVideo" for clips. Overridable at runtime — platform_config first (the keys are in
# api/routes/config.py EDITABLE_KEYS, so they appear in Admin Config -> Platform Settings),
# then env — because deleting and recreating a tag in CompanyCam's UI mints a NEW id, which
# would otherwise need a deploy to fix while every request still returned 200.
_PROJECTS_TAG_DEFAULT = "26926152"
_PROJECTS_VIDEO_TAG_DEFAULT = "26926154"


def _tag_id(key: str, default: str) -> str:
    """platform_config wins, then env, then the id in use today. Same idiom as
    adapters/search_indexing.py::_enabled."""
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415
        with PlatformSessionLocal() as db:
            row = db.get(PlatformConfig, key)
            if row and (row.value or "").strip():
                return row.value.strip()
    except Exception:  # noqa: BLE001 — config lookup must never break a media fetch
        pass
    return os.getenv(key, default).strip()


def projects_tag_id() -> str:
    """Tag marking a PHOTO for the public project gallery."""
    return _tag_id("COMPANYCAM_PROJECTS_TAG_ID", _PROJECTS_TAG_DEFAULT)


def projects_video_tag_id() -> str:
    """Tag marking a VIDEO for the public project gallery."""
    return _tag_id("COMPANYCAM_PROJECTS_VIDEO_TAG_ID", _PROJECTS_VIDEO_TAG_DEFAULT)


def _pat() -> str:
    pat = os.getenv("COMPANYCAM_PAT")
    if not pat:
        raise RuntimeError("COMPANYCAM_PAT environment variable is not set")
    return pat


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    if params:
        # A LIST value REPEATS the key. CompanyCam's only working tag filter is the plural
        # bracketed form `?tag_ids[]=A&tag_ids[]=B`; `tag_id=`, `tags[]=` and `tag=` are
        # accepted and SILENTLY IGNORED — they return the UNFILTERED list, which is
        # indistinguishable from a filter that matched everything. Verified live 2026-08-12
        # against project 79260538: unfiltered 100 photos / 22 videos, `tag_ids[]` 9 / 2.
        # Values are quoted, KEYS are not: `tag_ids[]` must reach CompanyCam with literal
        # brackets (that exact spelling is the only one it honours), while a value can come
        # from operator-editable platform_config and must not be able to add parameters.
        pairs: list[str] = []
        for k, v in params.items():
            values = v if isinstance(v, (list, tuple)) else [v]
            pairs.extend(f"{k}={urllib.parse.quote(str(x), safe='')}" for x in values)
        url = f"{url}?{'&'.join(pairs)}"
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
    """Normalize a raw CompanyCam photo dict into a stable shape for the mirror layer.

    NO ``tags`` key is produced, deliberately. A photo payload carries none (live key list
    verified 2026-08-12 — captured_at, company_id, coordinates, created_at, creator_*,
    description, hash, id, internal, photo_url, processing_status, project_id, status,
    updated_at, uris), so the previous ``raw.get("tags")`` was always ``None`` and mirrored
    ``[]`` for every photo since 2026-07-28.

    Publish tags are owned exclusively by ``core.companycam.mirror.set_publish_tags``, fed by
    an account-wide ``?tag_ids[]=`` pass. Keeping them out of this dict is what makes the
    webhook and the sync job produce byte-identical payloads for the same photo, so
    ``content_hash`` stays a stable identity and the two writers cannot rewrite each other.
    """
    url = None
    for uri in raw.get("uris") or []:
        if uri.get("type") == "original":
            url = uri.get("uri")
            break
    coordinates = raw.get("coordinates") or {}
    out = {
        "companycam_photo_id": str(raw["id"]),
        "project_id": str(raw.get("project_id")) if raw.get("project_id") is not None else None,
        "url": url,
        "captured_at": raw.get("captured_at"),
        "lat": coordinates.get("lat"),
        "lon": coordinates.get("lon"),
        "raw": raw,
    }
    return out


def normalize_video(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw CompanyCam video into the same stable shape as normalize_photo.

    Videos are NOT photos with a different type: the payload has ``playback_url`` +
    ``thumbnail_urls`` (a dict of large/medium/small) where a photo has ``uris`` (a list of
    {type, uri}), and its timestamps are unix epoch ints. Shape verified against a live
    payload 2026-07-28.

    ``internal`` is carried through deliberately — CompanyCam lets a crew mark media
    internal-only, and anything internal must never reach a proposal or a public project
    page. Callers are expected to filter on it.

    No ``tags`` key, for the same reason as ``normalize_photo``.
    """
    coordinates = raw.get("coordinates") or {}
    thumbs = raw.get("thumbnail_urls") or {}
    out = {
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
    return out


def list_videos(project_id: str, tag_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Every video on a project, or only those carrying one of ``tag_ids``.

    A 404 means the project has no video resource — empty, not an error (see
    CompanyCamNotFound). Any other HTTP failure still raises."""
    try:
        return [normalize_video(v) for v in _get_all(videos_url(project_id), tag_ids=tag_ids)]
    except CompanyCamNotFound:
        log.info("companycam: project %s has no videos resource (404)", project_id)
        return []


def ping(per_page: int = 1) -> None:
    """Cheapest authenticated call — fetch a single page of projects to prove the PAT works.

    Raises RuntimeError on a missing PAT or a non-2xx response. The health probe MUST use this,
    NOT list_projects() — the latter paginates through EVERY page via _get_all().
    """
    _get(projects_url(), {"per_page": per_page})


def _get_all(url: str, per_page: int = 100,
             tag_ids: list[str] | None = None) -> list[dict[str, Any]]:
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
    extra = {"tag_ids[]": [str(t) for t in tag_ids]} if tag_ids else {}
    while True:
        batch = _get(url, {"page": page, "per_page": per_page, **extra})
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


def list_tagged_photos(tag_ids: list[str]) -> list[dict[str, Any]]:
    """Every photo ON THE ACCOUNT carrying one of ``tag_ids``.

    Account-wide on purpose. The per-project fetch below is gated by the sync job's
    incremental `needs_media` check, which keys off the PROJECT's CompanyCam `updated_at` —
    and a finished roof's timestamp never moves again, so a per-project tag pass could never
    reach the completed jobs the portfolio is built from, nor notice a photo tagged today.
    This endpoint is not gated by anything: measured 2026-08-12, the whole account returns
    42 tagged photos and 10 tagged videos, so the entire publish-tag state costs ~4 requests.
    """
    return [normalize_photo(p) for p in _get_all(photos_index_url(), tag_ids=tag_ids)]


def list_tagged_videos(tag_ids: list[str]) -> list[dict[str, Any]]:
    """Every video ON THE ACCOUNT carrying one of ``tag_ids``. See list_tagged_photos."""
    return [normalize_video(v) for v in _get_all(videos_index_url(), tag_ids=tag_ids)]


def known_tag_ids() -> set[str]:
    """Every media tag id on the account.

    ⚠️ THE REASON THIS EXISTS: an UNRECOGNISED tag id does not return zero results, it
    returns the UNFILTERED list. Measured live 2026-08-12 on project 79260538 —
    `tag_ids[]=26926152` returns 9 photos, while `tag_ids[]=1`, `tag_ids[]=999999999` and
    `tag_ids[]=abc` each return all of them. So the filter fails OPEN: if a tag is deleted
    and recreated in CompanyCam's UI (which mints a new id) and the config still holds the
    old one, every request still succeeds and the "publishable" set silently becomes the
    whole project — tear-off frames, damage photos, and the GPS burned into their pixels.

    Callers validate the configured ids against this BEFORE filtering, and decline to write
    tags at all when one is missing.
    """
    return {str(t.get("id")) for t in _get_all(tags_url()) if t.get("id") is not None}


def list_photos(project_id: str, tag_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Every photo on a project, or only those carrying one of ``tag_ids``.

    A 404 means the project has no photo resource — empty, not an error (see
    CompanyCamNotFound). Any other HTTP failure still raises."""
    try:
        return [normalize_photo(p) for p in _get_all(photos_url(project_id), tag_ids=tag_ids)]
    except CompanyCamNotFound:
        log.info("companycam: project %s has no photos resource (404)", project_id)
        return []
