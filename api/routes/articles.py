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

from api.auth import require_role
from app.config import settings
from app.models import Article, SessionLocal

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


def _wp_base() -> str:
    return (settings.WP_URL or os.environ.get("WP_URL", "")).rstrip("/")


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
        "publish_at": a.publish_at.isoformat() if a.publish_at else None,
    }


def _article_full(a: Article) -> dict:
    return {
        "slug": a.slug,
        "title": a.title,
        "meta": a.meta,
        "content_md": a.content_md,
        "faq_json": a.faq_json,
        "jsonld_json": a.jsonld_json,
        "role": a.role,
        "pillar_slug": a.pillar_slug,
        "wp_post_id": a.wp_post_id,
        "wp_url": _wp_url_for(a.wp_post_id),
        "wp_admin_url": _wp_admin_url_for(a.wp_post_id),
        "status": a.status,
        "publish_at": a.publish_at.isoformat() if a.publish_at else None,
    }


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ArticleCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    content_md: Optional[str] = None
    meta: Optional[str] = None
    role: Optional[str] = "standalone"
    pillar_slug: Optional[str] = None
    status: Optional[str] = "draft"
    publish_at: Optional[datetime] = None


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content_md: Optional[str] = None
    meta: Optional[str] = None
    role: Optional[str] = None
    pillar_slug: Optional[str] = None
    status: Optional[str] = None
    publish_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_articles(claims=Depends(require_role("article_read"))):
    with SessionLocal() as db:
        rows = db.query(Article).order_by(Article.title).all()
        return [_article_summary(r) for r in rows]


@router.get("/{slug}")
def get_article(slug: str, claims=Depends(require_role("article_read"))):
    with SessionLocal() as db:
        a = db.get(Article, slug)
        if a is None:
            raise HTTPException(status_code=404, detail="article not found")
        return _article_full(a)


@router.post("", status_code=201)
def create_article(body: ArticleCreate, claims=Depends(require_role("manage_articles"))):
    slug = body.slug or _slugify(body.title)
    with SessionLocal() as db:
        if db.get(Article, slug) is not None:
            raise HTTPException(status_code=409, detail="slug already exists")
        from jobs.article_job import sanitize_html  # noqa: PLC0415
        a = Article(
            slug=slug,
            title=body.title,
            meta=body.meta,
            content_md=sanitize_html(body.content_md) if body.content_md else body.content_md,
            faq_json=None,
            jsonld_json=None,
            role=body.role or "standalone",
            pillar_slug=body.pillar_slug,
            wp_post_id=None,
            status=body.status or "draft",
            publish_at=body.publish_at,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        return _article_full(a)


@router.put("/{slug}")
def update_article(slug: str, body: ArticleUpdate,
                   claims=Depends(require_role("manage_articles"))):
    with SessionLocal() as db:
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
        if body.role is not None:
            a.role = body.role
        if body.pillar_slug is not None:
            a.pillar_slug = body.pillar_slug
        if body.status is not None:
            a.status = body.status
        if body.publish_at is not None:
            a.publish_at = body.publish_at
        db.commit()
        db.refresh(a)
        return _article_full(a)


@router.delete("/{slug}", status_code=204)
def delete_article(slug: str, claims=Depends(require_role("manage_articles"))):
    with SessionLocal() as db:
        a = db.get(Article, slug)
        if a is None:
            raise HTTPException(status_code=404, detail="article not found")
        db.delete(a)
        db.commit()


@router.post("/{slug}/reprocess")
def reprocess_article(slug: str, claims=Depends(require_role("manage_articles"))):
    """Sanitize + optionally refine an article, then sync to WordPress if published there.

    Steps:
    1. Load the article (404 if absent).
    2. Run markdownish_to_html + sanitize_html on content_md — converts markdown artifacts to HTML and strips unsafe tags.
    3. Persist the sanitized content.
    4. If the article has a wp_post_id AND WP credentials are present in env,
       push the updated content to WordPress via adapters.wordpress.update.

    Role: manage_articles (admin only).
    Returns: full article dict with updated content_md.
    """
    with SessionLocal() as db:
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
                    from jobs.article_job import _markdown_to_html  # noqa: PLC0415
                    from adapters.wordpress import update  # noqa: PLC0415
                    update(
                        post_id=a.wp_post_id,
                        title=a.title or "",
                        html=_markdown_to_html(a.content_md or ""),
                        meta_description=a.meta or "",
                        jsonld=list(a.jsonld_json) if a.jsonld_json else [],
                        status=a.status or "draft",
                    )
                    logger.info("wp reprocess update post_id=%d slug=%s", a.wp_post_id, slug)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "wp update failed during reprocess slug=%s (content still saved): %s",
                        slug, exc,
                    )
            else:
                logger.info("wp creds absent — skipping WP sync for slug=%s", slug)

        db.commit()
        db.refresh(a)
        return _article_full(a)


@router.post("/{slug}/publish")
def publish_article(slug: str, claims=Depends(require_role("manage_articles"))):
    """Publish an article immediately.

    Sets status='published' and publish_at=now. If WP credentials are present in
    the environment (WP_URL, WP_USER, WP_APP_PWD) and the article has content,
    publishes to WordPress and stores the returned wp_post_id. When creds are
    absent the endpoint still succeeds — it just sets the DB status without an
    external call.
    """
    with SessionLocal() as db:
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
                from jobs.article_job import _markdown_to_html  # noqa: PLC0415
                from adapters.wordpress import publish, update  # noqa: PLC0415

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
                    )
                    logger.info("wp update post_id=%d slug=%s", a.wp_post_id, slug)
                else:
                    post_id = publish(
                        title=a.title,
                        html=html,
                        meta_description=meta_desc,
                        jsonld=jsonld,
                        status="publish",
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

        db.commit()
        db.refresh(a)
        # Report the TRUE WordPress outcome so the console can confirm (or warn):
        # status flips to 'published' regardless, but wp_published tells the real story.
        return {**_article_full(a), "wp_published": wp_published, "wp_error": wp_error}
