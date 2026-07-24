"""Validate already-generated articles with the single grounding critic, and REGENERATE only
the ones it flags with a blocking finding.

Scope: articles whose focus_keyword is in the given plan (default: the current run's plan), so
articles made BEFORE the in-loop critic existed get the same grounding guarantee without blindly
regenerating the clean ones. A flagged article is regenerated via generate_scored_article (which
now runs the grounding critic in-loop) and re-published in place (WP post + DB row, slug preserved).

    python -m scripts.validate_run_with_critic --plan <plan.json>            # dry: report flags
    python -m scripts.validate_run_with_critic --plan <plan.json> --apply     # regenerate flagged

Env: DB_URL + Vertex vars (EMBED_BACKEND=vertex, GOOGLE_CLOUD_PROJECT, GCP_REGION, LLM_MODEL).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from adapters.llm import VertexLLM  # noqa: E402
from adapters.wordpress import (  # noqa: E402
    category_id_for_name, featured_media_from_url, publish, update)
from app.models import Article, SessionLocal  # noqa: E402
from core.article_critique import blocking, critique_prompt, parse_findings  # noqa: E402
from core.json_repair import parse_model_json  # noqa: E402
from core.wp_category import pick_category_name  # noqa: E402
from jobs.article_job import (  # noqa: E402
    _markdown_to_html, _stamped_session, generate_scored_article, source_transcripts)


def _vertex() -> VertexLLM:
    return VertexLLM(project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                     location=os.getenv("GCP_REGION", "us-central1"),
                     chat_model=os.getenv("LLM_MODEL", "gemini-2.5-flash"))


def _grounding_blockers(article: dict, transcript: str, llm) -> list[dict]:
    """The single grounding critic's blocking findings for an existing article."""
    prompt = critique_prompt("grounding", article, transcript)
    raw = llm.chat(prompt, want_json=True)
    findings = parse_findings(parse_model_json(raw) if isinstance(raw, str) else raw)
    return blocking(findings)


def _republish(fields: dict, slug: str, kw: str, role, pillar, wp_id, status) -> int:
    html = _markdown_to_html(fields["content_md"])
    cat = category_id_for_name(pick_category_name(kw, fields["content_md"]))
    m = re.search(r'<img[^>]*\bsrc="([^"]+)"', fields["content_md"])
    featured = featured_media_from_url(m.group(1), f"{slug}-featured.jpg") if m else None
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
    return wp_id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="plan .json whose keywords scope the run")
    ap.add_argument("--apply", action="store_true", help="regenerate + rewrite flagged articles")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    plan = json.load(open(args.plan))["campaigns"]
    kws = set()
    for c in plan:
        kws.add(c["pillar"]); kws.update(c.get("clusters", []))

    with _stamped_session(1) as db:
        rows = db.execute(text(
            "SELECT slug,title,meta,content_md,focus_keyword,faq_json,jsonld_json,role,"
            "pillar_slug,wp_post_id,status FROM articles WHERE focus_keyword = ANY(:k)"),
            {"k": list(kws)}).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} run articles to validate with the grounding critic "
          f"({'APPLY' if args.apply else 'DRY'})\n")

    llm = _vertex()
    clean = flagged = regenerated = no_evidence = 0
    for r in rows:
        slug, title, meta, content, kw, faq, jsonld, role, pillar, wp_id, status = r
        with _stamped_session(1) as db:
            try:
                sources = source_transcripts(kw, db=db)
            except Exception:  # noqa: BLE001
                sources = []
        transcript = "\n\n".join(s["transcript"] for s in sources) if sources else ""
        if not transcript:
            no_evidence += 1
            print(f"  SKIP (no evidence) {slug[:44]}")
            continue
        article = {"content_md": content or "", "title": title or "", "meta": meta or "",
                   "focus_keyword": kw}
        try:
            blockers = _grounding_blockers(article, transcript, llm)
        except Exception as exc:  # noqa: BLE001
            print(f"  CRITIC-ERR {slug[:44]}: {exc}")
            continue
        if not blockers:
            clean += 1
            continue
        flagged += 1
        print(f"  FLAGGED {slug[:44]:46} {len(blockers)} blocker(s): "
              f"{[b['issue'][:60] for b in blockers[:2]]}")
        if not args.apply:
            continue
        ctx = {"keyword": kw, "role": role, "pillar_slug": pillar}
        with _stamped_session(1) as db:
            fields = generate_scored_article(kw, ctx, llm=_vertex(), validator_llm=_vertex(),
                                             db=db, critique=False)
        if not fields.get("compliant"):
            print(f"     regen NOT compliant, leaving original: {slug}")
            continue
        fields["slug"] = slug
        new_wp = _republish(fields, slug, kw, role, pillar, wp_id, status)
        regenerated += 1
        print(f"     REGENERATED {slug[:44]} wp={new_wp}")

    print(f"\n=== critic validation: {clean} clean, {flagged} flagged, "
          f"{regenerated} regenerated, {no_evidence} no-evidence ===")


if __name__ == "__main__":
    main()
