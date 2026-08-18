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
import time
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
    from core.companycam.tokens import load_bearer  # noqa: PLC0415
    return bool(load_bearer())


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
    except Exception as exc:  # noqa: BLE001 — config lookup must never break a media fetch
        # LOG IT. Falling through is right (a config blip must not break a media fetch), but doing
        # it silently is not: the override exists precisely because recreating a tag in CompanyCam
        # mints a NEW id, so the hard-coded default below can be stale. When that happens the sync
        # filters on a tag that matches nothing, CompanyCam returns 200 with an empty set, the job
        # logs its usual success line, and the public gallery quietly stops updating.
        log.warning(
            "companycam: %s lookup failed, falling back to env/default %r — if the tag was "
            "recreated in CompanyCam this id is stale and the sync will match nothing: %s",
            key, default, exc,
        )
    return os.getenv(key, default).strip()


def projects_tag_id() -> str:
    """Tag marking a PHOTO for the public project gallery."""
    return _tag_id("COMPANYCAM_PROJECTS_TAG_ID", _PROJECTS_TAG_DEFAULT)


def projects_video_tag_id() -> str:
    """Tag marking a VIDEO for the public project gallery."""
    return _tag_id("COMPANYCAM_PROJECTS_VIDEO_TAG_ID", _PROJECTS_VIDEO_TAG_DEFAULT)


def _pat() -> str:
    from core.companycam.tokens import load_bearer  # noqa: PLC0415
    pat = load_bearer()
    if not pat:
        raise RuntimeError("COMPANYCAM_PAT is not set (env or companycam-pat secret)")
    return pat


_GET_ATTEMPTS = 3


def _query_string(params: dict[str, Any]) -> str:
    # A LIST value REPEATS the key. CompanyCam's working tag filter is
    # `?tag_ids[]=A&tag_ids[]=B` (legacy) and `tag_ids=` (modern). Both are
    # accepted on public_api/v1. `tag_id=` 400s. Values are quoted, KEYS are
    # not: `tag_ids[]` must keep literal brackets. Operator-editable tag ids
    # must not be able to add parameters.
    pairs: list[str] = []
    for k, v in params.items():
        if v is None:
            continue
        values = v if isinstance(v, (list, tuple)) else [v]
        pairs.extend(f"{k}={urllib.parse.quote(str(x), safe='')}" for x in values)
    return "&".join(pairs)


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    if params:
        url = f"{url}?{_query_string(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_pat()}",
            "User-Agent": UA,
            "Accept": "application/json",
        },
    )
    last_err: Exception | None = None
    for attempt in range(1, _GET_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            if exc.code == 404:
                raise CompanyCamNotFound(f"CompanyCam API error 404: {raw}") from exc
            if exc.code == 429 and attempt < _GET_ATTEMPTS:
                last_err = RuntimeError(f"CompanyCam API error 429: {raw}")
                log.warning("companycam GET attempt %d/%d HTTP 429", attempt, _GET_ATTEMPTS)
                time.sleep(0.4 * attempt)
                continue
            raise RuntimeError(f"CompanyCam API error {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            last_err = exc
            log.warning("companycam GET attempt %d/%d URLError %s", attempt, _GET_ATTEMPTS, exc)
            if attempt < _GET_ATTEMPTS:
                time.sleep(0.4 * attempt)
    raise RuntimeError(f"CompanyCam network error after {_GET_ATTEMPTS} attempts: {last_err}") from last_err


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
    _get(projects_url(), {"limit": per_page})


def _unwrap_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Split a modern {data, meta} page or a legacy raw list into (rows, next_cursor)."""
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        raise RuntimeError(f"companycam: unexpected payload type {type(payload).__name__}")
    errors = payload.get("errors") or []
    if errors:
        raise RuntimeError(f"CompanyCam API error: {errors}")
    data = payload.get("data")
    if data is None:
        return [], None
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        raise RuntimeError(f"companycam: unexpected data type {type(data).__name__}")
    meta = payload.get("meta") or {}
    cursor = meta.get("next_cursor") if meta.get("has_next") else None
    return rows, cursor


def _get_all(url: str, per_page: int = 100,
             tag_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch every page of a CompanyCam list endpoint.

    Modern public_api/v1 paginates with ``limit`` + ``after`` (cursor). A short page is
    not the end — only ``has_next=false`` or an empty ``data`` list is. Measured 2026-08-18:
    ``per_page`` 400s on the modern host; ``limit`` + ``after`` is the accepted pair.

    ``tag_ids[]`` is still the filter spelling we send (modern also accepts ``tag_ids``).
    """
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    seen_first: set[str] = set()
    extra = {"tag_ids[]": [str(t) for t in tag_ids]} if tag_ids else {}
    while True:
        params: dict[str, Any] = {"limit": per_page, **extra}
        if cursor:
            params["after"] = cursor
        batch, next_cursor = _unwrap_page(_get(url, params))
        if not batch:
            return out

        first_id = str(batch[0].get("id", ""))
        if first_id and first_id in seen_first:
            raise RuntimeError(
                f"companycam: {url} returned the same first id ({first_id}) on a later page — "
                "the endpoint is ignoring the cursor; refusing to loop or truncate."
            )
        seen_first.add(first_id)
        out.extend(batch)
        pages += 1
        if not next_cursor:
            return out
        cursor = next_cursor
        if pages >= _MAX_PAGES:
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
