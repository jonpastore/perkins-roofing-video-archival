"""Batch article generator + cost/quality harness.

Runs many pillar+cluster campaigns concurrently and reports the REAL cost and
quality distribution — including the refine/grounding/critique looping that a
single-article measurement can't show.

Two modes:
  measure  — calls generate_scored_article (the full to-criteria path: scored
             loop to 100 + grounding enforcement + optional 3-lens critique).
             NO WordPress publish, NO DB persistence. Pure cost/quality probe.
  publish  — calls generate_article (drafts to WP + persists). For the real run;
             pace with ScheduledContent downstream, not here.

Token accounting is exact (Gemini usage_metadata: prompt + candidate tokens),
attributed per article via a thread-local so concurrency doesn't cross wires.
Costs use current Gemini 2.5 Flash rates (standard + batch/flex).

CLI:
  python -m jobs.batch_article_job <plan.json> [--mode measure|publish]
                                   [--workers N] [--critique/--no-critique]
                                   [--out report.json]

plan.json: {"campaigns": [{"pillar": "<kw>", "clusters": ["<kw>", ...]}, ...]}
"""
import argparse
import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Gemini 2.5 Flash, USD per 1M tokens (Vertex AI, verified 2026-07-23).
PRICE = {
    "standard": {"in": 0.30, "out": 2.50},
    "batch":    {"in": 0.15, "out": 1.25},   # Flex/batch = half
}

_tls = threading.local()


def _instrument_vertex():
    """Monkeypatch VertexLLM.chat to accumulate per-article token usage into a
    thread-local record. Idempotent. Returns nothing — the record is read via
    _tls.rec around each generation call."""
    from adapters import llm as llm_mod

    if getattr(llm_mod.VertexLLM, "_batch_instrumented", False):
        return
    from adapters.llm import _with_retry

    def chat(self, prompt, want_json=False, response_schema=None):
        self._ensure_chat()
        cfg = {}
        if want_json or response_schema:
            cfg["response_mime_type"] = "application/json"
        if response_schema:
            cfg["response_schema"] = response_schema
        resp = _with_retry(lambda: self._model.generate_content(prompt, generation_config=cfg))
        u = getattr(resp, "usage_metadata", None)
        rec = getattr(_tls, "rec", None)
        if u is not None and rec is not None:
            rec["in"] += int(getattr(u, "prompt_token_count", 0) or 0)
            rec["out"] += int(getattr(u, "candidates_token_count", 0) or 0)
            rec["calls"] += 1
        return resp.text

    llm_mod.VertexLLM.chat = chat
    llm_mod.VertexLLM._batch_instrumented = True


def _fresh_vertex():
    """A per-thread VertexLLM (draft model) so concurrent workers never share one
    GenerativeModel instance."""
    import os

    from adapters.llm import VertexLLM
    return VertexLLM(
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GCP_REGION", "us-central1"),
        chat_model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
    )


def _criteria(fields: dict) -> dict:
    """Structural + SEO/AIO criteria the article must meet (mirrors the live
    console checks). Returns booleans + the numeric scores."""
    import re

    from core.seo import aio_signals, check_tier, rank_math_checks

    content = fields.get("content_md", "") or ""
    title = fields.get("title", "") or ""
    meta = fields.get("meta", "") or ""
    kw = fields.get("focus_keyword") or fields.get("keyword") or ""
    checks = rank_math_checks(title, meta, fields.get("slug", "") or "", content, kw)
    ranking = [c for c in checks if check_tier(c["key"]) == "ranking"]
    aio = aio_signals(content)
    kinds = {j.get("@type") for j in (fields.get("jsonld_json") or [])}
    img = re.search(r'<img[^>]*src="([^"]+)"', content)
    words = len(re.sub(r"<[^>]+>", " ", content).split())
    return {
        "seo_score": fields.get("seo_score"),
        "ranking_pass": sum(c["pass"] for c in ranking) / max(len(ranking), 1),
        "aio_pass": sum(c["pass"] for c in aio) / max(len(aio), 1),
        "words": words,
        "faq_ge4": len(fields.get("faq_json") or []) >= 4,
        "has_videoobject": "VideoObject" in kinds,
        "has_faqpage": "FAQPage" in kinds,
        "has_toc": 'class="toc"' in content,
        "curated_img": bool(img) and "default.jpg" not in img.group(1),
        "has_embed": "youtube.com/embed" in content or "youtu.be" in content,
    }


def _gen_one(keyword: str, role: str, pillar_slug: str | None, critique: bool) -> dict:
    """Generate one article to criteria (measure mode: no publish/persist) and
    return its cost + quality record."""
    from jobs.article_job import _stamped_session, generate_scored_article

    _tls.rec = {"in": 0, "out": 0, "calls": 0}
    ctx = {"keyword": keyword, "role": role, "pillar_slug": pillar_slug}
    ok, err = True, None
    crit = {}
    try:
        with _stamped_session(1) as db:
            fields = generate_scored_article(
                keyword, ctx, llm=_fresh_vertex(), db=db, critique=critique,
            )
        crit = _criteria({**fields, "keyword": keyword})
    except Exception as exc:  # noqa: BLE001 — a failed article is data, not a crash
        ok, err = False, f"{type(exc).__name__}: {exc}"
        logger.warning("batch gen failed keyword=%r: %s", keyword, err)
    rec = _tls.rec
    return {
        "keyword": keyword, "role": role, "ok": ok, "error": err,
        "calls": rec["calls"], "in_tok": rec["in"], "out_tok": rec["out"],
        **crit,
    }


def run_batch(campaigns: list[dict], *, workers: int = 6, critique: bool = True) -> dict:
    """Generate every campaign's pillar + clusters concurrently; return the full
    per-article records + an aggregate cost/quality report."""
    _instrument_vertex()

    # Flatten to (keyword, role, pillar_slug) work items. A cluster's pillar_slug
    # points at its pillar so cross-links resolve; slug derived like the pipeline.
    from api.routes.articles import _slugify  # noqa: PLC0415
    work = []
    for c in campaigns:
        pslug = _slugify(c["pillar"])
        work.append((c["pillar"], "pillar", None))
        for cl in c.get("clusters", []):
            work.append((cl, "cluster", pslug))

    records = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_gen_one, kw, role, ps, critique): kw for kw, role, ps in work}
        done = 0
        for fut in as_completed(futs):
            records.append(fut.result())
            done += 1
            if done % 10 == 0 or done == len(work):
                logger.info("batch progress: %d/%d articles", done, len(work))
                print(f"  ...{done}/{len(work)} articles", flush=True)

    return {"records": records, "report": _aggregate(records)}


def _aggregate(records: list[dict]) -> dict:
    import statistics

    ok = [r for r in records if r["ok"]]
    n = len(records)
    total_in = sum(r["in_tok"] for r in records)
    total_out = sum(r["out_tok"] for r in records)
    per_article_in = total_in / max(len(ok), 1)
    per_article_out = total_out / max(len(ok), 1)

    def cost_for(count, tier):
        pin = per_article_in * count * PRICE[tier]["in"] / 1e6
        pout = per_article_out * count * PRICE[tier]["out"] / 1e6
        return round(pin + pout, 2)

    calls = [r["calls"] for r in ok]
    scores = [r["seo_score"] for r in ok if r.get("seo_score") is not None]
    # "met all criteria" = structural spec + score 100 + real word floor
    met = [r for r in ok if r.get("seo_score") == 100 and r.get("faq_ge4")
           and r.get("has_videoobject") and r.get("has_faqpage")
           and (r.get("words") or 0) >= 900]
    return {
        "articles_total": n,
        "articles_ok": len(ok),
        "articles_failed": n - len(ok),
        "met_all_criteria": len(met),
        "met_criteria_rate": round(len(met) / max(len(ok), 1), 3),
        "avg_llm_calls": round(statistics.mean(calls), 2) if calls else 0,
        "max_llm_calls": max(calls) if calls else 0,
        "per_article_in_tok": round(per_article_in),
        "per_article_out_tok": round(per_article_out),
        "seo_score_median": statistics.median(scores) if scores else None,
        "seo_score_min": min(scores) if scores else None,
        "measured_batch_articles": len(ok),
        "extrapolated_3000": {
            "standard_usd": cost_for(3000, "standard"),
            "batch_usd": cost_for(3000, "batch"),
        },
        "this_run_usd": {
            "standard": cost_for(len(ok), "standard"),
            "batch": cost_for(len(ok), "batch"),
        },
        "structural_pass": {
            k: sum(1 for r in ok if r.get(k)) for k in
            ("faq_ge4", "has_videoobject", "has_faqpage", "has_toc",
             "curated_img", "has_embed")
        },
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", help="JSON: {campaigns:[{pillar, clusters[]}]}")
    ap.add_argument("--mode", choices=["measure"], default="measure",
                    help="measure = generate to-criteria, no publish (only mode wired)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--critique", dest="critique", action="store_true", default=True)
    ap.add_argument("--no-critique", dest="critique", action="store_false")
    ap.add_argument("--out", default="/tmp/batch_report.json")
    args = ap.parse_args()

    plan = json.load(open(args.plan))
    campaigns = plan["campaigns"]
    n_articles = sum(1 + len(c.get("clusters", [])) for c in campaigns)
    print(f"batch: {len(campaigns)} campaigns / {n_articles} articles, "
          f"workers={args.workers}, critique={args.critique}", flush=True)

    result = run_batch(campaigns, workers=args.workers, critique=args.critique)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=1)
    print("\n=== REPORT ===", flush=True)
    print(json.dumps(result["report"], indent=1), flush=True)
    print(f"\nfull records: {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
