"""Regenerate articles to pass the Rank Math SEO checks, then republish to WordPress.

For each target article:
  1. Derive a focus keyword FROM the existing slug (so the keyword is already in the URL and the
     WP permalink never changes — no broken links), refined to a clean 2-4 word phrase by the LLM.
  2. Regenerate the body with the (now Rank-Math-aware) generator, weaving the keyword into title,
     meta, intro, a heading, body (~1% density) and image alt.
  3. Verify with core.seo.rank_math_failures; keep the best of up to N attempts.
  4. Persist title/meta/content_md/focus_keyword; if the article was published to WP, update it.

Run locally with the Cloud SQL proxy up + vertex + WP creds in .env:
    LLM_BACKEND=vertex .venv/bin/python -m jobs.regen_articles_seo [--published-only] [--limit N] [--slug SLUG]
"""
import argparse
import logging

logger = logging.getLogger(__name__)

_STOPWORDS = {"and", "or", "the", "a", "an", "to", "of", "for", "vs", "your", "from", "with"}

# articles.status uses three spellings across the codebase ("publish", "published", "draft").
# Map to WordPress's vocabulary. Anything unrecognised -> "draft": regenerating an article must
# never be what PUBLISHES it. This used to be a hardcoded status="publish", which took post 7884
# (trashed in WP, draft in our DB) and published it live.
_WP_STATUS = {"publish": "publish", "published": "publish", "draft": "draft"}


def _wp_status_for(status: str | None) -> str:
    """WordPress status to send when republishing an article we regenerated."""
    return _WP_STATUS.get((status or "").strip().lower(), "draft")


def _keyword_from_slug(slug: str, title: str, llm) -> str:
    """A clean 2-4 word focus keyword that is a substring of the slug (so kw-in-slug passes)."""
    words = [w for w in slug.split("-") if w and w not in _STOPWORDS]
    fallback = " ".join(words[:3]) or slug.replace("-", " ")
    try:
        from app.llm import chat  # noqa: PLC0415
        prompt = (
            "Pick the best 2-4 word SEO focus keyword for a Perkins Roofing article. It MUST be a "
            f"contiguous phrase found within this URL slug (words only): '{slug.replace('-', ' ')}'. "
            f"Article title: '{title}'. Reply with ONLY the keyword phrase, lowercase, no quotes."
        )
        kw = (chat(prompt, want_json=False) or "").strip().strip('"').lower()
        # Accept only if every word of kw is in the slug (keeps the permalink valid).
        slug_words = set(slug.split("-"))
        if kw and all(w in slug_words for w in kw.split()):
            return kw
    except Exception as exc:  # noqa: BLE001 — deterministic fallback
        logger.warning("keyword LLM failed for %s: %s", slug, exc)
    return fallback


def _run_for_tenant(
    db,
    tenant_id: int,
    published_only: bool = False,
    limit: int | None = None,
    only_slug: str | None = None,
) -> dict:
    """Per-tenant SEO regen body. Called by for_each_tenant via run()."""
    from adapters.llm import get_default  # noqa: PLC0415
    from app.models import Article, SessionLocal  # noqa: PLC0415
    from core.article_plan import CLUSTER_TARGET_WORDS, PILLAR_TARGET_WORDS  # noqa: PLC0415
    from core.seo import _word_count, rank_math_failures  # noqa: PLC0415
    from jobs.article_job import _word_goal, generate_scored_article  # noqa: PLC0415

    # Same per-role targets the live generator plans against (core.article_plan) — otherwise
    # this job judges "healthy" against the old flat 1800 and keeps re-flagging correctly-sized
    # ~1000-word cluster articles as needing another regen round.
    role_target_words = {"pillar": PILLAR_TARGET_WORDS, "cluster": CLUSTER_TARGET_WORDS}

    llm = get_default()
    q = db.query(Article)
    if published_only:
        q = q.filter(Article.wp_post_id.isnot(None))
    if only_slug:
        q = q.filter(Article.slug == only_slug)
    slugs = [a.slug for a in q.all()]
    if limit:
        slugs = slugs[:limit]

    # Skip articles that are already healthy. Regeneration is non-deterministic: re-rolling a
    # good article can make it worse (observed: wall-flashings 2809 -> 2460 words, and a title
    # that had passed rm_title_number came back without a number). Only touch what is actually
    # failing. --slug is an explicit override and always regenerates.
    if not only_slug:
        skipped = []
        keep = []
        for slug in slugs:
            a = db.get(Article, slug)
            if a is None:
                continue
            fails = rank_math_failures(a.title or "", a.meta or "", slug,
                                       a.content_md or "", a.focus_keyword or "")
            target = role_target_words.get(a.role or "", 1800)
            if not fails and _word_count(a.content_md or "") >= _word_goal(target):
                skipped.append(slug)
            else:
                keep.append(slug)
        if skipped:
            logger.info("skipping %d already-healthy article(s): %s", len(skipped), skipped)
        out_skipped = skipped
        slugs = keep
    else:
        out_skipped = []

    out: dict = {"processed": 0, "passing": 0, "republished": 0,
                 "skipped_healthy": out_skipped, "still_failing": {}}
    for slug in slugs:
        with SessionLocal() as sdb:
            sdb.info["tenant_id"] = tenant_id
            a = sdb.get(Article, slug)
            if a is None:
                continue
            kw = _keyword_from_slug(slug, a.title or slug, llm)
            ctx = {"keyword": kw, "role": a.role or "standalone",
                   "pillar_slug": a.pillar_slug or slug, "topic": a.title or kw,
                   "target_words": role_target_words.get(a.role or "", 1800)}

            best = None
            best_fails = None
            for _ in range(3):
                try:
                    # critique=True: the backfill is where the adversarial pass earns its
                    # cost — these articles are republished to a live site, and a human is
                    # not reading every one. [REQ #334]
                    f = generate_scored_article(kw, ctx, llm=llm, db=db, critique=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("regen failed for %s: %s", slug, exc)
                    break
                fails = rank_math_failures(
                    f.get("title", ""), f.get("meta", ""), slug, f.get("content_md", ""), kw
                )
                if best is None or len(fails) < len(best_fails):
                    best, best_fails = f, fails
                if not fails:
                    break
            if best is None:
                continue

            a.title = best.get("title") or a.title
            a.meta = best.get("meta") or a.meta
            a.content_md = best.get("content_md") or a.content_md
            a.focus_keyword = kw
            if best.get("faq_json"):
                a.faq_json = best["faq_json"]
            if best.get("jsonld_json"):
                a.jsonld_json = best["jsonld_json"]
            # Provenance is articles.updated_at, stamped by SQLAlchemy's onupdate on every
            # write path (migration 0037). This job used to hand-stamp generated_at instead,
            # which clobbered the creation date the column is named for and covered only the
            # one caller that remembered — six other modules write content_md.
            sdb.commit()
            out["processed"] += 1
            if not best_fails:
                out["passing"] += 1
            else:
                out["still_failing"][slug] = best_fails
            wp_post_id = a.wp_post_id
            title, meta, content, jsonld_out = a.title, a.meta, a.content_md, (a.jsonld_json or [])
            wp_status = _wp_status_for(a.status)

        if wp_post_id:
            try:
                from adapters.wordpress import update as wp_update  # noqa: PLC0415
                from jobs.article_job import _markdown_to_html  # noqa: PLC0415
                wp_update(
                    wp_post_id,
                    title=title or slug,
                    html=_markdown_to_html(content or ""),
                    meta_description=meta or "",
                    jsonld=jsonld_out if isinstance(jsonld_out, list) else [],
                    status=wp_status,
                    focus_keyword=kw,
                )
                out["republished"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("WP republish failed for %s (post %s): %s", slug, wp_post_id, exc)
        logger.info("regen %s: kw=%r fails=%s", slug, kw, best_fails)

    return out


def run(published_only: bool = False, limit: int | None = None, only_slug: str | None = None) -> dict:
    """Iterate active tenants and regenerate articles for SEO for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"processed": 0, "passing": 0, "republished": 0, "still_failing": {}}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, published_only=published_only,
                            limit=limit, only_slug=only_slug)
        totals["processed"] += r.get("processed", 0)
        totals["passing"] += r.get("passing", 0)
        totals["republished"] += r.get("republished", 0)
        totals["still_failing"].update(r.get("still_failing", {}))

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--published-only", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--slug", default=None)
    args = p.parse_args()
    print(json.dumps(run(published_only=args.published_only, limit=args.limit, only_slug=args.slug), indent=2))
