"""Portfolio media curation + project-page SEO/AIO scoring (pure — no I/O).

Two jobs, both of which previously had no home:

1. CURATION. Decide which mirrored CompanyCam media may appear on a project page, in what
   order, with what alt text. The rules are not cosmetic:
     * internal media must NEVER be published (CompanyCam lets a crew flag it),
     * media is only publishable when the client has cleared that MEDIUM (photos vs video are
       separate permissions),
     * every image needs its OWN alt text — the nine live project pages carry four images
       sharing one alt string, which is the defect Wendy's audit found.

2. SCORING. Score the resulting page the way articles are scored, reusing core.seo rather than
   inventing a second rubric: score_article() for the 11 weighted SEO checks and aio_signals()
   for the advisory AI-optimization ones, plus the project-specific checks those cannot know
   about (alt uniqueness, service/location links, whether the gallery is actually cleared).

The caller supplies already-fetched media rows; nothing here touches the DB or the network.
"""
from __future__ import annotations

import html
import re
from typing import Any, Iterable, Optional

from core.seo import aio_signals, check_tier, score_article

# A CompanyCam project URL as recorded in the project doc:
# https://app.companycam.com/projects/60249175/photos
_CC_PROJECT_RE = re.compile(r"/projects/(\d+)")

# Internal links we expect a project page to carry — the audit found 0/9 with either.
_SERVICE_LINK_RE = re.compile(r'href="[^"]*/(services?|roofing|re-?roof)[^"]*"', re.I)
_LOCATION_LINK_RE = re.compile(r'href="[^"]*/(south-florida-service-areas|locations?)/[^"]*"', re.I)

MIN_GALLERY_IMAGES = 4


def companycam_project_id(url: str | None) -> str | None:
    """Extract the CompanyCam project id from a project URL.

    The candidate records already carry the URL, so the project link needs no separate mapping
    table. Returns None for empty/!matching input rather than raising — several candidates have
    no CompanyCam project at all.
    """
    if not url:
        return None
    m = _CC_PROJECT_RE.search(url)
    return m.group(1) if m else None


def publishable_media(
    photos: Iterable[dict],
    videos: Iterable[dict],
    *,
    permission_photos: bool,
    permission_video: bool,
) -> dict[str, list[dict]]:
    """Filter mirrored media down to what may legally and safely be published.

    Video carries CompanyCam's ``internal`` flag; anything internal is dropped regardless of
    permission. Photos and video are gated on their OWN permission — a client who cleared
    photos has not thereby cleared video.
    """
    ok_photos = list(photos) if permission_photos else []
    ok_videos = [v for v in videos if not v.get("internal", True)] if permission_video else []
    return {"photos": ok_photos, "videos": ok_videos}


def validate_selection(
    selections: Iterable[dict],
    available: dict[str, list[dict]],
) -> list[str]:
    """Return human-readable problems with a proposed selection; empty list == valid.

    Rejects (rather than silently dropping) a selection that names media which is not
    publishable — a silent drop is how an internal clip ends up "selected" in the UI and absent
    from the page, or worse, the reverse.
    """
    problems: list[str] = []
    by_kind = {
        "photo": {str(p.get("companycam_photo_id")) for p in available.get("photos", [])},
        "video": {str(v.get("companycam_video_id")) for v in available.get("videos", [])},
    }
    seen_ids: set[tuple[str, str]] = set()
    alts: list[str] = []

    for i, sel in enumerate(selections):
        kind = sel.get("kind")
        sid = str(sel.get("id", ""))
        if kind not in ("photo", "video"):
            problems.append(f"item {i}: kind must be 'photo' or 'video', got {kind!r}")
            continue
        if not sid:
            problems.append(f"item {i}: missing id")
            continue
        if sid not in by_kind[kind]:
            problems.append(
                f"item {i}: {kind} {sid} is not available for this project "
                "(unmirrored, internal, or not permitted)"
            )
        if (kind, sid) in seen_ids:
            problems.append(f"item {i}: {kind} {sid} selected twice")
        seen_ids.add((kind, sid))
        if kind == "photo":
            alts.append((sel.get("alt") or "").strip().lower())

    missing_alt = sum(1 for a in alts if not a)
    if missing_alt:
        problems.append(f"{missing_alt} image(s) have no alt text")
    # Duplicate alt text is the live-site defect, so it is an error here, not a warning.
    duped = {a for a in alts if a and alts.count(a) > 1}
    if duped:
        problems.append(
            f"{len(duped)} alt string(s) reused across images — each image needs its own: "
            + ", ".join(sorted(duped)[:3])
        )
    return problems


def gallery_html(selections: Iterable[dict], media_by_id: dict[str, dict]) -> str:
    """Render the curated selection as the gallery block for the project page body.

    Images carry their own alt; videos are rendered as a poster-linked <video> so the page has
    a real media element (and so score_article's video check sees an embed).
    """
    parts: list[str] = []
    for sel in selections:
        key = f"{sel.get('kind')}:{sel.get('id')}"
        row = media_by_id.get(key)
        if not row:
            continue
        if sel.get("kind") == "photo":
            # ESCAPED. `alt` is free text an editor types in the curation UI, and it is
            # interpolated straight into an attribute. Unescaped, an alt ending in `" /><img
            # src="<cdn url>` closes this tag and opens a second one pointing at a raw
            # CompanyCam file — which publishes the burned-in GPS stamp AND passed
            # `media_sanitized`, because unsanitized_media only saw double-quoted attributes.
            # Every other interpolated value on a project page goes through
            # core.portfolio_content._esc; this one did not.
            alt = html.escape((sel.get("alt") or "").strip(), quote=True)
            parts.append(f'<img src="{row.get("url", "")}" alt="{alt}" loading="lazy" />')
        else:
            poster = row.get("thumbnail_url") or ""
            parts.append(
                f'<video controls preload="none" poster="{poster}" '
                f'src="{row.get("url", "")}"></video>'
            )
    return '<div class="project-gallery">' + "".join(parts) + "</div>" if parts else ""


def score_project(
    *,
    title: str,
    meta: str,
    content_html: str,
    selections: Iterable[dict],
    has_jsonld: bool,
    permissions: dict[str, bool],
    faq: Optional[list] = None,
    keyword: str = "",
    date_modified_days: Optional[int] = None,
) -> dict[str, Any]:
    """Score a project page: the article rubric, plus what only a project page has.

    Returns {score, max, pct, checks, aio, blocking} where ``checks`` is the weighted SEO set
    and ``aio`` is advisory (never a gate — same contract as articles).

    ``blocking`` lists the reasons this page must not publish: a missing client permission is a
    legal gate, not a score.
    """
    sels = list(selections)
    base = score_article(title, meta, content_html, faq_json=list(faq or []),
                         has_jsonld=has_jsonld, keyword=keyword)

    photos = [s for s in sels if s.get("kind") == "photo"]
    alts = [(s.get("alt") or "").strip().lower() for s in photos]
    unique_alts = len({a for a in alts if a})

    project_checks = [
        {"key": "gallery_size", "label": f"≥{MIN_GALLERY_IMAGES} curated images", "points": 10,
         "pass": len(photos) >= MIN_GALLERY_IMAGES, "detail": f"{len(photos)} images"},
        {"key": "alt_unique", "label": "Every image has its own alt text", "points": 10,
         "pass": bool(photos) and unique_alts == len(photos),
         "detail": f"{unique_alts} unique of {len(photos)}"},
        {"key": "project_video", "label": "Project video included", "points": 5,
         "pass": any(s.get("kind") == "video" for s in sels)},
        {"key": "service_link", "label": "Links to a service page", "points": 10,
         "pass": bool(_SERVICE_LINK_RE.search(content_html or ""))},
        {"key": "location_link", "label": "Links to the matching location page", "points": 10,
         "pass": bool(_LOCATION_LINK_RE.search(content_html or ""))},
    ]

    checks = base["checks"] + project_checks
    score = sum(c["points"] for c in checks if c["pass"])
    maximum = sum(c["points"] for c in checks)

    blocking = [
        f"missing client permission: {name}"
        for name, ok in (("name the property", permissions.get("permission_property")),
                         ("use photos", permissions.get("permission_photos")),
                         ("use video", permissions.get("permission_video")))
        if not ok
    ]
    # Video permission only blocks when a video is actually selected — a photo-only page does
    # not need it, and blocking on it would stall every project whose client never discussed video.
    if not any(s.get("kind") == "video" for s in sels):
        blocking = [b for b in blocking if "use video" not in b]

    return {
        "score": score,
        "max": maximum,
        "pct": round(100 * score / maximum) if maximum else 0,
        "checks": [{**c, "tier": check_tier(c["key"])} for c in checks],
        "aio": aio_signals(content_html or "", date_modified_days=date_modified_days),
        "blocking": blocking,
    }
