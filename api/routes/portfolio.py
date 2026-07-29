"""Avada Portfolio admin routes (#384 — backend/publisher already existed as
scripts/portfolio_publish.py + scripts/portfolio_prefill.py; this is the admin UI's API).

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz, same grants as api/routes/articles.py):
  - article_read      → sales, web_admin, admin (GET)
  - manage_articles   → web_admin, admin (POST publish)

The 13 candidate projects live in scripts.portfolio_prefill.CANDIDATES (transcribed from
Wendy's projects doc — see that module's docstring for provenance). There is no DB table for
portfolio projects; WordPress itself is the status source of truth (checked live via
adapters.wordpress.find_portfolio_post).

Permission gate: Avada portfolio write-ups need three client permissions (name the property,
use photos, use video) before they can go out. These were hardcoded False with no way to record
a real answer; they now persist per project in ``portfolio_curation`` (migration 0048) along
with the curated media selection, so an editor can clear a project and publish it.

Media curation (2026-07-29): GET /portfolio/{slug}/media returns the mirrored CompanyCam media
for the project (jobs/companycam_sync.py), the current selection, and the SEO/AIO score;
PUT /portfolio/{slug}/curation records the selection. Media is filtered by permission on the
way out AND re-filtered at publish, so revoking a permission drops the media from the page.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from core.portfolio import map_to_post, needs_human
from core.portfolio_content import (
    build_faq,
    build_meta,
    build_project_jsonld,
    build_write_up,
)
from core.portfolio_media import (
    companycam_project_id,
    gallery_html,
    publishable_media,
    score_project,
    validate_selection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

class SelectionItem(BaseModel):
    kind: str = Field(description="'photo' or 'video'")
    id: str
    alt: str = ""


class CurationIn(BaseModel):
    permission_property: bool = False
    permission_photos: bool = False
    permission_video: bool = False
    selections: list[SelectionItem] = Field(default_factory=list)


def _candidate_or_404(slug: str) -> dict:
    from scripts.portfolio_prefill import CANDIDATES  # noqa: PLC0415
    candidate = next((c for c in CANDIDATES if _slugify(c["name"]) == slug), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="portfolio project not found")
    return candidate


def _curation_row(db: Session, slug: str):
    from app.models import PortfolioCuration  # noqa: PLC0415
    return db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).one_or_none()


def _permissions(row) -> dict[str, bool]:
    return {
        "permission_property": bool(row.permission_property) if row else False,
        "permission_photos": bool(row.permission_photos) if row else False,
        "permission_video": bool(row.permission_video) if row else False,
    }


def _available_media(db: Session, cc_project_id: str | None, perms: dict[str, bool]) -> dict:
    """Mirrored CompanyCam media for this project, filtered to what may be published."""
    from app.models import CompanyCamPhoto, CompanyCamVideo  # noqa: PLC0415

    if not cc_project_id:
        return {"photos": [], "videos": []}

    photos = [
        {"companycam_photo_id": p.companycam_photo_id, "url": p.url,
         "captured_at": p.captured_at.isoformat() if p.captured_at else None}
        for p in db.query(CompanyCamPhoto)
        .filter(CompanyCamPhoto.project_id == str(cc_project_id))
        .order_by(CompanyCamPhoto.captured_at.asc()).all()
    ]
    videos = [
        {"companycam_video_id": v.companycam_video_id, "url": v.url,
         "thumbnail_url": v.thumbnail_url, "internal": bool(v.internal),
         "captured_at": v.captured_at.isoformat() if v.captured_at else None}
        for v in db.query(CompanyCamVideo)
        .filter(CompanyCamVideo.project_id == str(cc_project_id))
        .order_by(CompanyCamVideo.captured_at.asc()).all()
    ]
    return publishable_media(
        photos, videos,
        permission_photos=perms["permission_photos"],
        permission_video=perms["permission_video"],
    )


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _wp_admin_url_for(wp_post_id: int | None) -> str | None:
    if not wp_post_id:
        return None
    from adapters.wordpress import resolved_wp_url  # noqa: PLC0415
    base = resolved_wp_url()
    return f"{base}/wp-admin/post.php?post={wp_post_id}&action=edit" if base else None


def _candidate_summary(candidate: dict, wp_by_title: dict | None = None,
                       curation_by_slug: dict | None = None) -> dict:
    preview = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html="",
    )
    wp_post = None
    if wp_by_title is not None:
        wp_post = wp_by_title.get(preview["title"].strip().lower())
    else:
        from adapters.wordpress import find_portfolio_post  # noqa: PLC0415
        try:
            wp_post = find_portfolio_post(candidate["name"])
        except Exception as exc:  # noqa: BLE001 — WP unreachable must not break the list
            logger.warning("wp lookup failed for portfolio candidate %s: %s", candidate["name"], exc)

    slug = _slugify(candidate["name"])
    row = (curation_by_slug or {}).get(slug)
    perms = _permissions(row)
    gate = {
        "Permission to name property": perms["permission_property"],
        "Permission to use photos": perms["permission_photos"],
        "Permission to use video": perms["permission_video"],
    }
    selections = list(row.selections or []) if row else []

    return {
        "slug": slug,
        "name": candidate["name"],
        "city": candidate["city"],
        "property_type": preview["category"],
        "roof_type": preview["skills"][0] if preview["skills"] else None,
        "companycam_url": candidate.get("companycam_url") or None,
        "youtube_url": candidate.get("youtube_url") or None,
        "curated_photos": sum(1 for s in selections if s.get("kind") == "photo"),
        "curated_videos": sum(1 for s in selections if s.get("kind") == "video"),
        **perms,
        "missing_permissions": needs_human(gate),
        "wp_post_id": wp_post["id"] if wp_post else None,
        "wp_status": wp_post["status"] if wp_post else None,
        "wp_admin_url": _wp_admin_url_for(wp_post["id"] if wp_post else None),
    }


def _media_by_id(available: dict) -> dict:
    return {
        **{f"photo:{p['companycam_photo_id']}": p for p in available.get("photos", [])},
        **{f"video:{v['companycam_video_id']}": v for v in available.get("videos", [])},
    }


def _location_slugs() -> list[str]:
    """Slugs of the location pages that actually exist, so an internal link never 404s.

    Best-effort: WordPress being unreachable costs the location link, not the page."""
    from adapters.wordpress import list_location_page_slugs  # noqa: PLC0415
    try:
        return list_location_page_slugs()
    except Exception as exc:  # noqa: BLE001
        logger.warning("wp location page lookup failed: %s", exc)
        return []


def _render_project(candidate: dict, selections: list, available: dict) -> tuple[str, list]:
    """(body_html, jsonld) for a project — the SAME render the score is taken of and the one
    publish ships, so a score can never describe a page that was never built."""
    media = _media_by_id(available)
    photos = sum(1 for s in selections if s.get("kind") == "photo")
    videos = sum(1 for s in selections if s.get("kind") == "video")
    body = build_write_up(
        candidate,
        gallery_html=gallery_html(selections, media),
        known_location_slugs=_location_slugs(),
        photo_count=photos,
        video_count=videos,
    )
    faq = build_faq(candidate, photo_count=photos, video_count=videos)
    return body, build_project_jsonld(candidate, selections, media, faq=faq)


def _placeholder_content(candidate: dict) -> str:
    """Minimal draft body when no LLM-grounded write-up exists yet (see
    scripts/portfolio_prefill.py for the full grounded-generation pipeline — out of scope
    here). The post is created as a WP *draft*; an editor finishes it in WordPress."""
    notes = (candidate.get("notes") or "").strip()
    if notes:
        return f"<p>{notes}</p>"
    city = candidate.get("city") or "South Florida"
    return f"<p>{candidate['name']} — a {candidate['section']} roofing project in {city}.</p>"


@router.get("")
def list_portfolio(
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("article_read")),
):
    from adapters.wordpress import list_portfolio_posts  # noqa: PLC0415
    from app.models import PortfolioCuration  # noqa: PLC0415
    from scripts.portfolio_prefill import CANDIDATES  # noqa: PLC0415

    curation_by_slug = {r.slug: r for r in db.query(PortfolioCuration).all()}
    # One WP fetch, matched locally — 13 sequential authed searches crawled on slow WP.
    try:
        wp_by_title = {p["title"].lower(): p for p in list_portfolio_posts()}
    except Exception as exc:  # noqa: BLE001 — WP unreachable must not break the list
        logger.warning("wp portfolio list fetch failed: %s", exc)
        wp_by_title = {}
    return [_candidate_summary(c, wp_by_title, curation_by_slug) for c in CANDIDATES]


@router.get("/{slug}/media")
def get_portfolio_media(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("article_read")),
):
    """Curation view: what media exists for this project, what's selected, and how it scores.

    Media comes from the CompanyCam mirror (jobs/companycam_sync.py), filtered by the client
    permissions recorded for this project — so an uncleared project shows an empty gallery
    rather than photos an editor could accidentally publish.
    """
    candidate = _candidate_or_404(slug)
    row = _curation_row(db, slug)
    perms = _permissions(row)
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))
    available = _available_media(db, cc_id, perms)
    selections = list(row.selections or []) if row else []

    preview = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html="",
    )
    body_html, jsonld = _render_project(candidate, selections, available)
    score = score_project(
        title=preview["title"], meta=build_meta(candidate),
        content_html=body_html, selections=selections,
        has_jsonld=bool(jsonld), permissions=perms,
        faq=build_faq(
            candidate,
            photo_count=sum(1 for s in selections if s.get("kind") == "photo"),
            video_count=sum(1 for s in selections if s.get("kind") == "video"),
        ),
    )
    return {
        "slug": slug,
        "name": candidate["name"],
        "companycam_project_id": cc_id,
        "companycam_url": candidate.get("companycam_url") or None,
        "youtube_url": (row.youtube_url if row and row.youtube_url
                        else candidate.get("youtube_url")) or None,
        **perms,
        "available": available,
        "selections": selections,
        "score": score,
    }


@router.put("/{slug}/curation")
def put_portfolio_curation(
    slug: str,
    body: CurationIn,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    """Record the curated media selection and the client permissions.

    The selection is validated against what is actually publishable *under the permissions in
    this same request*, so an editor cannot clear photos, select images, and then un-clear
    photos while leaving the selection behind.
    """
    from app.models import PortfolioCuration  # noqa: PLC0415

    candidate = _candidate_or_404(slug)
    row = _curation_row(db, slug)
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))

    perms = {
        "permission_property": body.permission_property,
        "permission_photos": body.permission_photos,
        "permission_video": body.permission_video,
    }
    available = _available_media(db, cc_id, perms)
    selections = [s.model_dump() for s in body.selections]
    problems = validate_selection(selections, available)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    if row is None:
        row = PortfolioCuration(slug=slug, companycam_project_id=cc_id)
        db.add(row)
    row.companycam_project_id = cc_id
    row.permission_property = body.permission_property
    row.permission_photos = body.permission_photos
    row.permission_video = body.permission_video
    row.selections = selections
    row.updated_by = (claims or {}).get("email")
    db.commit()

    return get_portfolio_media(slug, db=db, claims=claims)


@router.post("/{slug}/publish")
def publish_portfolio_project(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    candidate = _candidate_or_404(slug)

    row = _curation_row(db, slug)
    perms = _permissions(row)
    gate = {
        "Permission to name property": perms["permission_property"],
        "Permission to use photos": perms["permission_photos"],
        # Video permission is only required when a video is actually curated in.
        "Permission to use video": perms["permission_video"] or not any(
            s.get("kind") == "video" for s in (row.selections or [] if row else [])
        ),
    }
    missing = needs_human(gate)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"missing client permission(s): {', '.join(missing)}",
        )

    # Publish the curated gallery with the write-up. Built from the SAME permission-filtered
    # media list the curation view showed, so a permission revoked after selection drops the
    # media here too rather than shipping it.
    selections = list(row.selections or []) if row else []
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))
    available = _available_media(db, cc_id, perms)
    body_html, jsonld = _render_project(candidate, selections, available)

    # JSON-LD ships INSIDE the post body: WordPress owns the <head>, and Rank Math strips
    # unknown head injections. A script block in the content survives and validates.
    if jsonld:
        import json as _json  # noqa: PLC0415
        body_html += (
            '<script type="application/ld+json">'
            + _json.dumps(jsonld, separators=(",", ":"))
            + "</script>"
        )

    post = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html=body_html,
    )
    import requests  # noqa: PLC0415

    from adapters.wordpress import publish_portfolio_post  # noqa: PLC0415
    try:
        result = publish_portfolio_post(post)
    except requests.RequestException as exc:
        logger.warning("wp portfolio publish failed for %s: %s", candidate["name"], exc)
        raise HTTPException(status_code=502, detail=f"WordPress publish failed: {exc}") from exc

    return {**_candidate_summary(candidate, None, {slug: row} if row else None),
            "publish_result": result}
