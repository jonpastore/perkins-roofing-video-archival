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


def _run_for_tenant(db, tenant_id: int) -> dict:
    """Per-tenant stub article regeneration. Called by for_each_tenant via run()."""
    from app.models import Article  # noqa: PLC0415
    from jobs.article_job import generate_article_content, markdownish_to_html  # noqa: PLC0415

    stubs = db.query(Article).filter(Article.content_md.like(f"%{_STUB_MARK}%")).all()
    slugs = [a.slug for a in stubs]

    fixed, failed = 0, 0
    for slug in slugs:
        a = db.get(Article, slug)
        if a is None:
            continue
        kw = a.title or slug
        ctx = {"keyword": kw, "role": a.role or "standalone",
               "pillar_slug": a.pillar_slug or "", "topic": kw}
        try:
            f = generate_article_content(kw, ctx, db=db)
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


def run() -> dict:
    """Iterate active tenants and regenerate stub articles for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"candidates": 0, "fixed": 0, "failed": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
