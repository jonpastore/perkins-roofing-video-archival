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
use photos, use video) before they can go out. None of the 13 candidates have been confirmed
by a client yet, so the gate is honest-but-static here (all False) — there is no persistence
for these yet. A follow-on ticket should add a small admin-editable store once Wendy has
confirmations to record; today publish is correctly blocked for everyone until that exists.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_role
from core.portfolio import map_to_post, needs_human

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# All three permissions are unconfirmed for every current candidate — see module docstring.
_PERMISSION_GATE = {
    "Permission to name property": False,
    "Permission to use photos": False,
    "Permission to use video": False,
}


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


def _candidate_summary(candidate: dict) -> dict:
    preview = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html="",
    )
    from adapters.wordpress import find_portfolio_post  # noqa: PLC0415
    wp_post = None
    try:
        wp_post = find_portfolio_post(candidate["name"])
    except Exception as exc:  # noqa: BLE001 — WP unreachable must not break the list
        logger.warning("wp lookup failed for portfolio candidate %s: %s", candidate["name"], exc)

    return {
        "slug": _slugify(candidate["name"]),
        "name": candidate["name"],
        "city": candidate["city"],
        "property_type": preview["category"],
        "roof_type": preview["skills"][0] if preview["skills"] else None,
        "companycam_url": candidate.get("companycam_url") or None,
        "youtube_url": candidate.get("youtube_url") or None,
        "permission_property": _PERMISSION_GATE["Permission to name property"],
        "permission_photos": _PERMISSION_GATE["Permission to use photos"],
        "permission_video": _PERMISSION_GATE["Permission to use video"],
        "missing_permissions": needs_human(_PERMISSION_GATE),
        "wp_post_id": wp_post["id"] if wp_post else None,
        "wp_status": wp_post["status"] if wp_post else None,
        "wp_admin_url": _wp_admin_url_for(wp_post["id"] if wp_post else None),
    }


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
    claims=Depends(require_role("article_read")),
):
    from scripts.portfolio_prefill import CANDIDATES  # noqa: PLC0415
    return [_candidate_summary(c) for c in CANDIDATES]


@router.post("/{slug}/publish")
def publish_portfolio_project(
    slug: str,
    claims=Depends(require_role("manage_articles")),
):
    from scripts.portfolio_prefill import CANDIDATES  # noqa: PLC0415
    candidate = next((c for c in CANDIDATES if _slugify(c["name"]) == slug), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="portfolio project not found")

    missing = needs_human(_PERMISSION_GATE)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"missing client permission(s): {', '.join(missing)}",
        )

    post = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html=_placeholder_content(candidate),
    )
    import requests  # noqa: PLC0415

    from adapters.wordpress import publish_portfolio_post  # noqa: PLC0415
    try:
        result = publish_portfolio_post(post)
    except requests.HTTPError as exc:
        logger.warning("wp portfolio publish failed for %s: %s", candidate["name"], exc)
        raise HTTPException(status_code=502, detail=f"WordPress publish failed: {exc}") from exc

    return {**_candidate_summary(candidate), "publish_result": result}
