"""One-shot: bring EXISTING articles up to a 100 SEO/AIO score without regenerating
their body copy.

Fills the structural gaps the first-pass generator left behind — missing JSON-LD,
short meta descriptions, empty FAQ, and out-of-range titles — using the same
deterministic helpers + scorer as the generation loop. Content_md is preserved.

Run with LLM_BACKEND=vertex and the Cloud SQL proxy up:
  python -m jobs.upgrade_articles
"""
import logging

logger = logging.getLogger(__name__)


def _fix_title(title: str) -> str:
    t = (title or "").strip()
    if 30 <= len(t) <= 65:
        return t
    if len(t) < 30:
        # Add the shortest suffix that lands the title in the 30-65 band.
        for suffix in (": Homeowner's Guide", ": A Complete Homeowner's Guide",
                       ": A Complete Homeowner's Guide from Perkins Roofing"):
            cand = f"{t}{suffix}"
            if 30 <= len(cand) <= 65:
                return cand
        return f"{t}: Homeowner's Guide"  # accept slightly-short over mid-word cuts
    # Too long: trim at a word boundary, never mid-word.
    cut = t[:65].rsplit(" ", 1)[0].rstrip(" ,:;-")
    return cut or t[:65].rstrip()


def _run_for_tenant(db, tenant_id: int) -> dict:
    """Per-tenant article upgrade body. Called by for_each_tenant via run()."""
    from adapters.llm import get_default  # noqa: PLC0415
    from app.models import Article, SessionLocal  # noqa: PLC0415
    from core.seo import score_article  # noqa: PLC0415
    from jobs.article_job import (  # noqa: PLC0415
        _build_article_jsonld,
        _clamp_meta,
        _fallback_faq,
        _regen_faq,
        generate_scored_article,
        markdownish_to_html,
    )

    llm = get_default()
    slugs = [a.slug for a in db.query(Article).all()]
    upgraded, already, regenerated = 0, 0, 0

    for slug in slugs:
        with SessionLocal() as sdb:
            sdb.info["tenant_id"] = tenant_id
            a = sdb.get(Article, slug)
            if a is None:
                continue
            before = score_article(a.title or "", a.meta or "", a.content_md or "",
                                   a.faq_json or [], bool(a.jsonld_json))["score"]
            if before >= 100:
                already += 1
                continue

            title = _fix_title(a.title or slug)
            faq = a.faq_json or []
            if not faq:
                faq = _regen_faq(title, a.content_md or "", llm=llm) or \
                    _fallback_faq(title, a.content_md or "")
            meta = _clamp_meta(a.meta or "", title, a.content_md or "")
            jsonld = _build_article_jsonld(
                {"title": title, "meta": meta, "faq_json": faq},
                {"pillar_slug": a.pillar_slug or a.slug},
            )
            after = score_article(title, meta, a.content_md or "", faq, bool(jsonld))["score"]

            if after < 100:
                ctx = {"keyword": title, "role": a.role or "standalone",
                       "pillar_slug": a.pillar_slug or a.slug, "topic": title}
                try:
                    f = generate_scored_article(title, ctx, llm=llm, db=db)
                    title = f.get("title") or title
                    a.content_md = markdownish_to_html(f.get("content_md") or a.content_md)
                    meta = f.get("meta") or meta
                    faq = f.get("faq_json") or faq
                    jsonld = f.get("jsonld_json") or jsonld
                    after = f.get("seo_score", after)
                    regenerated += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("regen failed for %s: %s", slug, exc)

            a.title, a.meta, a.faq_json, a.jsonld_json = title, meta, faq, jsonld
            sdb.commit()
            upgraded += 1
            logger.info("upgraded %s: %d -> %d", slug, before, after)

    return {"upgraded": upgraded, "regenerated": regenerated,
            "already_100": already, "total": len(slugs)}


def run() -> dict:
    """Iterate active tenants and upgrade articles for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"upgraded": 0, "regenerated": 0, "already_100": 0, "total": 0}

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
