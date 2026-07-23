"""Articles CRUD routes.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read   → sales or admin
  - manage_articles (POST/PUT/DELETE/publish) → admin only (covered by admin "*")
"""
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Article
from core.timeutil import iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/articles", tags=["articles"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def _wp_status(db_status: str | None) -> str:
    """Map an Article DB status to a valid WP REST status. The DB stores
    'published' (promote_job) but WP only accepts 'publish' — passing the DB
    value verbatim 400s and silently drops the sync for live articles."""
    return "publish" if db_status == "published" else (db_status or "draft")


def _wp_base() -> str:
    # Admin-config WP_URL wins (editable, no redeploy); env is only a fallback. See
    # adapters.wordpress.resolved_wp_url — single source of truth, no .env reliance.
    from adapters.wordpress import resolved_wp_url  # noqa: PLC0415
    return resolved_wp_url()


def _wp_url_for(wp_post_id: int | None) -> str | None:
    """Public WordPress post URL when wp_post_id and WP_URL are set; else None."""
    if not wp_post_id:
        return None
    base = _wp_base()
    return f"{base}/?p={wp_post_id}" if base else None


def _wp_admin_url_for(wp_post_id: int | None) -> str | None:
    """WordPress editor URL for the post — the useful link for drafts (the public
    ?p= URL 404s for logged-out visitors while a draft isn't live yet)."""
    if not wp_post_id:
        return None
    base = _wp_base()
    return f"{base}/wp-admin/post.php?post={wp_post_id}&action=edit" if base else None


def _article_summary(a: Article) -> dict:
    return {
        "slug": a.slug,
        "title": a.title,
        "role": a.role,
        "status": a.status,
        "pillar_slug": a.pillar_slug,
        "wp_post_id": a.wp_post_id,
        "wp_url": _wp_url_for(a.wp_post_id),
        "wp_admin_url": _wp_admin_url_for(a.wp_post_id),
        "publish_at": iso_utc(a.publish_at),
    }


def _article_full(a: Article) -> dict:
    # local import — pure, cheap, avoids import churn
    from core.seo import aio_signals, check_tier, rank_math_checks  # noqa: PLC0415

    checks = rank_math_checks(
        a.title or "", a.meta or "", a.slug or "", a.content_md or "", a.focus_keyword or ""
    )
    for c in checks:
        c["tier"] = check_tier(c["key"])

    # Freshness needs the content's age in days (Article.updated_at).
    days = None
    if a.updated_at:
        u = a.updated_at if a.updated_at.tzinfo else a.updated_at.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - u).days
    aio = aio_signals(a.content_md or "", date_modified_days=days)
    for c in aio:
        c["tier"] = "aio"

    passed = sum(1 for c in checks if c["pass"])
    # A non-100 Rank Math score is fine when the only misses are COSMETIC (density, power word —
    # Rank Math gamification, not ranking factors). What matters is ranking-relevant + AIO.
    ranking_fail = [c["key"] for c in checks if not c["pass"] and c["tier"] == "ranking"]
    cosmetic_fail = [c["key"] for c in checks if not c["pass"] and c["tier"] == "cosmetic"]
    aio_fail = [c["key"] for c in aio if not c["pass"]]
    return {
        "slug": a.slug,
        "title": a.title,
        "meta": a.meta,
        "focus_keyword": a.focus_keyword,
        "content_md": a.content_md,
        "faq_json": a.faq_json,
        "jsonld_json": a.jsonld_json,
        "role": a.role,
        "pillar_slug": a.pillar_slug,
        "wp_post_id": a.wp_post_id,
        "wp_url": _wp_url_for(a.wp_post_id),
        "wp_admin_url": _wp_admin_url_for(a.wp_post_id),
        "status": a.status,
        "publish_at": iso_utc(a.publish_at),
        # Rank Math SEO / AIO checks — surfaced in the Articles UI to stay ahead of gaps.
        # Each check carries a `tier`: "ranking" (helps Google), "cosmetic" (Rank Math
        # gamification, no ranking effect), or "aio" (modern best practice, drives AI citation).
        "seo_checks": checks,
        "seo_passed": passed,
        "seo_total": len(checks),
        "aio_checks": aio,
        "aio_passed": sum(1 for c in aio if c["pass"]),
        "aio_total": len(aio),
        # Actionable triage: cosmetic failures are safe to ignore; ranking + AIO are the work.
        "score_note": {
            "ranking_fail": ranking_fail,
            "cosmetic_fail": cosmetic_fail,
            "aio_fail": aio_fail,
            "summary": (
                "Modern best practices (AIO) matter more than a full Rank Math score. "
                "Cosmetic Rank Math misses (keyword density, power/sentiment words) are not "
                "ranking factors and are safe to ignore; focus on ranking-relevant and AIO checks."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ArticleCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    content_md: Optional[str] = None
    meta: Optional[str] = None
    focus_keyword: Optional[str] = None
    role: Optional[str] = "standalone"
    pillar_slug: Optional[str] = None
    status: Optional[str] = "draft"
    publish_at: Optional[datetime] = None


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content_md: Optional[str] = None
    meta: Optional[str] = None
    focus_keyword: Optional[str] = None
    role: Optional[str] = None
    pillar_slug: Optional[str] = None
    status: Optional[str] = None
    publish_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_articles(
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    rows = db.query(Article).order_by(Article.title).all()
    return [_article_summary(r) for r in rows]


@router.get("/{slug}")
def get_article(
    slug: str,
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    return _article_full(a)


@router.post("", status_code=201)
def create_article(
    body: ArticleCreate,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    slug = body.slug or _slugify(body.title)
    if db.get(Article, slug) is not None:
        raise HTTPException(status_code=409, detail="slug already exists")
    from jobs.article_job import sanitize_html  # noqa: PLC0415
    a = Article(
        slug=slug,
        title=body.title,
        meta=body.meta,
        focus_keyword=body.focus_keyword,
        content_md=sanitize_html(body.content_md) if body.content_md else body.content_md,
        faq_json=None,
        jsonld_json=None,
        role=body.role or "standalone",
        pillar_slug=body.pillar_slug,
        wp_post_id=None,
        status=body.status or "draft",
        publish_at=body.publish_at,
        tenant_id=db.info["tenant_id"],
    )
    db.add(a)
    db.flush()
    db.refresh(a)
    return _article_full(a)


@router.put("/{slug}")
def update_article(
    slug: str,
    body: ArticleUpdate,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    if body.title is not None:
        a.title = body.title
    if body.content_md is not None:
        from jobs.article_job import sanitize_html  # noqa: PLC0415
        a.content_md = sanitize_html(body.content_md)
    if body.meta is not None:
        a.meta = body.meta
    if body.focus_keyword is not None:
        a.focus_keyword = body.focus_keyword
    if body.role is not None:
        a.role = body.role
    if body.pillar_slug is not None:
        a.pillar_slug = body.pillar_slug
    if body.status is not None:
        a.status = body.status
    if body.publish_at is not None:
        a.publish_at = body.publish_at
    db.flush()
    db.refresh(a)
    return _article_full(a)


@router.delete("/{slug}", status_code=204)
def delete_article(
    slug: str,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    db.delete(a)


@router.post("/{slug}/reprocess")
def reprocess_article(
    slug: str,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Sanitize + optionally refine an article, then sync to WordPress if published there.

    Steps:
    1. Load the article (404 if absent).
    2. Run markdownish_to_html + sanitize_html on content_md — converts markdown
       artifacts to HTML and strips unsafe tags.
    3. Persist the sanitized content.
    4. If the article has a wp_post_id AND WP credentials are present in env,
       push the updated content to WordPress via adapters.wordpress.update.

    Role: manage_articles (admin only).
    Returns: full article dict with updated content_md.
    """
    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")

    # ── Sanitize ──────────────────────────────────────────────────────────
    from jobs.article_job import markdownish_to_html, sanitize_html  # noqa: PLC0415
    original = a.content_md or ""
    sanitized = sanitize_html(markdownish_to_html(original))
    a.content_md = sanitized

    # ── WordPress sync when wp_post_id set and creds present ──────────────
    if a.wp_post_id:
        wp_creds_present = all(
            os.environ.get(k) for k in ("WP_URL", "WP_USER", "WP_APP_PWD")
        )
        if wp_creds_present:
            try:
                from adapters.wordpress import update  # noqa: PLC0415
                from jobs.article_job import _markdown_to_html  # noqa: PLC0415
                update(
                    post_id=a.wp_post_id,
                    title=a.title or "",
                    html=_markdown_to_html(a.content_md or ""),
                    meta_description=a.meta or "",
                    jsonld=list(a.jsonld_json) if a.jsonld_json else [],
                    status=_wp_status(a.status),
                    focus_keyword=a.focus_keyword,
                )
                logger.info("wp reprocess update post_id=%d slug=%s", a.wp_post_id, slug)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "wp update failed during reprocess slug=%s (content still saved): %s",
                    slug, exc,
                )
        else:
            logger.info("wp creds absent — skipping WP sync for slug=%s", slug)

    db.flush()
    db.refresh(a)
    return _article_full(a)


@router.get("/{slug}/image-candidates")
def image_candidates(
    slug: str,
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    """Curated-image gallery for an article (buildout item 12).

    Per embedded video: three real in-video frames (~25/50/75%, best live quality
    tier) plus the title card, each deep-linked to the video at its timecode. The
    current article image is included so the UI can mark the active choice.
    """
    from adapters.frame_pick import resolve_candidates  # noqa: PLC0415
    from app.models import Video  # noqa: PLC0415
    from core.article_images import current_image_src, embedded_video_ids  # noqa: PLC0415

    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    candidates = []
    for vid in embedded_video_ids(a.content_md or ""):
        v = db.get(Video, vid)
        for c in resolve_candidates(vid, v.duration if v else None):
            candidates.append({**c, "video_id": vid,
                               "video_title": v.title if v else None})
        # Previously-extracted timecode frames for this video (WP media, public read).
        try:
            import re as _re  # noqa: PLC0415

            from adapters.wordpress import search_media  # noqa: PLC0415
            for m in search_media(f"frame-{vid}"):
                src = m.get("source_url") or ""
                t = _re.search(rf"frame-{_re.escape(vid)}-(\d+)s", src)
                if not t:
                    continue
                tc = int(t.group(1))
                candidates.append({
                    "position": None, "url": src, "fallback_url": src,
                    "timecode": tc,
                    "watch_url": f"https://www.youtube.com/watch?v={vid}&t={tc}s",
                    "is_title_card": False, "extracted": True,
                    "video_id": vid, "video_title": v.title if v else None,
                })
        except Exception as exc:  # noqa: BLE001 — gallery must not break on a WP hiccup
            logger.warning("media search failed for %s: %s", vid, exc)
    return {"slug": slug, "current": current_image_src(a.content_md or ""),
            "candidates": candidates,
            "video_durations": {vid: db.get(Video, vid).duration
                                for vid in embedded_video_ids(a.content_md or "")
                                if db.get(Video, vid)}}


class ExtractFrameRequest(BaseModel):
    video_id: str
    timecode: int  # seconds into the video


@router.post("/{slug}/extract-frame")
def extract_frame_route(
    slug: str,
    body: ExtractFrameRequest,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Extract a frame at an exact timecode from the article's archived source video
    and host it in the WP media library. Returns the frame URL for the gallery; the
    client then sets it via PUT /{slug}/image. Full source resolution (capped 1600px)
    — sharper and more varied than the four YouTube-hosted thumbnails.
    """
    from app.models import Video  # noqa: PLC0415
    from core.article_images import embedded_video_ids, frame_filename  # noqa: PLC0415

    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    if body.video_id not in embedded_video_ids(a.content_md or ""):
        raise HTTPException(status_code=422, detail="video is not embedded in this article")
    if body.timecode < 0:
        raise HTTPException(status_code=422, detail="timecode must be >= 0")
    v = db.get(Video, body.video_id)
    if v is None or not v.archive_uri:
        raise HTTPException(status_code=409, detail="video has no archived source to extract from")
    if v.duration and body.timecode >= v.duration:
        raise HTTPException(status_code=422,
                            detail=f"timecode past end of video ({int(v.duration)}s)")

    from adapters.ffmpeg import extract_frame  # noqa: PLC0415
    from adapters.storage import signed_get_url  # noqa: PLC0415
    from adapters.wordpress import upload_media  # noqa: PLC0415

    bucket, _, key = v.archive_uri.removeprefix("gs://").partition("/")
    try:
        jpeg = extract_frame(signed_get_url(bucket, key), body.timecode)
    except Exception as exc:  # noqa: BLE001 — surface extraction failure as a clean 502
        logger.warning("frame extraction failed %s t=%s: %s", body.video_id, body.timecode, exc)
        raise HTTPException(status_code=502, detail=f"frame extraction failed: {exc}") from exc
    try:
        media = upload_media(frame_filename(body.video_id, body.timecode), jpeg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("frame upload to WP failed %s t=%s: %s", body.video_id, body.timecode, exc)
        raise HTTPException(status_code=502, detail=f"WP media upload failed: {exc}") from exc
    return {
        "url": media["source_url"],
        "media_id": media["id"],
        "video_id": body.video_id,
        "timecode": body.timecode,
        "watch_url": f"https://www.youtube.com/watch?v={body.video_id}&t={body.timecode}s",
    }


class SetImageRequest(BaseModel):
    url: str


@router.put("/{slug}/image")
def set_article_image(
    slug: str,
    body: SetImageRequest,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Set the article image to a chosen gallery candidate; sync to WP if published.

    Only thumbnail variants of a video actually embedded in the article are
    accepted — the image must stay honest to the article's own video.
    """
    from core.article_images import (  # noqa: PLC0415
        current_image_src,
        embedded_video_ids,
        swap_image_src,
        valid_candidate_url,
    )

    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    allowed = set(embedded_video_ids(a.content_md or ""))
    if not valid_candidate_url(body.url, allowed):
        raise HTTPException(status_code=422,
                            detail="url is not a thumbnail variant of this article's video")
    if current_image_src(a.content_md or "") is None:
        raise HTTPException(status_code=409, detail="article has no image to replace")
    # Extracted wp-content frames are stored host-relative: the repair pass strips
    # absolute staging-host srcs (_image_allowed) and the host dies at cutover anyway.
    url = body.url
    if "/wp-content/uploads/" in url and url.startswith("http"):
        url = "/" + url.split("://", 1)[1].split("/", 1)[1]
    a.content_md = swap_image_src(a.content_md, url)

    if a.wp_post_id:
        try:
            from adapters.wordpress import update  # noqa: PLC0415
            from jobs.article_job import _markdown_to_html  # noqa: PLC0415
            update(
                post_id=a.wp_post_id,
                title=a.title or "",
                html=_markdown_to_html(a.content_md or ""),
                meta_description=a.meta or "",
                jsonld=list(a.jsonld_json) if a.jsonld_json else [],
                status=_wp_status(a.status),
                focus_keyword=a.focus_keyword,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("wp update failed setting image slug=%s (db still saved): %s",
                           slug, exc)
    db.flush()
    db.refresh(a)
    return _article_full(a)


class FixSeoRequest(BaseModel):
    check_key: str


@router.post("/{slug}/fix-seo")
def fix_seo_check(
    slug: str,
    body: FixSeoRequest,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Re-submit an article to Gemini to fix ONE failing Rank Math check, re-verify, and (if the
    article is published) update WordPress. Returns the full article with refreshed seo_checks so
    the UI can re-render the SEO/AIO panel immediately.
    """
    import json as _json

    from app.llm import chat
    from core.seo import rank_math_checks

    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    kw = (a.focus_keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="article has no focus keyword to fix against")

    checks = rank_math_checks(a.title or "", a.meta or "", a.slug or "", a.content_md or "", kw)
    target = next((c for c in checks if c["key"] == body.check_key), None)
    if target is None:
        raise HTTPException(status_code=422, detail=f"unknown check '{body.check_key}'")
    if target["pass"]:
        return _article_full(a)  # already passing — no-op

    prompt = (
        "You are editing a Perkins Roofing SEO article to fix EXACTLY ONE Rank Math issue, "
        "changing as little as possible while keeping the content accurate, natural and complete.\n\n"
        f'Focus keyword: "{kw}"\n'
        f"Issue to fix: {target['label']}"
        + (f" (current: {target['detail']})" if target.get("detail") else "")
        + "\n\n"
        f"Current SEO title:\n{a.title or ''}\n\n"
        f"Current meta description:\n{a.meta or ''}\n\n"
        f"Current article body (HTML):\n{a.content_md or ''}\n\n"
        'Return ONLY JSON: {"title": <seo title>, "meta": <meta description>, '
        '"content_md": <full revised HTML body>}. Preserve existing links, images and headings '
        "unless the fix requires changing them; keep the focus keyword usage in title/meta/slug intact."
    )
    try:
        raw = chat(prompt, want_json=True)
        data = raw if isinstance(raw, dict) else _json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.error("fix_seo_check LLM failed for %s (%s): %s", slug, body.check_key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="SEO fix generation failed") from exc

    from jobs.article_job import markdownish_to_html  # noqa: PLC0415
    a.title = data.get("title") or a.title
    a.meta = data.get("meta") or a.meta
    a.content_md = markdownish_to_html(data.get("content_md") or a.content_md or "")
    db.flush()
    db.refresh(a)

    wp_error = None
    if a.wp_post_id and all(os.environ.get(k) for k in ("WP_URL", "WP_USER", "WP_APP_PWD")):
        try:
            from adapters.wordpress import update  # noqa: PLC0415
            from jobs.article_job import _markdown_to_html  # noqa: PLC0415
            update(
                post_id=a.wp_post_id,
                title=a.title,
                html=_markdown_to_html(a.content_md or ""),
                meta_description=a.meta or "",
                jsonld=list(a.jsonld_json) if a.jsonld_json else [],
                status="publish",
                focus_keyword=a.focus_keyword,
            )
        except Exception as exc:  # noqa: BLE001 — DB is source of truth; WP is best-effort
            wp_error = str(exc)
            logger.warning("fix_seo_check WP update failed for %s: %s", slug, exc)

    result = _article_full(a)
    result["wp_error"] = wp_error
    return result


@router.post("/{slug}/publish")
def publish_article(
    slug: str,
    claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Publish an article immediately.

    Sets status='published' and publish_at=now. If WP credentials are present in
    the environment (WP_URL, WP_USER, WP_APP_PWD) and the article has content,
    publishes to WordPress and stores the returned wp_post_id. When creds are
    absent the endpoint still succeeds — it just sets the DB status without an
    external call.
    """
    a = db.get(Article, slug)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # store as naive UTC
    a.status = "published"
    a.publish_at = now

    # Attempt WordPress publish only when env creds are all present
    wp_creds_present = all(
        os.environ.get(k) for k in ("WP_URL", "WP_USER", "WP_APP_PWD")
    )
    wp_published = False
    wp_error: str | None = None
    if wp_creds_present and a.content_md:
        try:
            from adapters.wordpress import publish, update  # noqa: PLC0415
            from jobs.article_job import _markdown_to_html  # noqa: PLC0415

            html = _markdown_to_html(a.content_md)
            meta_desc = a.meta or ""
            jsonld = list(a.jsonld_json) if a.jsonld_json else []

            if a.wp_post_id:
                update(
                    post_id=a.wp_post_id,
                    title=a.title,
                    html=html,
                    meta_description=meta_desc,
                    jsonld=jsonld,
                    status="publish",
                    focus_keyword=a.focus_keyword,
                )
                logger.info("wp update post_id=%d slug=%s", a.wp_post_id, slug)
            else:
                post_id = publish(
                    title=a.title,
                    html=html,
                    meta_description=meta_desc,
                    jsonld=jsonld,
                    status="publish",
                    focus_keyword=a.focus_keyword,
                )
                a.wp_post_id = post_id
                logger.info("wp publish post_id=%d slug=%s", post_id, slug)
            wp_published = True
        except Exception as exc:  # noqa: BLE001
            wp_error = str(exc)
            logger.warning("wp publish failed for slug=%s (status still set): %s", slug, exc)
    elif not wp_creds_present:
        wp_error = "WordPress credentials not configured on the server."
        logger.info("wp creds absent — skipping external publish for slug=%s", slug)
    elif not a.content_md:
        wp_error = "Article has no content to publish."

    db.flush()
    db.refresh(a)
    # Report the TRUE WordPress outcome so the console can confirm (or warn):
    # status flips to 'published' regardless, but wp_published tells the real story.
    return {**_article_full(a), "wp_published": wp_published, "wp_error": wp_error}
