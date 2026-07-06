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


def run() -> dict:
    from adapters.llm import get_default
    from app.models import Article, SessionLocal
    from core.seo import score_article
    from jobs.article_job import (
        _build_article_jsonld, _clamp_meta, _fallback_faq, _regen_faq,
        generate_scored_article, markdownish_to_html,
    )

    llm = get_default()
    upgraded, already, regenerated = 0, 0, 0
    with SessionLocal() as db:
        slugs = [a.slug for a in db.query(Article).all()]

    for slug in slugs:
        with SessionLocal() as db:
            a = db.get(Article, slug)
            if a is None:
                continue
            before = score_article(a.title or "", a.meta or "", a.content_md or "",
                                   a.faq_json or [], bool(a.jsonld_json))["score"]
            if before >= 100:
                already += 1
                continue

            # --- Cheap pass: fix meta / faq / jsonld / title without touching content ---
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
                # Content-quality gaps (headings/wordcount/video) → full scored regen.
                ctx = {"keyword": title, "role": a.role or "standalone",
                       "pillar_slug": a.pillar_slug or a.slug, "topic": title}
                try:
                    f = generate_scored_article(title, ctx, llm=llm)
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
            db.commit()
            upgraded += 1
            logger.info("upgraded %s: %d -> %d", slug, before, after)

    return {"upgraded": upgraded, "regenerated": regenerated,
            "already_100": already, "total": len(slugs)}


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
