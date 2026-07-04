"""Article generation job — I/O orchestration (coverage-omitted).

End-to-end pipeline:
    1. Build prompt  (core.article_prompt)
    2. Optionally ground with source videos (app.retrieval.hybrid_search)
    3. Call LLM      (adapters.llm via app.llm singleton)
    4. Parse JSON    (core.json_repair)
    5. QA checks     (core.qa_gate — dedup; fact/intent checks added here)
    6. Build JSON-LD (core.jsonld)
    7. Persist       (app.models.Article — upsert, idempotency guard)
    8. Publish       (adapters.wordpress — default status="draft")

Never auto-publishes: status defaults to "draft" and callers must explicitly
pass status="publish" to go live.
"""

from __future__ import annotations

import logging
import re

from core.article_prompt import system_prompt, template_prompt
from core.json_repair import parse_model_json
from core.jsonld import build_article, build_faq_page, build_video_object
from core.qa_gate import is_duplicate, verdict

logger = logging.getLogger(__name__)


# Vertex controlled-generation schema — constrains Gemini to valid JSON for every article.
ARTICLE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "slug": {"type": "STRING"},
        "metaDescription": {"type": "STRING"},
        "excerpt": {"type": "STRING"},
        "content": {"type": "STRING"},
        "faq": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"q": {"type": "STRING"}, "a": {"type": "STRING"}},
                "required": ["q", "a"],
            },
        },
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "internalLinks": {"type": "ARRAY", "items": {"type": "STRING"}},
        "wordCount": {"type": "INTEGER"},
    },
    "required": ["title", "slug", "content"],
}


def generate_article(
    keyword: str,
    ctx: dict,
    serp: dict,
    *,
    existing_texts: list[str] | None = None,
    status: str = "draft",
    llm=None,
    ground_videos: bool = True,
    persist: bool = True,
) -> dict:
    """Generate a single SEO article and publish it to WordPress as a draft.

    Args:
        keyword:        Primary target keyword.
        ctx:            Article context dict passed through to
                        ``core.article_prompt.template_prompt``.  Must include
                        at minimum ``{"keyword": keyword, ...}``.  PAA questions,
                        answer_box, internal_links, author, etc. are optional.
        serp:           SERP dict for the keyword (from adapters.serper or a
                        fixture).  Used to populate ``paa``, ``answer_box``, and
                        ``related`` inside *ctx* when those keys are absent.
        existing_texts: List of existing article body strings for dedup check.
                        Pass ``[]`` or omit to skip dedup.
        status:         WordPress post status.  Default ``"draft"`` — callers must
                        explicitly pass ``"publish"`` to go live.
        llm:            Optional VertexLLM instance.  When omitted, the default
                        singleton from ``adapters.llm.get_default()`` is used.
        ground_videos:  When True, call app.retrieval.hybrid_search to pull top
                        chunks from Tim's ingested corpus and append a SOURCE VIDEOS
                        section to the user prompt.  Best-effort: if retrieval fails
                        or returns nothing, the article is still generated.
        persist:        When True, upsert an app.models.Article row after publish.
                        Idempotency: if the slug already has a wp_post_id the
                        existing WP post is updated instead of a new one being created.

    Returns:
        Dict with keys::

            {
                "post_id":      int,          # WordPress post id
                "title":        str,
                "slug":         str,
                "verdict":      str,          # "pass"|"warn"|"block"
                "qa_checks":    list[dict],   # raw check results
                "article":      dict,         # parsed LLM output
                "failed_open":  bool,         # True if any QA checker errored
            }

    Raises:
        RuntimeError: if the QA verdict is "block" (article not published).
        requests.HTTPError: if the WordPress REST API returns a non-2xx response.
    """
    # ── 0. Lazy imports (I/O adapters) ───────────────────────────────────────
    if llm is None:
        from adapters.llm import get_default  # noqa: PLC0415
        llm = get_default()

    from adapters.wordpress import publish, update  # noqa: PLC0415

    # ── 1. Enrich ctx with SERP signals if caller didn't pre-populate ────────
    enriched = dict(ctx)
    enriched.setdefault("keyword", keyword)
    if serp:
        if "paa" not in enriched:
            from core.serp_analysis import extract_paa_questions  # noqa: PLC0415
            paa_raw = extract_paa_questions(serp)
            # Strip HTML tags from PAA text before it enters the prompt
            enriched["paa"] = [_strip_html(q) for q in paa_raw]
        if "answer_box" not in enriched:
            ab = serp.get("answerBox")
            if ab and isinstance(ab, str):
                ab = _strip_html(ab)
            enriched["answer_box"] = ab
        if "related" not in enriched:
            related_raw = serp.get("relatedSearches") or []
            enriched["related"] = [
                _strip_html(r) if isinstance(r, str) else r for r in related_raw
            ]

    # ── 2. Build prompt ───────────────────────────────────────────────────────
    sys_prompt = system_prompt()
    user_prompt = template_prompt(enriched)

    # ── 2a. Video grounding (best-effort) ────────────────────────────────────
    video_chunks: list[tuple] = []   # (chunk, score) pairs from retrieval
    jsonld_video_list: list[dict] = []

    if ground_videos:
        try:
            from app.retrieval import hybrid_search  # noqa: PLC0415
            result = hybrid_search(keyword, k=4)
            video_chunks = result.get("chunks") or []
            if video_chunks:
                user_prompt = _append_video_grounding(user_prompt, video_chunks)
                jsonld_video_list = _build_video_jsonld(video_chunks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("video grounding failed, continuing without it: %s", exc)

    # ── 3. Call LLM (schema-controlled → guaranteed-valid JSON; retry on any fluke) ──────
    prompt = f"{sys_prompt}\n\n{user_prompt}"
    article: dict = {}
    for _ in range(3):
        try:
            raw = llm.chat(prompt, want_json=True, response_schema=ARTICLE_SCHEMA)
        except TypeError:  # llm without response_schema support (e.g. a test fake)
            raw = llm.chat(prompt, want_json=True)
        parsed = parse_model_json(raw)
        if isinstance(parsed, dict) and parsed.get("content"):
            article = parsed
            break

    # ── 4. Validate ───────────────────────────────────────────────────────────
    if not article.get("content"):
        raise RuntimeError(f"LLM returned unparseable JSON for keyword '{keyword}'")

    title = article.get("title") or keyword
    content = article.get("content") or ""
    # Embed a real WordPress video player for the top source clip (bare URL on its own line →
    # WP oEmbed). Keeps the inline ?t= deep-links + VideoObject schema too.
    if video_chunks:
        content = _inject_oembed(content, video_chunks)
    # Normalize FAQ at the I/O boundary — the LLM occasionally omits a field.
    faq = [{"q": it["q"], "a": it.get("a", "")}
           for it in (article.get("faq") or [])
           if isinstance(it, dict) and it.get("q")]
    slug = article.get("slug") or ""

    # ── 5. QA checks ─────────────────────────────────────────────────────────
    qa_checks: list[dict] = []
    failed_open = False

    # Dedup check (pure — no LLM)
    if existing_texts:
        dup = is_duplicate(content, existing_texts)
        qa_checks.append({
            "name": "dedup",
            "severity": "block" if dup else "pass",
            "details": "Near-duplicate detected (Jaccard ≥ 0.85)" if dup else "No duplicates found",
        })
    else:
        qa_checks.append({"name": "dedup", "severity": "pass", "details": "Skipped — no corpus"})

    # Fact-check (LLM — fail-open on adapter error)
    try:
        fact_check = _run_fact_check(llm, content)
        qa_checks.append(fact_check)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fact-check errored (fail-open): %s", exc)
        failed_open = True
        qa_checks.append({
            "name": "fact_check",
            "severity": "pass",
            "details": f"Checker failed-open: {exc}",
        })

    # Intent-match check (LLM — fail-open on adapter error)
    try:
        intent_check = _run_intent_check(llm, keyword, content)
        qa_checks.append(intent_check)
    except Exception as exc:  # noqa: BLE001
        logger.warning("intent-check errored (fail-open): %s", exc)
        failed_open = True
        qa_checks.append({
            "name": "intent_match",
            "severity": "pass",
            "details": f"Checker failed-open: {exc}",
        })

    gate_verdict = verdict(qa_checks)
    logger.info("article QA verdict=%s keyword=%r checks=%d", gate_verdict, keyword, len(qa_checks))

    if gate_verdict == "block":
        raise RuntimeError(
            f"Article for '{keyword}' blocked by QA gate: "
            + "; ".join(c["details"] for c in qa_checks if c.get("severity") == "block")
        )

    # ── 6. Build JSON-LD ──────────────────────────────────────────────────────
    import datetime  # noqa: PLC0415
    today = datetime.date.today().isoformat()
    author_name = (enriched.get("author") or {}).get("name") or "Perkins Roofing"
    wp_url = _wp_base_url()
    canonical_url = f"{wp_url}/blog/{slug}"

    jsonld_list: list[dict] = [
        build_article(
            headline=title,
            description=article.get("metaDescription") or "",
            author_name=author_name,
            date_published=today,
            url=canonical_url,
        )
    ]
    if faq:
        jsonld_list.append(build_faq_page(faq))

    # Append VideoObject entries for each grounded source video
    jsonld_list.extend(jsonld_video_list)

    # ── 7. Idempotency check + Publish/Update ────────────────────────────────
    existing_article = None
    if persist and slug:
        from app.models import Article as ArticleModel  # noqa: PLC0415
        from app.models import SessionLocal
        _db = SessionLocal()
        try:
            existing_article = _db.get(ArticleModel, slug)
        finally:
            _db.close()

    if existing_article and existing_article.wp_post_id:
        # Update existing WP post instead of creating a duplicate
        update(
            post_id=existing_article.wp_post_id,
            title=title,
            html=_markdown_to_html(content),
            meta_description=article.get("metaDescription") or "",
            jsonld=jsonld_list,
            status=status,
        )
        post_id = existing_article.wp_post_id
        logger.info("updated existing post_id=%d keyword=%r status=%s", post_id, keyword, status)
    else:
        post_id = publish(
            title=title,
            html=_markdown_to_html(content),
            meta_description=article.get("metaDescription") or "",
            jsonld=jsonld_list,
            status=status,
        )
        logger.info("published post_id=%d keyword=%r status=%s", post_id, keyword, status)

    # ── 8. Persist Article row ────────────────────────────────────────────────
    if persist and slug:
        import datetime as dt  # noqa: PLC0415

        from app.models import Article as ArticleModel  # noqa: PLC0415
        from app.models import SessionLocal
        publish_at_val = ctx.get("publish_at")
        if isinstance(publish_at_val, str):
            try:
                publish_at_val = dt.datetime.fromisoformat(publish_at_val)
            except ValueError:
                publish_at_val = None

        _db = SessionLocal()
        try:
            row = _db.get(ArticleModel, slug)
            if row is None:
                row = ArticleModel(slug=slug)
                _db.add(row)
            row.title = title
            row.meta = article.get("metaDescription") or ""
            row.content_md = content
            row.faq_json = faq
            row.jsonld_json = jsonld_list
            row.role = ctx.get("role")
            row.pillar_slug = ctx.get("pillar_slug")
            row.wp_post_id = post_id
            row.status = status
            row.publish_at = publish_at_val
            _db.commit()
        finally:
            _db.close()

    return {
        "post_id": post_id,
        "title": title,
        "slug": slug,
        "verdict": gate_verdict,
        "qa_checks": qa_checks,
        "article": article,
        "failed_open": failed_open,
    }


def run(
    topic: str,
    keyword_serps: list[tuple[str, dict]],
    *,
    max_articles: int = 12,
    status: str = "draft",
) -> dict:
    """Orchestrate a full pillar + cluster article campaign.

    Args:
        topic:          Broad topic label (e.g. "roof repair").
        keyword_serps:  List of (keyword_string, serp_dict) tuples — the raw
                        keyword/SERP pairs to build the plan from.
        max_articles:   Cap on how many articles to generate.  Default 12.
        status:         WordPress post status passed to each generate_article call.

    Returns:
        Dict::

            {
                "generated": int,
                "articles":  [list of generate_article return dicts],
            }
    """
    from core.article_plan import build_plan  # noqa: PLC0415

    # Build keyword dicts for plan — infer intent as "informational" by default
    keywords = [
        {"keyword": kw, "intent": "informational", "topic": topic}
        for kw, _ in keyword_serps
    ]
    serps_map = {kw: serp for kw, serp in keyword_serps}

    plan = build_plan(keywords, serps_map)

    # Collect all planned keywords (pillar + clusters), capped at max_articles
    planned: list[dict] = [plan["pillar"]] + plan["clusters"]
    planned = planned[:max_articles]

    generated_articles = []
    existing_texts: list[str] = []

    pillar_slug = plan["pillar"]["slug"]

    for item in planned:
        kw = item["keyword"]
        is_pillar = item["slug"] == pillar_slug
        ctx = {
            "keyword": kw,
            "angle": item.get("angle", ""),
            "outline": item.get("outline", []),
            "role": "pillar" if is_pillar else "cluster",
            "pillar_slug": pillar_slug if not is_pillar else None,
        }
        serp = serps_map.get(kw) or {}
        try:
            result = generate_article(
                kw,
                ctx,
                serp,
                existing_texts=list(existing_texts),
                status=status,
            )
            generated_articles.append(result)
            content = result["article"].get("content") or ""
            if content:
                existing_texts.append(content)
        except Exception as exc:  # noqa: BLE001
            logger.error("generate_article failed for keyword=%r: %s", kw, exc)

    return {"generated": len(generated_articles), "articles": generated_articles}


if __name__ == "__main__":
    import json
    import sys

    # Usage: python -m jobs.article_job <topic> <keyword1> [<keyword2> ...]
    # SERPs default to empty dicts (no live Serper calls)
    if len(sys.argv) < 3:  # noqa: PLR2004
        print("Usage: python -m jobs.article_job <topic> <kw1> [<kw2> ...]")
        sys.exit(1)
    _topic = sys.argv[1]
    _kw_serps = [(kw, {}) for kw in sys.argv[2:]]
    print(json.dumps(run(_topic, _kw_serps), indent=2))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _wp_base_url() -> str:
    """Read WP_URL from env, stripping trailing slash."""
    import os  # noqa: PLC0415
    return os.environ.get("WP_URL", "https://perkinsroofing.net").rstrip("/")


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string (for SERP/PAA data before prompt injection)."""
    return re.sub(r"<[^>]+>", "", text)


def _markdown_to_html(md: str) -> str:
    """Convert Markdown to sanitised HTML for WordPress post content.

    Uses the `markdown` library for conversion then `bleach` to strip any
    unsafe tags/attributes (no script, iframe, on* event handlers, etc.).
    """
    import bleach  # noqa: PLC0415
    import markdown  # noqa: PLC0415
    from bleach.sanitizer import ALLOWED_ATTRIBUTES, ALLOWED_TAGS  # noqa: PLC0415

    allowed_tags = list(ALLOWED_TAGS) + [
        "p", "h1", "h2", "h3", "h4",
        "ul", "ol", "li",
        "blockquote", "code", "pre",
        "img", "table", "thead", "tbody", "tr", "td", "th",
    ]
    allowed_attrs = dict(ALLOWED_ATTRIBUTES)
    allowed_attrs["a"] = ["href", "title", "rel"]
    allowed_attrs["img"] = ["src", "alt", "title"]

    html = markdown.markdown(md, extensions=["tables", "fenced_code"])
    return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)


def _duration_iso(seconds: float | None) -> str:
    """Convert a duration in seconds to ISO 8601 format (PT#M#S)."""
    if not seconds:
        return "PT0S"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"PT{minutes}M{secs}S"
    return f"PT{secs}S"


def _append_video_grounding(user_prompt: str, chunks: list[tuple]) -> str:
    """Append a SOURCE VIDEOS section to the user prompt."""
    from core.retrieval import link as video_link  # noqa: PLC0415
    lines = [
        "",
        "SOURCE VIDEOS from Perkins Roofing's own YouTube channel (Tim's expert content). You MUST "
        "reference at least two of these in the article body as inline markdown links using the exact "
        "?t= URLs below — e.g. [what Tim says about X](URL) — and weave their specific insights into "
        "the copy. These first-party expert videos are the article's strongest E-E-A-T + AIO signal:",
    ]
    for chunk, _score in chunks:
        yt_link = video_link(chunk.video_id, chunk.start)
        lines.append(f"- {yt_link} : {chunk.text[:300]}")
    return user_prompt + "\n".join(lines)


def _inject_oembed(content: str, chunks: list[tuple]) -> str:
    """Insert a bare YouTube watch URL (with &t= start) on its own line after the first
    paragraph so WordPress oEmbeds a real inline player. python-markdown leaves a bare URL
    un-linked, so it survives to WP's autoembed."""
    if not chunks:
        return content
    chunk, _score = chunks[0]
    url = f"https://www.youtube.com/watch?v={chunk.video_id}&t={int(chunk.start)}s"
    parts = content.split("\n\n", 1)
    if len(parts) == 2:
        return f"{parts[0]}\n\n{url}\n\n{parts[1]}"
    return f"{url}\n\n{content}"


def _build_video_jsonld(chunks: list[tuple]) -> list[dict]:
    """Build VideoObject JSON-LD entries for distinct source videos in chunks."""
    from app.models import SessionLocal, Video  # noqa: PLC0415
    from core.retrieval import link as video_link  # noqa: PLC0415

    seen_ids: set[str] = set()
    result: list[dict] = []

    _db = SessionLocal()
    try:
        for chunk, _score in chunks:
            vid_id = chunk.video_id
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)

            video = _db.get(Video, vid_id)
            title = video.title if video and video.title else vid_id
            upload_date = video.upload_date if video and video.upload_date else ""
            duration_secs = video.duration if video and video.duration else None

            content_url = video_link(vid_id, chunk.start)
            embed_url = f"https://www.youtube.com/embed/{vid_id}"
            thumbnail_url = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
            description = chunk.text[:300]

            result.append(build_video_object(
                title=title,
                description=description,
                thumbnail_url=thumbnail_url,
                upload_date=upload_date,
                content_url=content_url,
                embed_url=embed_url,
                duration_iso=_duration_iso(duration_secs),
            ))
    finally:
        _db.close()

    return result


def _run_fact_check(llm, content: str) -> dict:
    """Run a Vertex-backed fact-check on the article content.

    Prompts the LLM to flag hallucinated specific numbers or claims.
    Returns a qa_check dict with severity warn|pass.
    Never raises (caller wraps in try/except).
    """
    prompt = (
        "You are a fact-checking assistant. Read the article below and identify any "
        "specific numbers, statistics, or concrete claims that appear to be hallucinated "
        "or unverifiable. If you find any, reply with: WARN: <brief description>. "
        "If everything looks factually sound for a roofing services article, reply: PASS\n\n"
        f"ARTICLE:\n{content[:3000]}"
    )
    raw = llm.chat(prompt, want_json=False)
    raw = (raw or "").strip()
    if raw.upper().startswith("WARN"):
        return {
            "name": "fact_check",
            "severity": "warn",
            "details": raw[:300],
        }
    return {
        "name": "fact_check",
        "severity": "pass",
        "details": "No hallucinated claims detected",
    }


def _run_intent_check(llm, keyword: str, content: str) -> dict:
    """Run a Vertex-backed intent-match check.

    Verifies the article genuinely addresses the target keyword's search intent.
    Returns a qa_check dict with severity warn|pass.
    Never raises (caller wraps in try/except).
    """
    prompt = (
        f"Keyword: {keyword}\n\n"
        "Does the article below address the search intent for that keyword? "
        "Reply with PASS if yes, or WARN: <reason> if not.\n\n"
        f"ARTICLE EXCERPT:\n{content[:2000]}"
    )
    raw = llm.chat(prompt, want_json=False)
    raw = (raw or "").strip()
    if raw.upper().startswith("WARN"):
        return {
            "name": "intent_match",
            "severity": "warn",
            "details": raw[:300],
        }
    return {
        "name": "intent_match",
        "severity": "pass",
        "details": "Article matches keyword intent",
    }
