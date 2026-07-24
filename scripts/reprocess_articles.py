"""Bring every non-compliant persisted article up to the Wendy checklist IN PLACE.

For each article that currently fails core.article_criteria, run the SAME compliance gate
the generation pipeline uses (deterministic ensures + repair; the LLM re-refine only fires
if a residual answer_first/seo_ranking remains, which — after the gate hardening — it does
not), PRESERVE the existing slug/permalink, then update the WordPress post + DB row.

Idempotent: an already-compliant article is skipped. Dry by default.

    python -m scripts.reprocess_articles            # dry-run: report what would change
    python -m scripts.reprocess_articles --apply     # write to WP + DB
    python -m scripts.reprocess_articles --apply --limit 5

Env: the usual DB_URL + Vertex vars (EMBED_BACKEND=vertex, GOOGLE_CLOUD_PROJECT, ...).
"""
import argparse
import re
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from adapters.wordpress import (  # noqa: E402
    category_id_for_name, featured_media_from_url, publish, update)
from app.models import Article, SessionLocal  # noqa: E402
from core.article_criteria import check_compliance, failing  # noqa: E402
from core.wp_category import pick_category_name  # noqa: E402
from jobs.article_job import (  # noqa: E402
    _compliance_gate, _markdown_to_html, _repair_inputs, _stamped_session)
from jobs.batch_article_job import _fresh_vertex  # noqa: E402


def _kw_from(slug: str, focus_keyword: str | None) -> str:
    """The article's focus keyword, or a clean phrase derived from the slug when it's NULL
    (pre-gate backfill articles have no focus_keyword)."""
    return focus_keyword or re.sub(r"-\d{4}$", "", slug).replace("-", " ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to WordPress + DB (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="cap the number of articles processed")
    args = ap.parse_args()

    with _stamped_session(1) as db:
        known = _repair_inputs(db)["known_video_ids"]
        rows = db.execute(text(
            "SELECT slug,title,meta,content_md,focus_keyword,faq_json,jsonld_json,role,"
            "pillar_slug,wp_post_id,status FROM articles ORDER BY generated_at DESC")).fetchall()

    targets = []
    for r in rows:
        slug, title, meta, content, fk, faq, jsonld, role, pillar, _wp, _st = r
        comp = check_compliance(content or "", meta or "", jsonld or [], faq or [],
                                {"role": role, "pillar_slug": pillar, "title": title or "", "slug": slug},
                                _kw_from(slug, fk), known)
        if failing(comp):
            targets.append(r)
    if args.limit:
        targets = targets[:args.limit]
    print(f"{len(rows)} total articles; {len(targets)} non-compliant to reprocess "
          f"({'APPLY' if args.apply else 'DRY-RUN'})\n")

    ok_n, blocked = 0, []
    for r in targets:
        slug, title, meta, content, fk, faq, jsonld, role, pillar, wp_id, status = r
        kw = _kw_from(slug, fk)
        fields = {"content_md": content or "", "faq_json": list(faq or []), "title": title or "",
                  "meta": meta or "", "slug": slug, "jsonld_json": list(jsonld or [])}
        ctx = {"role": role, "pillar_slug": pillar}
        with _stamped_session(1) as gdb:
            comp, compliant = _compliance_gate(fields, ctx, kw, gdb, llm=_fresh_vertex())
        fields["slug"] = slug  # never change the live permalink
        recheck = check_compliance(fields["content_md"], fields["meta"], fields["jsonld_json"],
                                   fields["faq_json"], {**ctx, "title": fields["title"], "slug": slug},
                                   kw, known)
        fails = [c.key for c in failing(recheck)]
        if fails:
            blocked.append((slug, fails))
            print(f"  BLOCKED {slug[:44]:46} {fails}")
            continue
        ok_n += 1
        if not args.apply:
            continue
        html = _markdown_to_html(fields["content_md"])
        cat = category_id_for_name(pick_category_name(kw, fields["content_md"]))
        m = re.search(r'<img[^>]*\bsrc="([^"]+)"', fields["content_md"])
        featured = featured_media_from_url(m.group(1), f"{slug}-featured.jpg") if m else None
        # Map internal Article.status -> a valid WP status. "scheduled" = draft on WP + a
        # ScheduledContent row promote_job flips live at publish_at, so WP stays "draft".
        wp_status = "publish" if status == "published" else "draft"
        if wp_id:
            update(wp_id, title=fields["title"], html=html, meta_description=fields["meta"],
                   jsonld=fields["jsonld_json"], status=wp_status, focus_keyword=kw,
                   category_ids=[cat] if cat else None, featured_media=featured)
        else:
            wp_id = publish(title=fields["title"], html=html, meta_description=fields["meta"],
                            jsonld=fields["jsonld_json"], status=wp_status, focus_keyword=kw,
                            slug=slug, category_ids=[cat] if cat else None, featured_media=featured)
        wdb = SessionLocal(); wdb.info["tenant_id"] = 1
        try:
            row = wdb.get(Article, slug)
            row.title, row.meta = fields["title"], fields["meta"]
            row.content_md, row.faq_json = fields["content_md"], fields["faq_json"]
            row.jsonld_json, row.focus_keyword, row.wp_post_id = fields["jsonld_json"], kw, wp_id
            wdb.add(row); wdb.commit()
        finally:
            wdb.close()
        print(f"  OK {slug[:50]:52} wp={wp_id}")

    print(f"\n=== {ok_n}/{len(targets)} compliant{' + WRITTEN' if args.apply else ' (dry)'}; "
          f"{len(blocked)} blocked ===")
    for slug, fails in blocked:
        print(f"   blocked: {slug} {fails}")


if __name__ == "__main__":
    main()
