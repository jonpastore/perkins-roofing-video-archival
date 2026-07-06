"""One-shot: regenerate stub article bodies on Vertex, in place.

The broken local-LLM run left ~14 articles with the deterministic fallback body
("... projects throughout the region. This page covers ..."). This regenerates
real content via the cloud LLM + retrieval and updates content_md/meta/faq_json
in place, preserving each article's slug/role/pillar_slug/status/publish_at.

Run with LLM_BACKEND=vertex and the Cloud SQL proxy up:
  python -m jobs.regen_stub_articles
"""
import logging

logger = logging.getLogger(__name__)

_STUB_MARK = "projects throughout the region. This page covers"


def run() -> dict:
    from app.models import Article, SessionLocal
    from jobs.article_job import generate_article_content, markdownish_to_html

    with SessionLocal() as db:
        stubs = db.query(Article).filter(Article.content_md.like(f"%{_STUB_MARK}%")).all()
        slugs = [a.slug for a in stubs]

    fixed, failed = 0, 0
    for slug in slugs:
        with SessionLocal() as db:
            a = db.get(Article, slug)
            if a is None:
                continue
            kw = a.title or slug
            ctx = {"keyword": kw, "role": a.role or "standalone",
                   "pillar_slug": a.pillar_slug or "", "topic": kw}
            try:
                f = generate_article_content(kw, ctx)
                md = markdownish_to_html(f.get("content_md") or "")
                if not md or _STUB_MARK in md:
                    raise RuntimeError("still stub")
                a.content_md = md
                if f.get("meta"):
                    a.meta = f["meta"]
                if f.get("faq_json"):
                    a.faq_json = f["faq_json"]
                db.commit()
                fixed += 1
                logger.info("regenerated %s (%d chars)", slug, len(md))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed += 1
                logger.warning("regen failed for %s: %s", slug, exc)
    return {"candidates": len(slugs), "fixed": fixed, "failed": failed}


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
