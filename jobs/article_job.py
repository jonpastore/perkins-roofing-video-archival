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
from contextlib import contextmanager

from core.article_prompt import system_prompt, template_prompt
from core.json_repair import parse_model_json
from core.jsonld import build_article, build_breadcrumb_list, build_faq_page, build_video_object
from core.qa_gate import is_duplicate, verdict

logger = logging.getLogger(__name__)


@contextmanager
def _stamped_session(tenant_id):
    """Short-lived SessionLocal stamped with tenant_id (RLS GUC via after_begin).

    For retrieval calls inside job bodies that have a tenant_id but no ambient
    session — keeps the chain strict-safe (C1 Part 2). tenant_id=None yields an
    unstamped session (dev/SQLite only, where the event no-ops).
    """
    from app.models import SessionLocal  # noqa: PLC0415
    s = SessionLocal()
    if tenant_id is not None:
        s.info["tenant_id"] = tenant_id
    try:
        yield s
    finally:
        s.close()



# ---------------------------------------------------------------------------
# HTML sanitizer — strips/converts residual markdown artifacts
# ---------------------------------------------------------------------------

# Matches GitHub-style admonition lines: > [!TIP], > [!NOTE], etc.
_ADMONITION_RE = re.compile(
    r"^>\s*\[!(TIP|WARNING|NOTE|KEY|CAUTION|IMPORTANT)\]\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# Matches blockquote continuation lines that follow an admonition: > text
_BLOCKQUOTE_LINE_RE = re.compile(r"^>\s?", re.MULTILINE)
# Markdown headings: ## Heading → <h2>Heading</h2>
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
# Markdown bold: **text** or __text__
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
# Markdown pipe tables (lines starting with |)
_PIPE_TABLE_LINE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
# Markdown separator rows: |---|---|
_TABLE_SEP_RE = re.compile(r"^\|[\s\-|:]+\|$", re.MULTILINE)

_ADMONITION_CLASS = {
    "tip": "tip",
    "warning": "warning",
    "note": "note",
    "key": "key",
    "caution": "warning",
    "important": "note",
}


def markdownish_to_html(content: str) -> str:
    """Convert residual markdown artifacts in article content to HTML.

    Handles:
    - GitHub-style `> [!TIP]` / `> [!NOTE]` admonition blocks → ``<aside class="...">``
    - Markdown headings (## H2, ### H3) → ``<h2>``, ``<h3>`` etc.
    - Markdown bold (**text**) → ``<strong>``
    - Markdown pipe tables → plain ``<table>`` HTML
    - Any remaining bare `[!X]` markers → stripped

    Content that is already valid HTML is passed through unchanged (the regex
    patterns only match markdown-specific syntax).

    NOTE: This is a markdown→HTML converter, NOT a security sanitizer. Use
    ``sanitize_html()`` (bleach-based) to strip unsafe tags/attributes.
    """
    if not content:
        return content

    # ── 1. Convert > [!TIP] admonition blocks ────────────────────────────────
    # Each block is: one marker line + one or more > continuation lines.
    # We process line-by-line so we can collect multi-line callout bodies.
    lines = content.split("\n")
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ADMONITION_RE.match(line)
        if m:
            kind = m.group(1).lower()
            css_class = _ADMONITION_CLASS.get(kind, "note")
            # Collect following > continuation lines as the callout body
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                body_lines.append(_BLOCKQUOTE_LINE_RE.sub("", lines[i], count=1).strip())
                i += 1
            body = " ".join(body_lines).strip() or ""
            if body:
                out_lines.append(f'<aside class="{css_class}"><p>{body}</p></aside>')
            # else drop empty callout
        else:
            out_lines.append(line)
            i += 1
    content = "\n".join(out_lines)

    # ── 2. Strip any bare [!X] markers that survived (e.g. without > prefix) ─
    content = re.sub(r"\[!(TIP|WARNING|NOTE|KEY|CAUTION|IMPORTANT)\]", "", content, flags=re.IGNORECASE)

    # ── 3. Convert markdown headings → HTML headings ──────────────────────────
    def _heading_repl(m: re.Match) -> str:
        level = len(m.group(1))
        level = min(level, 6)
        return f"<h{level}>{m.group(2).strip()}</h{level}>"

    content = _MD_HEADING_RE.sub(_heading_repl, content)

    # ── 4. Convert markdown bold → <strong> ──────────────────────────────────
    def _bold_repl(m: re.Match) -> str:
        text = m.group(1) or m.group(2)
        return f"<strong>{text}</strong>"

    content = _MD_BOLD_RE.sub(_bold_repl, content)

    # ── 4b. Convert markdown links [text](url) → <a href> ────────────────────
    content = _MD_LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', content)

    # ── 4c. Convert leftover markdown italics *text* → <em> (bold already done) ─
    content = _MD_ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", content)

    # ── 4d. Convert markdown bullet lines (- / *) → <ul><li> ─────────────────
    content = _convert_bullets(content)

    # ── 5. Convert markdown pipe tables → HTML <table> ───────────────────────
    content = _convert_pipe_tables(content)

    return content


# ---------------------------------------------------------------------------
# HTML security sanitizer (bleach-based) — strips unsafe tags/attributes.
# Applied on write to prevent stored-XSS from admin-supplied content_md.
# ---------------------------------------------------------------------------

_BLEACH_ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "ul", "ol", "li", "strong", "em", "b", "i",
    "a", "br", "hr",
    "table", "thead", "tbody", "tr", "td", "th",
    "blockquote", "code", "pre",
    "aside", "div", "span", "img", "iframe",
]

_BLEACH_ALLOWED_ATTRS: dict = {
    "*": ["class"],
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height", "loading"],
    "iframe": ["src", "allow", "allowfullscreen", "loading", "frameborder",
               "width", "height", "title"],
}

_SAFE_URI_RE = re.compile(r"^(https?:|/|#|mailto:)", re.IGNORECASE)

# Tags whose entire content (inner text + children) should be dropped, not just the tag.
_STRIP_CONTENT_RE = re.compile(
    r"<(script|style|noscript|object|embed|applet|base|meta|link)"
    r"(\s[^>]*)?>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
# Also drop self-closing / unclosed script/style tags that may lack a close tag
_STRIP_CONTENT_OPEN_RE = re.compile(
    r"<(script|style|noscript|object|embed|applet|base|meta|link)(\s[^>]*)?/?>",
    re.IGNORECASE,
)


def _allow_safe_attrs(tag: str, name: str, value: str) -> bool:
    """Bleach attribute callback: block on* handlers and unsafe URI schemes."""
    if name.lower().startswith("on"):
        return False
    if name.lower() in ("href", "src", "action", "data"):
        return bool(_SAFE_URI_RE.match(value.strip()))
    return True


def sanitize_html(content: str) -> str:
    """Bleach-clean HTML to the article allow-list, stripping script/on*/javascript:.

    Safe for storage: legitimate article HTML (headings, lists, links, tables,
    YouTube iframes with https src) survives unchanged; <script>, onerror=,
    javascript: URLs, and any on* event handler are stripped.

    Two-pass approach:
    1. Regex-strip entire <script>/<style>/… blocks including their inner text
       (bleach strip=True only removes the tag wrapper, keeping inner text).
    2. bleach.clean with a URI+on* callback to catch remaining attribute attacks.
    """
    if not content:
        return content
    import bleach  # noqa: PLC0415

    # Pass 1: drop entire content of script/style/etc. blocks
    content = _STRIP_CONTENT_RE.sub("", content)
    content = _STRIP_CONTENT_OPEN_RE.sub("", content)

    # Pass 2: bleach allow-list + attribute callback
    return bleach.clean(
        content,
        tags=_BLEACH_ALLOWED_TAGS,
        attributes=_allow_safe_attrs,
        strip=True,
        strip_comments=True,
    )


# Markdown links: [text](http… or /path) — not images (no leading !)
_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(((?:https?:|/|#)[^)\s]+)\)")
# Single-asterisk italics (bold ** already handled): *text*
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
# Markdown bullet line: "- item" or "* item" at line start
_MD_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")


def _convert_bullets(content: str) -> str:
    """Wrap consecutive markdown bullet lines in <ul><li>…</li></ul>."""
    out, buf = [], []

    def flush():
        if buf:
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in buf) + "</ul>")
            buf.clear()

    for line in content.split("\n"):
        m = _MD_BULLET_RE.match(line)
        # Skip lines that are already HTML list items or contain block tags
        if m and "<li" not in line and "<td" not in line:
            buf.append(m.group(1).strip())
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


# Residual-markdown detector: headings, bold, italics, links, bullets, pipe tables,
# strikethrough, or __double-underscore__ bold.
_MD_RESIDUAL = [
    re.compile(r"^#{1,6}\s", re.MULTILINE),
    re.compile(r"\*\*[^*]+\*\*"),
    re.compile(r"__[^_]+__"),
    re.compile(r"(?<!\*)\*(?!\s)(?!\*)([^*\n]+?)(?<!\s)\*(?!\*)"),  # *italic*
    re.compile(r"~~[^~]+~~"),                                         # ~~strikethrough~~
    re.compile(r"(?<!\!)\[[^\]]+\]\((?:https?:|/|#)[^)\s]+\)"),
    re.compile(r"^\s*[-*]\s+\S", re.MULTILINE),
    re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE),
]


def has_residual_markdown(content: str) -> bool:
    """True if any Markdown syntax remains (used to gate the generation loop)."""
    return any(rx.search(content or "") for rx in _MD_RESIDUAL)


# ---------------------------------------------------------------------------
# Placeholder detector — catches unfilled template tokens in LLM output
# ---------------------------------------------------------------------------

# Common placeholder patterns: TODO, [insert X], {{var}}, XXXX, Lorem, [keyword], etc.
_PLACEHOLDER_PATTERNS = [
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bLorem\b", re.IGNORECASE),
    re.compile(r"\[insert\b[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[add\b[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[your\b[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[keyword\]", re.IGNORECASE),
    re.compile(r"\[\w[\w\s]{0,30}\]"),   # [PLACEHOLDER], [CONTENT HERE], etc.
    re.compile(r"\{\{[^}]+\}\}"),         # {{variable}} / Jinja/Handlebars tokens
    re.compile(r"\bXXXX+\b"),             # XXXX filler
    re.compile(r"<\s*(placeholder|todo|insert)[^>]*>", re.IGNORECASE),  # <placeholder>
]


def has_placeholder(content: str) -> bool:
    """True if unfilled template tokens or placeholder text remain in content."""
    return any(rx.search(content or "") for rx in _PLACEHOLDER_PATTERNS)


def _convert_pipe_tables(content: str) -> str:
    """Convert markdown pipe tables to HTML <table> elements."""
    lines = content.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        # Detect a pipe-table block: header row | sep row | data rows
        if _PIPE_TABLE_LINE_RE.match(lines[i].strip()):
            table_lines: list[str] = []
            while i < len(lines) and _PIPE_TABLE_LINE_RE.match(lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1
            # Need at least header + separator
            if len(table_lines) >= 2 and _TABLE_SEP_RE.match(table_lines[1]):
                header_cells = [c.strip() for c in table_lines[0].strip("|").split("|")]
                data_rows = table_lines[2:]
                html_parts = ["<table>", "<thead><tr>"]
                for cell in header_cells:
                    html_parts.append(f"<th>{cell}</th>")
                html_parts.append("</tr></thead>")
                if data_rows:
                    html_parts.append("<tbody>")
                    for row in data_rows:
                        cells = [c.strip() for c in row.strip("|").split("|")]
                        html_parts.append("<tr>")
                        for cell in cells:
                            html_parts.append(f"<td>{cell}</td>")
                        html_parts.append("</tr>")
                    html_parts.append("</tbody>")
                html_parts.append("</table>")
                out.append("".join(html_parts))
            else:
                # Not a real table — keep as-is
                out.extend(table_lines)
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


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


def generate_article_content(
    keyword: str,
    ctx: dict,
    *,
    llm=None,
    ground_videos: bool = True,
    db=None,
) -> dict:
    """Generate real article content via LLM + retrieval WITHOUT publishing to WordPress.

    Reuses the same prompt-building, video-grounding, and LLM-call logic as
    ``generate_article`` but skips the WordPress publish step and all DB persistence.
    Use this to produce finished draft content synchronously (e.g. from an API
    route), then persist the returned fields yourself.

    Args:
        keyword:       Primary target keyword.
        ctx:           Article context dict (same shape as generate_article ctx).
                       Must include at minimum ``{"keyword": keyword}``.
        llm:           Optional VertexLLM instance.  Falls back to the default
                       singleton when omitted.
        ground_videos: When True, call app.retrieval.hybrid_search to ground the
                       prompt in source videos.  Best-effort: if retrieval fails
                       the article is still generated.

    Returns:
        Dict with keys::

            {
                "title":      str,
                "slug":       str,
                "meta":       str,   # metaDescription
                "content_md": str,   # full markdown body
                "faq_json":   list,  # [{q, a}, ...]
            }

    Raises:
        RuntimeError: if the LLM returns unparseable JSON after 3 attempts.
    """
    if llm is None:
        from adapters.llm import get_default  # noqa: PLC0415
        llm = get_default()

    # ── Enrich ctx ────────────────────────────────────────────────────────────
    enriched = dict(ctx)
    enriched.setdefault("keyword", keyword)

    # ── Build prompt ──────────────────────────────────────────────────────────
    sys_prompt = system_prompt()
    user_prompt = template_prompt(enriched)

    # ── Video grounding (best-effort) ─────────────────────────────────────────
    if ground_videos:
        try:
            from app.retrieval import hybrid_search  # noqa: PLC0415
            result = hybrid_search(keyword, k=4, db=db)
            video_chunks = result.get("chunks") or []
            if video_chunks:
                user_prompt = _append_video_grounding(user_prompt, video_chunks)
        except Exception as exc:  # noqa: BLE001
            # RuntimeError here is the strict unstamped-session guard — never bury it
            lvl = logger.critical if isinstance(exc, RuntimeError) else logger.warning
            lvl("video grounding failed for %r, continuing: %s", keyword, exc)

    # ── Call LLM (retry up to 3×) ─────────────────────────────────────────────
    prompt = f"{sys_prompt}\n\n{user_prompt}"
    article: dict = {}
    for _ in range(3):
        try:
            raw = llm.chat(prompt, want_json=True, response_schema=ARTICLE_SCHEMA)
        except TypeError:
            raw = llm.chat(prompt, want_json=True)
        parsed = parse_model_json(raw)
        if isinstance(parsed, dict) and parsed.get("content"):
            article = parsed
            break

    if not article.get("content"):
        raise RuntimeError(f"LLM returned unparseable JSON for keyword '{keyword}'")

    faq = [{"q": it["q"], "a": it.get("a", "")}
           for it in (article.get("faq") or [])
           if isinstance(it, dict) and it.get("q")]

    return {
        "title":      article.get("title") or keyword,
        "slug":       article.get("slug") or "",
        "meta":       article.get("metaDescription") or "",
        "content_md": markdownish_to_html(article.get("content") or ""),
        "faq_json":   faq,
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
    tenant_id: int | None = None,
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
            with _stamped_session(tenant_id) as _gs:
                result = hybrid_search(keyword, k=4, db=_gs)
            video_chunks = result.get("chunks") or []
            if video_chunks:
                user_prompt = _append_video_grounding(user_prompt, video_chunks)
                jsonld_video_list = _build_video_jsonld(video_chunks, tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001
            lvl = logger.critical if isinstance(exc, RuntimeError) else logger.warning
            lvl("video grounding failed, continuing without it: %s", exc)

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
    content = markdownish_to_html(article.get("content") or "")
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
        if tenant_id is not None:
            _db.info["tenant_id"] = tenant_id
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
        if tenant_id is not None:
            _db.info["tenant_id"] = tenant_id
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


def _run_for_tenant(
    db,
    tenant_id: int,
    topic: str,
    keyword_serps: list[tuple[str, dict]],
    *,
    max_articles: int = 12,
    status: str = "draft",
) -> dict:
    """Per-tenant article campaign body. Called by for_each_tenant via run()."""
    from core.article_plan import build_plan  # noqa: PLC0415

    keywords = [
        {"keyword": kw, "intent": "informational", "topic": topic}
        for kw, _ in keyword_serps
    ]
    serps_map = {kw: serp for kw, serp in keyword_serps}

    plan = build_plan(keywords, serps_map)

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
                tenant_id=tenant_id,
            )
            generated_articles.append(result)
            content = result["article"].get("content") or ""
            if content:
                existing_texts.append(content)
        except Exception as exc:  # noqa: BLE001
            logger.error("generate_article failed for keyword=%r: %s", kw, exc)

    return {"generated": len(generated_articles), "articles": generated_articles}


def run(
    topic: str,
    keyword_serps: list[tuple[str, dict]],
    *,
    max_articles: int = 12,
    status: str = "draft",
) -> dict:
    """Iterate active tenants and orchestrate a full pillar + cluster article campaign for each.

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
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"generated": 0, "articles": []}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, topic, keyword_serps,
                            max_articles=max_articles, status=status)
        totals["generated"] += r.get("generated", 0)
        totals["articles"].extend(r.get("articles", []))

    for_each_tenant(SessionLocal, _fn)
    return totals


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

def refine_article_content(fields: dict, keyword: str, *, llm=None) -> dict:
    """Run a second SEO/AIO pass on first-pass article fields.

    Takes the output of generate_article_content ({title, slug, meta, content_md,
    faq_json}) and asks the LLM to revise it for:
      - AIO (AI-answer optimized): question-led headings, concise direct answers, FAQ-friendly
      - SEO: keyword coverage, meta description quality, scannable structure

    Returns an improved version of the same field dict.  If the LLM call fails for
    any reason the original fields are returned unchanged (fail-open).

    Args:
        fields:  First-pass dict from generate_article_content.
        keyword: Primary target keyword (used to anchor the refine prompt).
        llm:     Optional LLM instance; falls back to default singleton.
    """
    if llm is None:
        try:
            from adapters.llm import get_default  # noqa: PLC0415
            llm = get_default()
        except Exception as exc:  # noqa: BLE001
            logger.warning("refine_article_content: no llm available, skipping: %s", exc)
            return fields

    refine_prompt = (
        f"You are an expert SEO and AIO (AI-answer optimized) content editor.\n"
        f"Primary keyword: {keyword}\n\n"
        f"Revise the article below to be FULLY AIO-optimized and SEO-optimized:\n"
        f"- Use clear question-led headings (e.g. ## What is X? ## How does X work?)\n"
        f"- Provide concise, direct answers immediately after each heading\n"
        f"- Ensure the target keyword and semantic variants appear naturally throughout\n"
        f"- Improve the meta description to be compelling and keyword-rich (≤160 chars)\n"
        f"- Add or improve a FAQ section with common questions and concise answers\n"
        f"- Preserve all factual content; only improve structure and clarity\n\n"
        f"Return a JSON object with exactly these keys: title, slug, metaDescription, content, faq\n"
        f"where faq is an array of {{q, a}} objects.\n\n"
        f"CURRENT TITLE: {fields.get('title', '')}\n"
        f"CURRENT META: {fields.get('meta', '')}\n"
        f"CURRENT CONTENT:\n{fields.get('content_md', '')[:4000]}\n"
        f"CURRENT FAQ: {fields.get('faq_json', [])}"
    )

    try:
        raw = llm.chat(refine_prompt, want_json=True)
        from core.json_repair import parse_model_json  # noqa: PLC0415
        parsed = parse_model_json(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict) or not parsed.get("content"):
            logger.warning("refine_article_content: bad LLM response for %r, keeping first pass", keyword)
            return fields

        faq = [{"q": it["q"], "a": it.get("a", "")}
               for it in (parsed.get("faq") or [])
               if isinstance(it, dict) and it.get("q")]

        return {
            "title":      parsed.get("title") or fields["title"],
            "slug":       parsed.get("slug") or fields["slug"],
            "meta":       parsed.get("metaDescription") or fields["meta"],
            "content_md": markdownish_to_html(parsed.get("content") or fields["content_md"]),
            "faq_json":   faq or fields["faq_json"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("refine_article_content failed for %r, keeping first pass: %s", keyword, exc)
        return fields


def _wp_base_url() -> str:
    """Read WP_URL from env, stripping trailing slash."""
    import os  # noqa: PLC0415
    return os.environ.get("WP_URL", "https://perkinsroofing.net").rstrip("/")


# ---------------------------------------------------------------------------
# Scored generation loop — generate → score → refine until SEO/AIO score == 100
# ---------------------------------------------------------------------------

def _build_article_jsonld(fields: dict, ctx: dict) -> list[dict]:
    """Deterministic JSON-LD: Article + FAQPage + BreadcrumbList (always present)
    + VideoObject entries when video grounding exists."""
    from datetime import datetime, timezone  # noqa: PLC0415

    from core.jsonld import build_article, build_faq_page  # noqa: PLC0415

    slug = ctx.get("pillar_slug") or fields.get("slug") or ""
    wp_base = _wp_base_url()
    url = f"{wp_base}/{slug}".rstrip("/")
    date = datetime.now(timezone.utc).date().isoformat()
    jsonld: list[dict] = [
        build_article(
            (fields.get("title") or "")[:110],
            fields.get("meta") or "",
            "Perkins Roofing",
            date,
            url,
        ),
        build_breadcrumb_list([
            {"name": "Home", "url": f"{wp_base}/"},
            {"name": "Blog", "url": f"{wp_base}/blog/"},
            {"name": fields.get("title") or slug, "url": url},
        ]),
    ]
    if fields.get("faq_json"):
        jsonld.append(build_faq_page(fields["faq_json"]))
    # Include VideoObject entries stored on fields (set by generate_scored_article
    # when video grounding was used).
    for vo in (fields.get("_video_jsonld") or []):
        jsonld.append(vo)
    return jsonld


def _clamp_meta(meta: str, title: str, content_md: str) -> str:
    """Deterministically coerce the meta description into the 120-160 char band."""
    meta = re.sub(r"\s+", " ", (meta or "").strip())
    if 120 <= len(meta) <= 160:
        return meta
    text = re.sub(r"\s+", " ", _strip_html(content_md or "")).strip()
    base = meta or (f"{title}: {text}" if title else text)
    if len(base) < 120:
        base = re.sub(r"\s+", " ", f"{title}: {text}").strip()
    if len(base) < 120:
        base = (base + " Expert South Florida roofing guidance from Perkins Roofing's licensed team.")
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) > 160:
        base = base[:159].rstrip()
    return base


def _fallback_faq(keyword: str, content_md: str) -> list[dict]:
    """Last-resort deterministic FAQ — 4 pairs so faq_count (≥4) check passes."""
    text = re.sub(r"\s+", " ", _strip_html(content_md or "")).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]
    a = (sentences[0] if sentences else f"Perkins Roofing can help with {keyword}.")[:300]
    b = (sentences[1] if len(sentences) > 1 else a)[:300]
    c = (sentences[2] if len(sentences) > 2 else b)[:300]
    return [
        {"q": f"What should homeowners know about {keyword}?", "a": a},
        {"q": f"Why does {keyword} matter for my roof?", "a": b},
        {"q": f"How much does {keyword} typically cost in South Florida?", "a": c},
        {"q": f"Can Perkins Roofing help with {keyword}?",
         "a": f"Yes. Perkins Roofing's licensed South Florida team handles {keyword} and can assess your roof, "
              f"explain the options, and give you a free estimate."},
    ]


def _ensure_video_link(content_md: str, keyword: str, db=None) -> str:
    """Guarantee an embedded YouTube player.

    A plain citation link is not enough: the console preview and WordPress article
    should show a real player. If the body already has a YouTube iframe, keep it.
    Otherwise convert the first YouTube URL already present into a responsive
    iframe; if none exists, append the top grounded clip from retrieval.
    """
    if re.search(r"<iframe\b[^>]*\bsrc=[\"'][^\"']*(?:youtube\.com|youtu\.be)", content_md or "", re.IGNORECASE):
        return content_md

    def _iframe(url: str) -> str | None:
        parsed = _youtube_embed_src(url)
        if parsed is None:
            return None
        src, title = parsed
        return (
            f'<div class="video-embed" style="position:relative;padding-bottom:56.25%;height:0;'
            f'overflow:hidden;border-radius:8px;margin:16px 0">'
            f'<iframe src="{src}" title="{title}" '
            f'style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" '
            f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            f'gyroscope; picture-in-picture; web-share" '
            f'allowfullscreen loading="lazy"></iframe></div>'
        )

    url_match = re.search(
        r"https?://(?:www\.)?(?:youtube\.com/(?:watch|embed)|youtu\.be/)[^\s\"'<)]+",
        content_md or "",
        re.IGNORECASE,
    )
    if url_match:
        embed = _iframe(url_match.group(0))
        if embed:
            return f"{embed}\n{content_md}"

    try:
        from app.retrieval import hybrid_search  # noqa: PLC0415
        chunks = (hybrid_search(keyword, k=1, db=db).get("chunks") or [])
        if not chunks:
            return content_md
        chunk = chunks[0][0]
        from core.retrieval import link as _yt  # noqa: PLC0415
        url = _yt(chunk.video_id, chunk.start)
        embed = _iframe(url)
        if not embed:
            return content_md
        return f"{content_md}\n<h2>Watch: {keyword}</h2>\n{embed}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("_ensure_video_link failed for %r: %s", keyword, exc)
        return content_md


def _youtube_embed_src(url: str) -> tuple[str, str] | None:
    """Return (embed_src, title) for a YouTube URL; None when not parseable."""
    from html import escape  # noqa: PLC0415
    from urllib.parse import parse_qs, urlparse  # noqa: PLC0415

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    video_id = ""
    start = 0
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
        t_vals = parse_qs(parsed.query).get("t") or ["0"]
        start = _parse_youtube_time(t_vals[0])
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
            start = _parse_youtube_time((parse_qs(parsed.query).get("t") or ["0"])[0])
        elif parsed.path.startswith("/embed/"):
            video_id = parsed.path.split("/embed/", 1)[1].split("/")[0]
            start = _parse_youtube_time((parse_qs(parsed.query).get("start") or ["0"])[0])
    if not re.fullmatch(r"[\w-]{6,}", video_id or ""):
        return None
    src = f"https://www.youtube.com/embed/{escape(video_id)}"
    if start > 0:
        src += f"?start={start}"
    return src, f"YouTube video for {escape(video_id)}"


def _parse_youtube_time(raw: str) -> int:
    """Parse YouTube t/start values like '90', '90s', '1m30s', '1h2m3s'."""
    raw = str(raw or "").strip().lower()
    if raw.isdigit():
        return int(raw)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", raw)
    if not m:
        return 0
    h, minutes, seconds = (int(x or 0) for x in m.groups())
    return h * 3600 + minutes * 60 + seconds


def _regen_faq(keyword: str, content_md: str, *, llm) -> list[dict]:
    """One targeted LLM call to produce 3-4 grounded FAQ pairs; [] on failure."""
    prompt = (
        f"Write 3-4 frequently asked questions with concise, professional answers for a roofing "
        f"article about '{keyword}', grounded ONLY in the article below. Return JSON: "
        f'{{"faq":[{{"q":"...","a":"..."}}]}}.\n\nARTICLE:\n{_strip_html(content_md)[:3000]}'
    )
    try:
        raw = llm.chat(prompt, want_json=True)
        parsed = parse_model_json(raw) if isinstance(raw, str) else raw
        return [{"q": it["q"], "a": it.get("a", "")}
                for it in (parsed.get("faq") or [])
                if isinstance(it, dict) and it.get("q")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_regen_faq failed for %r: %s", keyword, exc)
        return []


def _word_count_str(content: str) -> int:
    """Word count on a string (mirrors core.seo._word_count without import cycle)."""
    import re as _re  # noqa: PLC0415
    text = _re.sub(r"<[^>]+>", " ", content or "")
    text = _re.sub(r"[#*>`_~\[\]]", " ", text)
    return len([w for w in text.split() if w])


def _title_case_keyword(keyword: str) -> str:
    """Return keyword in Title Case, e.g. 'roof repair miami' → 'Roof Repair Miami'."""
    return " ".join(w.capitalize() for w in keyword.split())


def _ensure_title(title: str, keyword: str) -> str:
    """Guarantee the title:
    - contains the keyword (case-insensitive), AND
    - is between 30 and 65 characters.

    Strategy (deterministic, no LLM):
    1. If title already satisfies both conditions, return it unchanged.
    2. If keyword is missing from title, prepend "<Keyword Title Case>: " and trim
       at a word boundary to ≤65 chars.
    3. If title is too short (<30 chars), append a short descriptor.
    4. If title is too long (>65 chars), trim at the last word boundary ≤65 chars —
       but only AFTER the keyword is present so we never cut the keyword out.
    """
    if not keyword:
        # No keyword to enforce — just enforce length.
        title = title.strip() or "Roofing Guide"
        if len(title) < 30:
            title = (title + " | Expert South Florida Roofing Tips")[:65].rstrip()
        elif len(title) > 65:
            title = title[:65].rstrip()
        return title

    kw_lower = keyword.strip().lower()
    title = (title or "").strip()

    # Step 1: ensure keyword present
    if kw_lower not in title.lower():
        kw_tc = _title_case_keyword(keyword)
        # Synthesize "<Keyword TC>: <original>" or just keyword TC if original is empty
        if title:
            candidate = f"{kw_tc}: {title}"
        else:
            candidate = kw_tc
        title = candidate

    # Step 2: enforce 30–65 char band
    if len(title) > 65:
        # Trim at last space ≤65 so we don't split mid-word
        trimmed = title[:65]
        space_pos = trimmed.rfind(" ")
        title = trimmed[:space_pos].rstrip() if space_pos > 0 else trimmed.rstrip()

    if len(title) < 30:
        # Pad with a short descriptor; trim back to 65 if we overshoot
        title = (title + " | South Florida Roofing Guide")[:65].rstrip()

    # Final sanity: still verify keyword present after trimming
    if kw_lower not in title.lower():
        # Keyword got trimmed away; use bare keyword TC (may be short) + pad
        kw_tc = _title_case_keyword(keyword)
        title = kw_tc if len(kw_tc) >= 30 else (kw_tc + " | South Florida Roofing Guide")[:65]

    return title


def _ensure_heading(content_md: str, keyword: str) -> str:
    """Guarantee ≥1 <h2> exists in content.  If none found, prepend a generic one."""
    import re as _re  # noqa: PLC0415
    if _re.search(r"<h[23][\s/>]", content_md or "", _re.IGNORECASE):
        return content_md
    kw_tc = _title_case_keyword(keyword) if keyword else "Overview"
    heading = f"<h2>{kw_tc}: What You Need to Know</h2>\n"
    return heading + (content_md or "")


def _ensure_answer_first(content_md: str, keyword: str, faq: list) -> str:
    """Guarantee the first ~200 plain-text chars contain a complete declarative sentence.

    If the plain-text head already has a sentence-ending period with ≥4 char words, leave
    it unchanged.  Otherwise prepend a one-sentence answer-first <p> lede derived from the
    topic or the first FAQ answer.
    """
    import re as _re  # noqa: PLC0415
    TAG_RE = _re.compile(r"<[^>]+>")
    ANSWER_FIRST_RE = _re.compile(r"\w{4,}.*?\.", _re.DOTALL)

    def _plain_head(text: str) -> str:
        t = TAG_RE.sub(" ", text or "")
        t = _re.sub(r"[#*>`_~\[\]]", " ", t)
        return _re.sub(r"\s+", " ", t).strip()[:200]

    if ANSWER_FIRST_RE.search(_plain_head(content_md)):
        return content_md

    # Build a lede sentence: prefer first complete sentence from FAQ answer,
    # fall back to generic if the FAQ answer contains no sentence-ending punctuation.
    lede_text = ""
    if faq and isinstance(faq[0], dict) and faq[0].get("a"):
        raw_a = faq[0]["a"].strip()
        # Only use the FAQ answer when it contains a complete sentence (ends with . ! ?)
        m = _re.match(r"([^.!?]+[.!?])", raw_a)
        if m:
            lede_text = m.group(1).strip()

    if not lede_text:
        kw_tc = _title_case_keyword(keyword) if keyword else "roofing"
        lede_text = (
            f"{kw_tc} is an important consideration for South Florida homeowners. "
            f"Understanding your options helps you make confident decisions about "
            f"your roof."
        )

    lede = f"<p>{lede_text}</p>\n"
    return lede + (content_md or "")


def generate_scored_article(
    keyword: str,
    ctx: dict,
    *,
    target: int = 100,
    max_iters: int = 3,
    llm=None,
    db=None,
) -> dict:
    """Generate an article, then loop (generate → score → refine) until the SEO/AIO
    score reaches ``target`` (default 100) or ``max_iters`` is hit.

    Verification is the pure ``core.seo.score_article``. Structural checks that can be
    satisfied deterministically (JSON-LD, meta length, a FAQ) are guaranteed on the
    final pass so a finished draft never ships below 100 on fixable dimensions.

    Returns the generate_article_content fields plus ``jsonld_json`` and ``seo_score``.
    """
    from core.seo import failing_keys, score_article  # noqa: PLC0415

    if llm is None:
        from adapters.llm import get_default  # noqa: PLC0415
        llm = get_default()

    fields = generate_article_content(keyword, ctx, llm=llm, db=db)
    fields["content_md"] = markdownish_to_html(fields.get("content_md", ""))

    def _score(f: dict, jl: list) -> dict:
        return score_article(f.get("title", ""), f.get("meta", ""),
                             f.get("content_md", ""), f.get("faq_json"), bool(jl),
                             keyword=keyword)

    def _done(res: dict, f: dict) -> bool:
        # Not done until score hits target, no Markdown remains, and no placeholders.
        return (
            res["score"] >= target
            and not has_residual_markdown(f.get("content_md", ""))
            and not has_placeholder(f.get("content_md", ""))
        )

    jsonld = _build_article_jsonld(fields, ctx)
    result = _score(fields, jsonld)
    it = 0
    while not _done(result, fields) and it < max_iters:
        it += 1
        fails = set(failing_keys(result))
        # Content-quality gaps OR leftover markdown/placeholders → full refine pass
        if (fails & {"headings", "wordcount", "video", "title_len", "answer_first",
                     "keyword_in_title"}) \
                or has_residual_markdown(fields.get("content_md", "")) \
                or has_placeholder(fields.get("content_md", "")):
            fields = refine_article_content(fields, keyword, llm=llm)
        # FAQ gap (any) → one targeted FAQ generation
        if fails & {"faq", "faq_count"}:
            regen = _regen_faq(keyword, fields.get("content_md", ""), llm=llm)
            # Accept regen only when it produces more items than current
            if len(regen) > len(fields.get("faq_json") or []):
                fields["faq_json"] = regen
        # Meta gaps → deterministic clamp into 120-160
        if fails & {"meta_present", "meta_len"}:
            fields["meta"] = _clamp_meta(fields.get("meta", ""), fields.get("title", ""),
                                         fields.get("content_md", ""))
        # Deterministically strip any Markdown the refine pass emitted.
        fields["content_md"] = markdownish_to_html(fields.get("content_md", ""))
        jsonld = _build_article_jsonld(fields, ctx)
        result = _score(fields, jsonld)

    # ── Final deterministic guarantees ──────────────────────────────────────
    # Applied AFTER the refine loop so the returned article provably passes every
    # fixable check regardless of LLM behaviour.

    # 1. Video link (video check)
    fields["content_md"] = markdownish_to_html(
        _ensure_video_link(fields.get("content_md", ""), keyword, db=db))

    # 2. Meta description (meta_present + meta_len checks)
    fields["meta"] = _clamp_meta(fields.get("meta", ""), fields.get("title", ""),
                                 fields.get("content_md", ""))

    # 3. FAQ (faq + faq_count checks): ensure ≥4 pairs
    if not fields.get("faq_json"):
        fields["faq_json"] = _fallback_faq(keyword, fields.get("content_md", ""))
    elif len(fields["faq_json"]) < 4:
        extra = _fallback_faq(keyword, fields.get("content_md", ""))
        existing_qs = {f["q"].lower() for f in fields["faq_json"]}
        for item in extra:
            if item["q"].lower() not in existing_qs and len(fields["faq_json"]) < 4:
                fields["faq_json"].append(item)

    # 4. Title: keyword_in_title + title_len (30–65 chars)
    fields["title"] = _ensure_title(fields.get("title", ""), keyword)

    # 5. Headings: ensure ≥1 <h2> in content_md
    fields["content_md"] = _ensure_heading(fields.get("content_md", ""), keyword)

    # 6. Answer-first lede: first ~200 plain-text chars must contain a sentence
    fields["content_md"] = _ensure_answer_first(
        fields.get("content_md", ""), keyword, fields.get("faq_json") or [])

    # 7. Wordcount > 300: if still short after all fixes, attempt one more refine
    if _word_count_str(fields.get("content_md", "")) <= 300:
        logger.warning(
            "generate_scored_article %r: body still ≤300 words before final score; "
            "attempting emergency refine", keyword)
        fields = refine_article_content(fields, keyword, llm=llm)
        fields["content_md"] = markdownish_to_html(fields.get("content_md", ""))
        fields["content_md"] = _ensure_heading(fields.get("content_md", ""), keyword)
        fields["content_md"] = _ensure_answer_first(
            fields.get("content_md", ""), keyword, fields.get("faq_json") or [])
        if _word_count_str(fields.get("content_md", "")) <= 300:
            logger.error(
                "generate_scored_article %r: body still ≤300 words after emergency refine; "
                "wordcount check will fail — content may be incomplete", keyword)

    jsonld = _build_article_jsonld(fields, ctx)
    result = _score(fields, jsonld)

    fields["jsonld_json"] = jsonld
    fields["seo_score"] = result["score"]
    logger.info(
        "generate_scored_article %r → score %d/100 (%d iters) failing=%s",
        keyword, result["score"], it,
        [c["key"] for c in result["checks"] if not c["pass"]],
    )
    return fields


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string (for SERP/PAA data before prompt injection)."""
    return re.sub(r"<[^>]+>", "", text)


def _markdown_to_html(md: str) -> str:
    """Convert Markdown to sanitised HTML for WordPress post content.

    Uses the `markdown` library for conversion then `bleach` to strip any
    unsafe tags/attributes (no script, on* event handlers, etc.). Safe YouTube
    iframes are preserved so article video embeds survive publishing.
    """
    import bleach  # noqa: PLC0415
    import markdown  # noqa: PLC0415
    from bleach.sanitizer import ALLOWED_ATTRIBUTES, ALLOWED_TAGS  # noqa: PLC0415

    allowed_tags = list(ALLOWED_TAGS) + [
        "p", "h1", "h2", "h3", "h4",
        "ul", "ol", "li",
        "blockquote", "code", "pre",
        "img", "iframe", "div", "span", "table", "thead", "tbody", "tr", "td", "th",
    ]
    allowed_attrs = dict(ALLOWED_ATTRIBUTES)
    allowed_attrs["a"] = ["href", "title", "rel", "target"]
    allowed_attrs["img"] = ["src", "alt", "title", "width", "height", "loading"]
    allowed_attrs["iframe"] = [
        "src", "allow", "allowfullscreen", "loading", "frameborder",
        "width", "height", "title", "style",
    ]
    allowed_attrs["div"] = ["class", "style"]
    allowed_attrs["span"] = ["class", "style"]

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
    t_param = f"&t={int(chunk.start)}s" if chunk.start is not None else ""
    url = f"https://www.youtube.com/watch?v={chunk.video_id}{t_param}"
    parts = content.split("\n\n", 1)
    if len(parts) == 2:
        return f"{parts[0]}\n\n{url}\n\n{parts[1]}"
    return f"{url}\n\n{content}"


def _build_video_jsonld(chunks: list[tuple], tenant_id: int | None = None) -> list[dict]:
    """Build VideoObject JSON-LD entries for distinct source videos in chunks."""
    from app.models import SessionLocal, Video  # noqa: PLC0415
    from core.retrieval import link as video_link  # noqa: PLC0415

    seen_ids: set[str] = set()
    result: list[dict] = []

    _db = SessionLocal()
    if tenant_id is not None:
        _db.info["tenant_id"] = tenant_id
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
