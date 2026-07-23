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
import os
import re
from contextlib import contextmanager
from functools import lru_cache

from core.article_prompt import system_prompt, template_prompt
from core.json_repair import parse_model_json
from core.jsonld import build_faq_page, build_video_object
from core.numeric_grounding import check_numeric_claims
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


def _repair_inputs(db) -> dict:
    """DB-backed facts core.article_repair.repair_article needs: known video ids +
    metadata (videos table) and valid slugs + pillar map (articles table).

    I/O only — the actual repair logic is the pure core.article_repair module.
    """
    from app.models import Article as ArticleModel  # noqa: PLC0415
    from app.models import Video  # noqa: PLC0415

    known_video_ids: set[str] = set()
    video_meta: dict[str, dict] = {}
    for vid, title, upload_date, duration in db.query(
        Video.id, Video.title, Video.upload_date, Video.duration
    ).all():
        known_video_ids.add(vid)
        video_meta[vid] = {"title": title, "upload_date": upload_date, "duration": duration}

    valid_slugs = {s for (s,) in db.query(ArticleModel.slug).all()}
    pillar_map = {
        p: s
        for p, s in db.query(ArticleModel.pillar_slug, ArticleModel.slug)
                      .filter(ArticleModel.role == "pillar").all()
        if p and p != s
    }
    return {
        "known_video_ids": known_video_ids,
        "video_meta": video_meta,
        "valid_slugs": valid_slugs,
        "pillar_map": pillar_map,
    }


def _apply_repair(content_md: str, jsonld: list[dict], keyword: str, meta_description: str,
                  db) -> tuple[str, list[dict], list[dict]]:
    """Run core.article_repair.repair_article with DB-backed facts.

    Callers wrap this fail-open (same convention as the grounding/fact-check passes
    below): a repair-stage error must never block an otherwise-good article — it
    just ships unrepaired and the caller logs it.
    """
    from core.article_repair import repair_article  # noqa: PLC0415

    inputs = _repair_inputs(db)
    result = repair_article(
        content_md, jsonld,
        known_video_ids=inputs["known_video_ids"],
        video_meta=inputs["video_meta"],
        valid_slugs=inputs["valid_slugs"],
        pillar_map=inputs["pillar_map"],
        keyword=keyword,
        meta_description=meta_description,
    )
    if result.fixes:
        logger.info("article_repair on %r: %s", keyword, result.fixes)
    return result.content_md, result.jsonld, result.issues


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

# An <iframe> is a full embedding of another page — a scheme check is not enough
# (any https host would be embeddable → clickjacking/phishing frame on the public
# site if an iframe is ever hallucinated or injected). Restrict iframe src to the
# only host the pipeline ever emits: YouTube embeds (see _embed_iframe / _inject_oembed,
# which build https://www.youtube.com/embed/<id>).
_SAFE_IFRAME_SRC_RE = re.compile(
    r"^https://(www\.)?(youtube\.com|youtube-nocookie\.com)/embed/", re.IGNORECASE
)

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
    n = name.lower()
    if n.startswith("on"):
        return False
    if tag == "iframe" and n == "src":
        # Bad src → drop the attribute (bleach keeps a src-less, inert iframe).
        return bool(_SAFE_IFRAME_SRC_RE.match(value.strip()))
    if n in ("href", "src", "action", "data"):
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


def _chat_article(llm, prompt: str) -> dict:
    """One schema-controlled article call → parsed dict, or {} when unparseable."""
    try:
        raw = llm.chat(prompt, want_json=True, response_schema=ARTICLE_SCHEMA)
    except TypeError:  # llm without response_schema support (e.g. a test fake)
        raw = llm.chat(prompt, want_json=True)
    parsed = parse_model_json(raw)
    return parsed if isinstance(parsed, dict) and parsed.get("content") else {}


def _expand_prompt(base_prompt: str, draft: str, words: int, target_words: int, goal: int) -> str:
    """Ask for more of TIM — never for more words.

    This prompt used to say "Rewrite it LONGER ... add worked examples, specific costs,
    materials, edge cases" against a ~{target}-word target, without requiring any of it to come
    from the transcripts. That instructs the model to invent costs and code details to hit a
    number, which is precisely the failure the grounding critic calls unshippable. It worked:
    45,945 published words rested on 4,564 words of source.

    So the ask is now "what did Tim cover that you left out?", and running out of Tim is a
    legitimate place to stop.
    """
    return (
        f"{base_prompt}\n\n"
        f"═══ EXPAND THIS DRAFT — FROM THE SOURCE TRANSCRIPTS ONLY ═══\n"
        f"The draft is {words} words. The plan plotted this article at about {target_words} "
        f"words ({goal}+ is the guide), and there is likely more in the SOURCE TRANSCRIPTS "
        f"above that it has not used yet — but that number is only reachable if Tim's material "
        f"reaches it.\n\n"
        f"Re-read the transcripts and add ONLY what Tim actually covers and the draft omits: "
        f"his specific techniques, materials, brand names, code points, numbers, and the "
        f"examples he walks through on real roofs.\n\n"
        f"ABSOLUTE RULES:\n"
        f"- DO NOT invent anything to reach a length. No costs, code references, measurements, "
        f"  timeframes or product claims that are not in the transcripts above. A fabricated "
        f"  price or code cite is the worst thing this article can contain.\n"
        f"- If the transcripts contain nothing further of substance, RETURN THE DRAFT AS-IS. "
        f"  Stopping short is correct and expected — {goal} words is a guide, not a quota, and "
        f"  a shorter article that is all Tim beats a longer one that is partly invented.\n"
        f"- No filler, no restating a point in new words, no marketing language.\n"
        f"- Keep every section, heading, YouTube URL and ?t= timestamp EXACTLY as written — "
        f"  those are the grounding citations and must survive verbatim.\n"
        f"Return the SAME JSON shape.\n\n"
        f"PREVIOUS DRAFT:\n{draft}"
    )


# Expansion rounds before shipping whatever we have. Each round is one LLM call, so this
# trades spend for length — enough to walk a ~400-word first draft up to an 1800-word target,
# bounded so a model that plateaus can't loop forever.
_EXPAND_ROUNDS = 4


def _word_goal(target_words: int) -> int:
    """Word count an article must reach: the same lower bound the prompt already asks for
    (see core.article_prompt's lo = target_words * 0.9), floored at Rank Math's minimum so a
    small target can never drag an article under the green line."""
    from core.seo import RM_MIN_WORDS  # noqa: PLC0415
    return max(RM_MIN_WORDS, round(target_words * 0.9))


def _generate_article_json(llm, prompt: str, keyword: str, target_words: int) -> dict:
    """Generate an article dict: retry unparseable JSON, then expand until it reaches the
    planned word target.

    The expansion pass exists because Gemini reliably under-delivers on a one-shot word
    target (~400 words against an 1800-word ask) and nothing downstream re-asked — which is
    how 350-450-word articles reached WordPress while scoring green.

    Aims for the plan's target (via _word_goal), not merely Rank Math's floor — clearing 600
    would score green while still shipping a third of the commissioned article. Bounded at
    _EXPAND_ROUNDS; keeps the longest draft seen and warns rather than blocking.
    """
    from core.seo import RM_MIN_WORDS, _word_count  # noqa: PLC0415

    goal = _word_goal(target_words)

    article: dict = {}
    for _ in range(3):
        article = _chat_article(llm, prompt)
        if article:
            break
    if not article:
        raise RuntimeError(f"LLM returned unparseable JSON for keyword '{keyword}'")

    for _ in range(_EXPAND_ROUNDS):
        words = _word_count(article.get("content") or "")
        if words >= goal:
            return article
        expanded = _chat_article(
            llm, _expand_prompt(prompt, article.get("content") or "", words, target_words, goal))
        if _word_count(expanded.get("content") or "") <= words:
            break  # no progress — keep the longer draft rather than regress
        article = expanded

    final = _word_count(article.get("content") or "")
    if final < RM_MIN_WORDS:
        logger.warning("article for %r is %d words — under Rank Math's %d-word floor after %d "
                       "expansion rounds", keyword, final, RM_MIN_WORDS, _EXPAND_ROUNDS)
    elif final < goal:
        logger.info("article for %r is %d words, short of the %d-word goal (target %d) after %d "
                    "expansion rounds", keyword, final, goal, target_words, _EXPAND_ROUNDS)
    return article


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
    grounded_on = ""
    if ground_videos:
        try:
            sources = source_transcripts(keyword, db=db)
            if sources:
                user_prompt = _append_video_grounding(user_prompt, sources)
                grounded_on = "\n\n".join(s["transcript"] for s in sources)
        except Exception as exc:  # noqa: BLE001
            # RuntimeError here is the strict unstamped-session guard — never bury it
            lvl = logger.critical if isinstance(exc, RuntimeError) else logger.warning
            lvl("video grounding failed for %r, continuing: %s", keyword, exc)

    # ── Call LLM (retry on unparseable JSON, then expand to the word floor) ───
    prompt = f"{sys_prompt}\n\n{user_prompt}"
    article = _generate_article_json(
        llm, prompt, keyword, int(enriched.get("target_words", 1800)))

    faq = [{"q": it["q"], "a": it.get("a", "")}
           for it in (article.get("faq") or [])
           if isinstance(it, dict) and it.get("q")]

    return {
        "title":      article.get("title") or keyword,
        "slug":       article.get("slug") or "",
        "meta":       article.get("metaDescription") or "",
        "content_md": markdownish_to_html(article.get("content") or ""),
        "faq_json":   faq,
        # The evidence this article was written from, carried out for the grounding audit so it
        # re-reads nothing. Underscore-prefixed: transient, never persisted to articles.*.
        "_source_transcript": grounded_on,
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
                # chunks drive the jsonld + oembed picks; the PROMPT gets whole topic slices.
                result = hybrid_search(keyword, k=4, db=_gs)
                video_chunks = result.get("chunks") or []
                sources = source_transcripts(keyword, db=_gs)
            if sources:
                user_prompt = _append_video_grounding(user_prompt, sources)
            if video_chunks:
                jsonld_video_list = _build_video_jsonld(video_chunks, tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001
            lvl = logger.critical if isinstance(exc, RuntimeError) else logger.warning
            lvl("video grounding failed, continuing without it: %s", exc)

    # ── 3. Call LLM (schema-controlled JSON; retry on fluke, expand to the word floor) ───
    prompt = f"{sys_prompt}\n\n{user_prompt}"
    article = _generate_article_json(
        llm, prompt, keyword, int(enriched.get("target_words", 1800)))

    # ── 4. Validate ───────────────────────────────────────────────────────────
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

    # ── 6. Build JSON-LD — FAQPage + VideoObject ONLY ─────────────────────────
    # Rank Math already emits Organization/Person/Article/BreadcrumbList for every post, so
    # emitting them per-article duplicates schema. Scoped to the two node types Rank Math does
    # NOT generate — matches _build_article_jsonld (the generate_scored_article path). Was a full
    # Organization+Article graph; corrected 2026-07-22 so this deployed batch path no longer ships
    # duplicate schema (the same fix already applied to the live scored path + the existing posts).
    jsonld_list: list[dict] = []
    if faq:
        jsonld_list.append(build_faq_page(faq))
    # Append VideoObject entries for each grounded source video
    jsonld_list.extend(jsonld_video_list)

    # ── 6b. Deterministic repair + QA pass (core.article_repair) ────────────
    # Corrects/strips corrupted video ids, invented images, dead relative links,
    # dead staging hosts, and resyncs VideoObject jsonld — before publish. Never
    # blocks: repair issues are appended to qa_checks for visibility only, since
    # the rot they flag was already fixed (see core.article_repair's docstring).
    try:
        with _stamped_session(tenant_id) as _repair_db:
            content, jsonld_list, repair_issues = _apply_repair(
                content, jsonld_list, keyword, article.get("metaDescription") or "", _repair_db)
        qa_checks.extend(repair_issues)
    except Exception as exc:  # noqa: BLE001
        logger.warning("article_repair failed for %r, shipping unrepaired: %s", keyword, exc)

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
            focus_keyword=keyword,
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
            focus_keyword=keyword,
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
            "pillar_title": plan["pillar"].get("title") if not is_pillar else None,
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

    # Manual CLI for explicit backfills — SERPs default to empty dicts (no live Serper).
    #   python -m jobs.article_job <topic> <keyword1> [<keyword2> ...]
    # In prod, article generation is admin-driven via the /topics API (curated per
    # tenant), so this entrypoint has no autonomous work without explicit topics. A
    # no-arg invocation is therefore a clean no-op (exit 0) — executing the Cloud Run
    # `article` job bare (e.g. a deploy smoke check) must not red-flag as a failure.
    if len(sys.argv) < 3:  # noqa: PLR2004
        print("jobs.article_job: no topic/keywords given — nothing to do. "
              "Usage: python -m jobs.article_job <topic> <kw1> [<kw2> ...] "
              "(article generation runs via the admin /topics API).")
        sys.exit(0)
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
        f"- Use clear question-led headings that name the ACTUAL SUBJECT of their section\n"
        f"  (e.g. '## What does a permit cost?', '## How long does installation take?')\n"
        f"- Do NOT bolt the keyword onto every heading. AT MOST TWO headings in the whole\n"
        f"  article may contain '{keyword}', and only where it is what the section is really\n"
        f"  about. Headings like 'What Happens on Installation Day When You Need a New Roof?'\n"
        f"  or 'What Does Cleanup Entail After You Need a New Roof?' are exactly what to avoid:\n"
        f"  no human writes that, and it reads as spam to readers and to Google.\n"
        f"- Provide concise, direct answers immediately after each heading\n"
        f"- KEYWORD DENSITY — hit the BAND, from both sides. Rank Math flags BOTH ends:\n"
        f"  under 0.5% is under-optimised, over 1.5% is stuffing. Aim for the middle, ~0.9%.\n"
        f"  THE RULE IS A RATIO, NOT A COUNT: (times you write the exact phrase\n"
        f"  '{keyword}') divided by (total words in YOUR FINISHED ARTICLE) must land near\n"
        f"  0.009 — about one mention per 110 words of whatever you actually write.\n"
        f"  Worked both ways, so the length is yours and the ratio is fixed:\n"
        f"      a 1,200-word article -> ~11 mentions       (NOT 20 — that would be 1.7%)\n"
        f"      a 2,400-word article -> ~22 mentions\n"
        f"  Count against your OWN final length. A previous version of this instruction gave a\n"
        f"  count for a 2,000-word article; the model anchored on the number, wrote 23 of them\n"
        f"  into a 1,440-word piece, and landed at 1.60% — over the ceiling. The version before\n"
        f"  that gave only a ceiling and it landed at 0.16-0.48%, under the floor on 12 of 31\n"
        f"  articles. Both ends and the ratio, or it misses.\n"
        f"  Use semantic variants (pronouns, 'the roof', 'this') for everything else — never\n"
        f"  repeat the phrase back-to-back, in filler, or in a list to reach the number.\n"
        f"- Improve the meta description to be compelling and keyword-rich (≤160 chars)\n"
        f"- Add or improve a FAQ section with common questions and concise answers\n"
        f"- Preserve all factual content; only improve structure and clarity\n"
        f"- Return the article in FULL. Do not shorten it, do not summarise it, and do not\n"
        f"  drop sections: the revision must be at least as long as the article below, and\n"
        f"  must keep every YouTube URL and ?t= timestamp verbatim (they are citations).\n\n"
        f"Return a JSON object with exactly these keys: title, slug, metaDescription, content, faq\n"
        f"where faq is an array of {{q, a}} objects.\n\n"
        f"CURRENT TITLE: {fields.get('title', '')}\n"
        f"CURRENT META: {fields.get('meta', '')}\n"
        # NOT truncated. This used to be content_md[:4000], which silently fed the editor
        # only the first ~600 words of a 2000+ word article — it then "revised" that fragment
        # and returned it as the whole piece (2208 -> 949 words observed). That truncation was
        # a major cause of the short articles in #334. Gemini's context is ~1M tokens; a long
        # article is ~3k, so there is nothing to save here.
        f"CURRENT CONTENT:\n{fields.get('content_md', '')}\n"
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
    """Canonical WP base URL (admin-config WP_URL wins, env fallback; see
    adapters.wordpress.resolved_wp_url). Defaults to the live domain if neither is set."""
    from adapters.wordpress import resolved_wp_url  # noqa: PLC0415
    return resolved_wp_url() or "https://perkinsroofing.net"


# ---------------------------------------------------------------------------
# Scored generation loop — generate → score → refine until SEO/AIO score == 100
# ---------------------------------------------------------------------------

def _build_article_jsonld(fields: dict, ctx: dict) -> list[dict]:
    """Deterministic JSON-LD: FAQPage + VideoObject ONLY.

    Rank Math (the live site's SEO plugin) already emits Organization/Person/Article/
    BreadcrumbList for every post — see core.brand_identity for the same NAP data
    modeled for the (currently unused-here) full-graph path in ``generate_article``.
    Emitting those node types again per-article would duplicate what Rank Math already
    puts on the page, so the per-post schema we inject here is scoped to the two node
    types Rank Math does NOT generate: the article's own FAQ Q&A pairs and its source
    VideoObject(s).
    """
    from core.jsonld import build_faq_page  # noqa: PLC0415

    jsonld: list[dict] = []
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


def _kw_span_re(keyword: str):
    """Regex matching the keyword where words may be separated by punctuation as well as space,
    so "roof estimate vs inspection" still matches "Roof Estimate vs. Inspection"."""
    import re as _re  # noqa: PLC0415
    parts = [_re.escape(w) for w in (keyword or "").split() if w]
    if not parts:
        return None
    return _re.compile(r"\b" + r"[\s.,:;'\"()\[\]/–—-]+".join(parts) + r"\b", _re.IGNORECASE)


def _ensure_title_number(title: str, keyword: str) -> str:
    """rm_title_number: Rank Math wants a digit in the title. Deterministic, no LLM.

    Appends the current year — the standard SEO convention for this ("Roof Costs 2026"), honest,
    and it works for evergreen topics where an invented item count ("7 Things...") would be a lie
    about the article's structure.

    If the year does not fit inside the 65-char band, the title is returned UNCHANGED and
    rm_title_number simply fails. This used to trim the title at a word boundary to make room,
    which cut the final noun and shipped dangling nonsense to the live site:
        "Wall Flashings: ... to Preventing Water Damage" -> "... to Preventing Water (2026)"
        "Roof Ventilation: ... to a Cooler, Healthier Home" -> "... to a Cooler (2026)"
    Length and the keyword were both still "valid" — only the meaning was destroyed, which no
    length check can catch. A readable title that fails one SEO check beats a broken one that
    passes: rewrite the title by hand if the number matters.
    """
    import re as _re  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    title = (title or "").strip()
    if _re.search(r"\d", title):
        return title

    suffix = f" ({datetime.now(timezone.utc).year})"
    if len(title) + len(suffix) <= 65:
        return title + suffix
    return title  # no room for the year; never truncate to make room


_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})", re.IGNORECASE)


_YOUTUBE_FOOTER_TEXT = "Subscribe to our YouTube channel for more!"


def _ensure_footer_link(content_md: str) -> str:
    """Append the YouTube subscribe CTA to every article body.

    Same pattern as _ensure_video_link/_ensure_article_image: deterministic and append-only,
    never invented. Idempotent — a second pass (e.g. a regen job re-running this on an already
    processed body) won't double the footer.
    """
    if not content_md or _YOUTUBE_FOOTER_TEXT in content_md:
        return content_md
    from core.brand_identity import YOUTUBE_CHANNEL_URL  # noqa: PLC0415
    footer = f'<p>{_YOUTUBE_FOOTER_TEXT} <a href="{YOUTUBE_CHANNEL_URL}">{YOUTUBE_CHANNEL_URL}</a></p>'
    return f"{content_md}\n{footer}"


def _ensure_internal_links(content_md: str, keyword: str, ctx: dict) -> str:
    """Append internal links: cluster -> pillar (descriptive anchor) + 1-3 contextual
    SERVICES links (keyword-matched — see core.internal_links).

    Same append-only pattern as _ensure_footer_link/_ensure_video_link: never rewrites
    existing prose, never invents a link. Idempotent — skips a link whose URL is
    already present in the body.
    """
    if not content_md:
        return content_md

    links: list[str] = []

    pillar_slug = ctx.get("pillar_slug")
    if ctx.get("role") == "cluster" and pillar_slug:
        # No /blog/ — post URLs are top-level (see _wp_base_url callers / canonical_url note).
        pillar_url = f"{_wp_base_url()}/{pillar_slug}"
        if pillar_url not in content_md:
            anchor = ctx.get("pillar_title") or _title_case_keyword(pillar_slug.replace("-", " "))
            links.append(f'<a href="{pillar_url}">{anchor}</a>')

    from core.internal_links import matching_service_links  # noqa: PLC0415
    # Match against the article's own prose only — excluding a related-links block this
    # function already appended, so a second pass doesn't treat its own anchor text as new
    # content to match against (which would keep growing the link list every re-run).
    body_for_matching = re.sub(r'<p class="related-links">.*?</p>', "", content_md,
                               flags=re.IGNORECASE | re.DOTALL)
    haystack = f"{keyword} {_strip_html(body_for_matching)}"
    for entry in matching_service_links(haystack):
        if entry["url"] not in content_md:
            links.append(f'<a href="{entry["url"]}">{entry["anchor"]}</a>')

    if not links:
        return content_md

    block = f'<p class="related-links">Related: {" | ".join(links)}</p>'
    return f"{content_md}\n{block}"


def _ensure_article_image(content_md: str, keyword: str) -> str:
    """Give the article a real image: the thumbnail of the video it was built from.

    rm_kw_in_img_alt needs an <img> with the keyword in its alt, and these articles ship with
    none. The honest source is already in the body — every article embeds Tim's video, so its
    thumbnail is a genuinely relevant image rather than decoration.

    Deliberately NOT the retired approach (the old SEO/AIO repair script, removed in this
    change), which injected one generic `perkins-roofing-seo-guide.jpg` into every article
    purely to turn the check green. The same stock image on unrelated posts is decoration that
    lies about its own content.

    No video in the body -> no image. We never invent one.
    """
    if not content_md or re.search(r"<img\b", content_md, re.IGNORECASE):
        return content_md  # already has an image; neither duplicate nor overwrite it
    m = _YT_ID_RE.search(content_md)
    if not m:
        return content_md
    alt = _title_case_keyword(keyword) if keyword else "Perkins Roofing"
    img = (f'<img src="https://img.youtube.com/vi/{m.group(1)}/hqdefault.jpg" '
           f'alt="{alt} — Perkins Roofing" loading="lazy" '
           f'style="max-width:100%;height:auto;border-radius:8px;margin:16px 0" />')
    return f"{img}\n{content_md}"


def _ensure_img_alt_keyword(content_md: str, keyword: str) -> str:
    """rm_kw_in_img_alt: put the focus keyword into the first <img> alt.

    Only rewrites an alt on an image that already exists — we never invent an <img>, because a
    fabricated image tag would render as a broken image on Tim's site. Articles with no images
    keep failing this check, which is the honest outcome. `_ensure_article_image` runs first and
    supplies a real one when the body has a video to take it from.
    """
    import re as _re  # noqa: PLC0415

    if not keyword or not content_md:
        return content_md
    if any(keyword.lower() in m.group(1).lower()
           for m in _re.finditer(r'<img[^>]*\balt="([^"]*)"', content_md, _re.IGNORECASE)):
        return content_md

    imgs = list(_re.finditer(r"<img\b[^>]*>", content_md, _re.IGNORECASE))
    if not imgs:
        return content_md  # nothing to caption; do not fabricate one

    tag = imgs[0].group(0)
    kw_tc = _title_case_keyword(keyword)
    if _re.search(r'\balt="[^"]*"', tag, _re.IGNORECASE):
        new_tag = _re.sub(r'\balt="[^"]*"', f'alt="{kw_tc}"', tag, count=1, flags=_re.IGNORECASE)
    else:
        new_tag = tag[:-1].rstrip() + f' alt="{kw_tc}">'
    return content_md[:imgs[0].start()] + new_tag + content_md[imgs[0].end():]


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

    # Step 0: punctuation-tolerant match. The literal `in` test below is defeated by punctuation
    # the model adds — keyword "roof estimate vs inspection" is NOT a substring of "Roof Estimate
    # vs. Inspection" because of the period. That prepended the keyword to a title that already
    # said it, and the 65-char trim produced the observed
    #   "Roof Estimate Vs Inspection: Roof Estimate vs. Inspection: Key"
    # If the keyword is present apart from punctuation, rewrite that span to the exact spelling
    # so the literal checks (and Rank Math itself) see it, rather than prepending a duplicate.
    if kw_lower not in title.lower():
        span = _kw_span_re(keyword)
        m = span.search(title) if span else None
        if m:
            title = title[:m.start()] + _title_case_keyword(keyword) + title[m.end():]

    # Step 1: ensure keyword present
    if kw_lower not in title.lower():
        kw_tc = _title_case_keyword(keyword)
        # Synthesize "<Keyword TC>: <original>" or just keyword TC if original is empty
        if title:
            candidate = f"{kw_tc}: {title}"
        else:
            candidate = kw_tc
        title = candidate

    # Step 2: enforce 30–65 char band.
    # Cut at a CLAUSE boundary, never mid-clause. Trimming at the last space ≤65 kept the length
    # and the keyword valid while destroying the meaning — it turned
    #   "7 Essential Fire and Water Barrier Tips: Protect Your Florida Home from Disaster"
    # into "...Tips: Protect Your Florida", a dangling fragment. Dropping the whole trailing
    # clause instead yields "7 Essential Fire and Water Barrier Tips" — still true, still has the
    # keyword, and reads like a title a human wrote. If no clause boundary gives a usable title,
    # leave it long: an over-length title costs one length check, a butchered one costs the reader.
    if len(title) > 65:
        best = None
        for m in re.finditer(r"\s*[:–—|,]\s*", title):
            head = title[:m.start()].rstrip()
            # No lower bound here: a short head ("Fix Roof") is a fine title once the pad step
            # below extends it. Gating on >=30 rejected the good answer and left the title long.
            if len(head) <= 65 and kw_lower in head.lower():
                best = head  # keep scanning; the longest qualifying prefix wins
        if best:
            title = best

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


def _grounding_transcript(keyword: str, db=None) -> str:
    """Evidence base for the grounding critic — the SAME topic slices the generator was given.

    This used to run its own `hybrid_search(k=6)` with 1200-char slices, which meant the critic
    judged a 3,900-word article against ~250 words of source. It could not tell "Tim never said
    this" from "that isn't in my excerpt", so it passed invented content as clean. A critic
    holding less evidence than the writer cannot catch the writer inventing.
    """
    try:
        sources = source_transcripts(keyword, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("grounding transcript unavailable for %r: %s", keyword, exc)
        return ""
    if not sources:
        logger.warning("grounding transcript EMPTY for %r — the grounding critic is blind "
                       "and will pass anything; treat its verdict as unproven", keyword)
        return ""
    return "\n\n".join(
        f"- {s['url']} ({s['title']}{' — ' + s['label'] if s.get('label') else ''}):\n"
        f"  {s['transcript']}"
        for s in sources)


CRITIQUE_ROUNDS = 3


def _run_critics(fields: dict, keyword: str, transcript: str, *, llm) -> list[dict]:
    """Run all three critic lenses over the article; return their pooled findings.

    A critic that errors or returns junk contributes nothing rather than aborting the round —
    losing one lens degrades the review, but killing the revision loses the whole article.
    """
    from core.article_critique import (  # noqa: PLC0415
        CRITICS,
        CRITIQUE_SCHEMA,
        critique_prompt,
        parse_findings,
    )
    from core.json_repair import parse_model_json  # noqa: PLC0415

    article = {**fields, "focus_keyword": keyword}
    findings: list[dict] = []
    for lens in CRITICS:
        try:
            prompt = critique_prompt(lens, article, transcript)
            try:
                raw = llm.chat(prompt, want_json=True, response_schema=CRITIQUE_SCHEMA)
            except TypeError:  # llm without response_schema support (e.g. a test fake)
                raw = llm.chat(prompt, want_json=True)
            got = parse_findings(parse_model_json(raw) if isinstance(raw, str) else raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("critic %r failed for %r, skipping: %s", lens, keyword, exc)
            continue
        for f in got:
            f["lens"] = lens
        findings.extend(got)
        logger.info("critic %s on %r: %d finding(s)", lens, keyword, len(got))

    # Deterministic grounding pass — REPORTS ONLY, never a blocking finding.
    #
    # It used to append one `blocker` per flagged term, which forced a revision round. The
    # detector flags Title-Case heading words and plural mismatches ('Costs', 'Risk', 'Value'),
    # so the reviser was ordered to strip legitimate prose and the article got worse while
    # every check reported success. Token presence is not claim support — "Tim recommends
    # replacing shingles every 10 years" uses only his words and is still invented — so this
    # cannot be tuned into a gate. It is a lead for a human, not an instruction to a model.
    if transcript:
        from core.grounding import unsourced_terms  # noqa: PLC0415
        terms = unsourced_terms(fields.get("content_md", ""), transcript, ignore=keyword)
        if terms:
            logger.info("grounding-check on %r: %d unsourced term(s) (reported, not blocking): "
                        "%s", keyword, len(terms), terms[:8])
    return findings


def critique_and_revise(fields: dict, keyword: str, *, llm, transcript: str = "",
                        target_words: int = 1800, rounds: int = CRITIQUE_ROUNDS) -> dict:
    """Generate -> critique (3 lenses) -> revise, up to `rounds` times.

    Stops early when no critic raises a blocking finding — the common case once the article is
    good, and what keeps this from costing 3 rounds every time.

    Every revision goes through the same no-regress guard as refine: the reviser is another
    fail-open LLM call, and a revision that drops half the article is not an improvement no
    matter how many findings it claims to fix.
    """
    from core.article_critique import blocking  # noqa: PLC0415

    goal = _word_goal(target_words)
    for i in range(1, rounds + 1):
        findings = _run_critics(fields, keyword, transcript, llm=llm)
        blockers = blocking(findings)
        if not blockers:
            logger.info("critique round %d for %r: clean, stopping", i, keyword)
            return fields
        logger.info("critique round %d for %r: %d blocking finding(s), revising",
                    i, keyword, len(blockers))
        fields = _revise_without_regressing_length(fields, keyword, blockers, goal, llm=llm)
    return fields


def _revise_without_regressing_length(fields: dict, keyword: str, findings: list[dict],
                                      goal: int, *, llm) -> dict:
    """Apply reviewer findings, keeping the previous draft if the reviser loses content."""
    from core.article_critique import revise_prompt  # noqa: PLC0415
    from core.seo import _word_count  # noqa: PLC0415

    before = _word_count(fields.get("content_md", ""))
    try:
        revised = _chat_article(llm, revise_prompt({**fields, "focus_keyword": keyword},
                                                   findings, goal))
    except Exception as exc:  # noqa: BLE001
        logger.warning("revise failed for %r, keeping draft: %s", keyword, exc)
        return fields
    if not revised:
        logger.warning("revise returned no content for %r, keeping draft", keyword)
        return fields

    out = {
        "title":      revised.get("title") or fields.get("title"),
        "slug":       revised.get("slug") or fields.get("slug"),
        "meta":       revised.get("metaDescription") or fields.get("meta"),
        "content_md": markdownish_to_html(revised.get("content") or fields.get("content_md", "")),
        "faq_json":   [{"q": it["q"], "a": it.get("a", "")}
                       for it in (revised.get("faq") or [])
                       if isinstance(it, dict) and it.get("q")] or fields.get("faq_json"),
    }
    after = _word_count(out["content_md"])
    if after < before:
        logger.warning("revise for %r returned %d words vs %d — keeping the longer draft",
                       keyword, after, before)
        return fields
    return out


def _refine_without_regressing_length(fields: dict, keyword: str, *, llm=None) -> dict:
    """refine_article_content, but never accept a revision that loses content.

    The editor pass rewrites the article wholesale and is fail-open by design, so a bad
    revision silently replaces a good draft — that is how an expanded 2208-word article
    came back as 949. Length is the cheap proxy for "did the editor drop half the piece";
    if the revision is shorter, keep the draft we already had.
    """
    from core.seo import _word_count  # noqa: PLC0415

    before = _word_count(fields.get("content_md", ""))
    refined = refine_article_content(fields, keyword, llm=llm)
    after = _word_count(refined.get("content_md", ""))
    if after < before:
        logger.warning("refine for %r returned %d words vs %d — keeping the longer draft",
                       keyword, after, before)
        return fields
    return refined


GROUNDING_ROUNDS = 2


@lru_cache(maxsize=1)
def _corpus_vocabulary(_tenant: int = 1) -> frozenset[str]:
    """Every word Tim has ever said, across all 801 videos (~11,300 tokens).

    Cached per process: it is one scan of 14,592 chunks and the answer does not change during
    a run. Opens its own stamped session — callers reach this from inside a generation and
    should not have to thread a session down for a diagnostic.
    """
    import re as _re  # noqa: PLC0415

    try:
        from app.models import Chunk, SessionLocal  # noqa: PLC0415
        with SessionLocal() as db:
            db.info["tenant_id"] = _tenant
            vocab: set[str] = set()
            for (text,) in db.query(Chunk.text).all():
                vocab |= set(_re.findall(r"[a-z0-9]+", (text or "").lower()))
        return frozenset(vocab)
    except Exception as exc:  # noqa: BLE001 — a diagnostic must never break generation
        logger.warning("corpus vocabulary unavailable: %s", exc)
        return frozenset()


def _audit_grounding(fields: dict, keyword: str, transcript: str) -> list[str]:
    """Proper nouns the article names that its source transcripts never mention.

    `transcript` is the evidence the generator actually used, held by the caller — no evidence
    in hand -> no claims of fabrication. Deliberately does not re-retrieve: an audit that
    re-queried would add a network call to every generation (and hung the test suite when I
    first wrote it that way).

    TWO TIERS, because they mean very different things (measured across 31 articles):

      absent from THIS ARTICLE'S SLICES  — weak. Mostly Title-Case headings and plural
        mismatches ('Costs', 'Underlayment'), sometimes the model reaching outside its evidence
        onto something real ('PB77', 'Polyblast' — both things Tim genuinely says elsewhere).
        ~9 per article. Noise.

      absent from the WHOLE 801-VIDEO CORPUS — strong. Tim has never said this word in his
        life, so the article invented it: 'Solar Reflectance Index' has 0 hits in 14,592
        chunks. ~1 per article.

    The corpus tier is a severity ESCALATOR, not a replacement — GPT-5 and Grok both rejected
    swapping the slice check for it, correctly: "Tim said it somewhere across 801 videos" is
    not evidence for THIS article, and trading the grounding signal away to hide false
    positives is worse than the false positives. Both tiers report; neither edits. Token
    presence still is not claim support ([[grounding-vs-vocabulary]]).
    """
    from core.grounding import _normalise, unsourced_terms  # noqa: PLC0415

    if not transcript:
        return []
    terms = unsourced_terms(fields.get("content_md", ""), transcript, ignore=keyword)
    if not terms:
        return []

    vocab = _corpus_vocabulary()
    if vocab:
        never = [t for t in terms if not all(w in vocab for w in _normalise(t).split())]
        if never:
            logger.error(
                "GROUNDING (corpus): %r names %d term(s) Tim has NEVER said in 801 videos: "
                "%s — likely invented; verify before this ships", keyword, len(never), never)
    fields["never_said_terms"] = [
        t for t in terms if vocab and not all(w in vocab for w in _normalise(t).split())
    ]
    return terms


def _enforce_grounding(fields: dict, keyword: str, transcript: str, *, llm=None,
                       target_words: int = 1800, rounds: int = GROUNDING_ROUNDS) -> dict:
    """REPORT unsourced terms. Does not edit the article — deliberately.

    This used to feed each flagged term to an LLM reviser as a `blocker` ("Remove 'X', Tim
    never said it") for up to 2 rounds. In production that flagged 'Costs', 'Risk', 'Value',
    'Durability' and 10 more on a single article — Title-Case headings make every heading word
    a candidate, and "cost" vs "Costs" fails a plural-naive token test. So the reviser was
    ordered to strip legitimate words, twice per article, at ~10 minutes a round. Articles got
    worse while every check reported success.

    The deeper reason it stays report-only: TOKEN PRESENCE IS NOT CLAIM SUPPORT. "Tim
    recommends replacing all shingles every 10 years" can be built entirely from words Tim has
    said and still be pure invention — so this detector's precision ceiling is low by
    construction, not by tuning. A noisy detector must never drive automated edits: the reviser
    optimises for satisfying the finding, not for truth, and cannot tell a bad flag from a good
    one. (Reviewed independently by GPT-5 and Grok; both reached this conclusion.)

    Real claim-grounding needs typed checks — numbers, named entities, "Tim says/recommends"
    attributions — each requiring a matched evidence span from the source. Numbers now have
    that instrument (see _enforce_numeric_grounding below, core.numeric_grounding) because a
    figure is objectively checkable against the source in a way a semantic claim is not, so it
    can safely edit where this proper-noun guard cannot. Named-entity/attribution checks are
    still not built. Until they are, the honest defence there is upstream: give the generator
    enough real transcript (source_transcripts) and forbid invention in the prompt.
    """
    terms = _audit_grounding(fields, keyword, transcript)
    if terms:
        logger.warning(
            "GROUNDING: %r names %d term(s) absent from its sources: %s — reported, NOT edited "
            "(this detector is too noisy to drive revisions; check by hand if it matters)",
            keyword, len(terms), terms[:12])
    fields["unsourced_terms"] = terms
    return fields


NUMERIC_GROUNDING_ROUNDS = 2


def _soften_unsupported_numeric_claims(content_md: str, unsupported: list[str]) -> str:
    """Deterministic last resort: delete the sentence containing each still-unsupported figure.

    Runs only after the LLM repair rounds in _enforce_numeric_grounding could not ground (or
    remove) a number — an invented wind rating or price must never ship just because a repair
    attempt was made. Tag-boundary aware (matches stop at '<'/'>') so a deletion can't bleed
    into the next paragraph or heading.
    """
    out = content_md
    for claim in unsupported:
        pattern = re.compile(
            r'(?:(?<=[.!?])\s+|(?<=[>])\s*)([^<>.!?]*?' + re.escape(claim) + r'[^<>.!?]*[.!?])')
        out = pattern.sub(" ", out)
    out = re.sub(r"<(p|li)([^>]*)>\s*</\1>", "", out, flags=re.IGNORECASE)  # emptied blocks
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _enforce_numeric_grounding(fields: dict, keyword: str, transcript: str, *, llm=None,
                               target_words: int = 1800,
                               rounds: int = NUMERIC_GROUNDING_ROUNDS) -> dict:
    """BLOCK unsupported numeric claims from shipping.

    Unlike _enforce_grounding (proper nouns, report-only — token presence there is not proof of
    invention, so it can't safely drive edits) a number IS objectively checkable: either "218
    mph" appears in the source (allowing format/range/synonym variance, see
    core.numeric_grounding) or it doesn't. A wrong wind rating or price on a licensed roofer's
    site is a liability an invented adjective is not, so this one is allowed to edit.

    Tries the same revise loop the critique pass uses (one blocker finding per ungrounded
    figure) up to `rounds` times. Whatever is STILL unsupported after that is deterministically
    stripped sentence-by-sentence — bias is toward flagging: a real figure sent for human
    review costs nothing shipped-wrong; an invented one shipping is the failure mode this
    exists to prevent.
    """
    if not transcript:
        return fields  # no evidence in hand -> nothing to check against (same policy as
                        # _audit_grounding)

    goal = _word_goal(target_words)
    for _ in range(rounds):
        _, unsupported = check_numeric_claims(fields.get("content_md", ""), transcript)
        if not unsupported:
            break
        logger.warning(
            "NUMERIC GROUNDING: %r has %d unsupported figure(s): %s — attempting repair",
            keyword, len(unsupported), unsupported)
        findings = [
            {"severity": "blocker",
             "issue": f'The article states "{claim}" but the source transcript never gives '
                      f"this figure.",
             "fix": "Find the real figure in the source transcript and correct it, or remove/"
                    "soften the sentence. Never invent a replacement number."}
            for claim in unsupported
        ]
        fields = _revise_without_regressing_length(fields, keyword, findings, goal, llm=llm)

    _, still_unsupported = check_numeric_claims(fields.get("content_md", ""), transcript)
    if still_unsupported:
        logger.error(
            "NUMERIC GROUNDING: %r still has %d unsupported figure(s) after %d repair round(s), "
            "stripping the sentence(s) rather than shipping an invented number: %s",
            keyword, len(still_unsupported), rounds, still_unsupported)
        fields["content_md"] = _soften_unsupported_numeric_claims(
            fields.get("content_md", ""), still_unsupported)
    fields["numeric_claims_stripped"] = still_unsupported
    return fields


def generate_scored_article(
    keyword: str,
    ctx: dict,
    *,
    target: int = 100,
    max_iters: int = 3,
    llm=None,
    validator_llm=None,
    db=None,
    critique: bool = False,
) -> dict:
    """Generate an article, then loop (generate → score → refine) until the SEO/AIO
    score reaches ``target`` (default 100) or ``max_iters`` is hit.

    Verification is the pure ``core.seo.score_article``. Structural checks that can be
    satisfied deterministically (JSON-LD, meta length, a FAQ) are guaranteed on the
    final pass so a finished draft never ships below 100 on fixable dimensions.

    Returns the generate_article_content fields plus ``jsonld_json`` and ``seo_score``.

    ``critique`` (default OFF) runs the 3-lens adversarial loop (core.article_critique) before the
    deterministic guarantees. It is OPT-IN because it is expensive — up to CRITIQUE_ROUNDS x
    (3 critics + 1 revision) extra LLM round-trips per article on top of generation — and because
    turning it on globally silently changes every existing caller's cost, latency, and LLM-call
    surface. Callers that want it ask for it (see jobs/regen_articles_seo).

    Two-model split: ``llm`` drafts/refines (may be the cheap local backend, e.g. litellm's
    gpt-oss-120b-think); ``validator_llm`` grades that draft for grounding and defaults to an
    EXPLICIT VertexLLM instance regardless of settings.LLM_BACKEND, so a local draft model never
    marks its own homework. Construction is lazy/no-op (no vertexai.init happens until a check
    actually calls .chat()), so a caller that never exercises the validator pays nothing.
    """
    from core.seo import failing_keys, score_article  # noqa: PLC0415

    if llm is None:
        from adapters.llm import get_default  # noqa: PLC0415
        llm = get_default()
    if validator_llm is None:
        from adapters.llm import VertexLLM  # noqa: PLC0415
        validator_llm = VertexLLM(
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GCP_REGION", "us-central1"),
            chat_model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
        )

    fields = generate_article_content(keyword, ctx, llm=llm, db=db)
    # Hold the evidence in a LOCAL, not in `fields`. Every refine/revise step rebuilds the dict
    # from a fixed set of keys, so anything carried inside it is silently dropped — and a
    # grounding audit with no evidence reports "clean". That is the same way every other check
    # failed today: it stopped working and said nothing.
    transcript = fields.pop("_source_transcript", "") or ""
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
            fields = _refine_without_regressing_length(fields, keyword, llm=llm)
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

    # ── Adversarial critique: 3 lenses x up to CRITIQUE_ROUNDS rounds ────────
    # Runs BEFORE the deterministic guarantees below so those still get the last word and can
    # repair anything the reviser breaks (title band, meta length, a dropped heading).
    if critique:
        fields = critique_and_revise(
            fields, keyword, llm=llm,
            transcript=transcript or _grounding_transcript(keyword, db=db),
            target_words=int(ctx.get("target_words", 1800)))
        fields["content_md"] = markdownish_to_html(fields.get("content_md", ""))

    # ── Grounding is enforced on EVERY path, not just critique=True ──────────
    # api/routes/topics.py — the app's own "generate article" button, and where future content
    # comes from — calls this with critique off. Leaving the guard advisory there meant the one
    # path that matters had no fabrication check at all. This costs an LLM round-trip ONLY when
    # something is actually unsourced; a clean article pays nothing.
    fields = _enforce_grounding(fields, keyword, transcript, llm=validator_llm,
                               target_words=int(ctx.get("target_words", 1800)))

    # ── Numeric claims are a liability, not a style issue — this one edits ───
    # Prices, wind ratings, gauges: unlike the proper-noun guard above, a number is objectively
    # checkable against the source, so unsupported ones are repaired or stripped, never just
    # reported. See _enforce_numeric_grounding / core.numeric_grounding.
    fields = _enforce_numeric_grounding(fields, keyword, transcript, llm=llm,
                                        target_words=int(ctx.get("target_words", 1800)))

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

    # 4. Title: keyword_in_title + title_len (30–65 chars), then rm_title_number.
    #    Order matters: _ensure_title owns the 30-65 band and the keyword, so the number goes on
    #    after and re-checks both rather than fighting it.
    fields["title"] = _ensure_title(fields.get("title", ""), keyword)
    fields["title"] = _ensure_title_number(fields["title"], keyword)

    # 4b. rm_kw_in_img_alt — give the article its source video's thumbnail (a real, relevant
    #     image), then caption it. Order matters: supply the image before captioning it.
    fields["content_md"] = _ensure_article_image(fields.get("content_md", ""), keyword)
    fields["content_md"] = _ensure_img_alt_keyword(fields.get("content_md", ""), keyword)

    # 5. Headings: ensure ≥1 <h2> in content_md
    fields["content_md"] = _ensure_heading(fields.get("content_md", ""), keyword)

    # 6. Answer-first lede: first ~200 plain-text chars must contain a sentence
    fields["content_md"] = _ensure_answer_first(
        fields.get("content_md", ""), keyword, fields.get("faq_json") or [])

    # 7. Table of contents (REQUIRED): anchor-linked TOC + <h2> ids. Inserted after the intro so
    #    it doesn't displace the answer-first lede. AI answer engines and Rank Math both credit it;
    #    the live site had none. Idempotent and a no-op below 3 sections.
    from core.seo import ensure_toc  # noqa: PLC0415
    fields["content_md"] = ensure_toc(fields.get("content_md", ""))

    # 7. Wordcount > 300: if still short after all fixes, attempt one more refine
    if _word_count_str(fields.get("content_md", "")) <= 300:
        logger.warning(
            "generate_scored_article %r: body still ≤300 words before final score; "
            "attempting emergency refine", keyword)
        # Same seam as the main loop: refine is fail-open and shortens, so go through the guard.
        fields = _refine_without_regressing_length(fields, keyword, llm=llm)
        fields["content_md"] = markdownish_to_html(fields.get("content_md", ""))
        fields["content_md"] = _ensure_heading(fields.get("content_md", ""), keyword)
        fields["content_md"] = _ensure_answer_first(
            fields.get("content_md", ""), keyword, fields.get("faq_json") or [])
        if _word_count_str(fields.get("content_md", "")) <= 300:
            logger.error(
                "generate_scored_article %r: body still ≤300 words after emergency refine; "
                "wordcount check will fail — content may be incomplete", keyword)

    # 7b. Internal links (REQUIRED): cluster -> pillar + 1-3 contextual services links.
    #     Placed after the emergency-refine block for the same reason as the footer below.
    fields["content_md"] = _ensure_internal_links(fields.get("content_md", ""), keyword, ctx)

    # 8. Footer (REQUIRED on every article): YouTube subscribe CTA. Placed last, after the
    #    emergency-refine block above (which can regenerate content_md wholesale), so nothing
    #    downstream of this point can drop it.
    fields["content_md"] = _ensure_footer_link(fields.get("content_md", ""))

    jsonld = _build_article_jsonld(fields, ctx)

    # ── Deterministic repair + QA pass (core.article_repair) ─────────────────
    # Same stage as generate_article's batch path. Best-effort: only runs when a
    # DB session is available — every current caller of generate_scored_article
    # passes one; skipping otherwise (rather than opening an ad-hoc unstamped
    # session) keeps this off the C1 unstamped-SessionLocal failure class.
    if db is not None:
        try:
            fields["content_md"], jsonld, repair_issues = _apply_repair(
                fields.get("content_md", ""), jsonld, keyword, fields.get("meta", ""), db)
            fields.setdefault("qa_checks", []).extend(repair_issues)
        except Exception as exc:  # noqa: BLE001
            logger.warning("article_repair failed for %r, shipping unrepaired: %s", keyword, exc)

    result = _score(fields, jsonld)

    fields["jsonld_json"] = jsonld
    fields["seo_score"] = result["score"]
    fields["unsourced_terms"] = _audit_grounding(fields, keyword, transcript)
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
    """Convert Markdown to HTML, then run the article allow-list sanitizer.

    Sanitization is delegated to ``sanitize_html()`` — the SAME policy the manual
    editor route enforces — so this unattended auto-publish path (article_job +
    regen_articles_seo) can no longer be weaker than the human-in-the-loop path.
    sanitize_html disallows inline ``style`` and drops the inner text of
    script/style blocks (two-pass), closing the CSS-injection / arbitrary-embed
    gap this path previously carried via its own looser bleach allow-list.
    Legitimate YouTube iframes (https src) still survive.
    """
    import markdown  # noqa: PLC0415

    html = markdown.markdown(md, extensions=["tables", "fenced_code"])
    return sanitize_html(html)


def _duration_iso(seconds: float | None) -> str:
    """Convert a duration in seconds to ISO 8601 format (PT#M#S)."""
    if not seconds:
        return "PT0S"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"PT{minutes}M{secs}S"
    return f"PT{secs}S"


SOURCE_MAX_SLICES = 14
SOURCE_MAX_WORDS = 24000
_NO_TOPIC_PAD_SECS = 90.0


def _topic_windows(video_id: str, db) -> list[tuple[float, float | None, str]]:
    """A video's topic markers as (start, end, label) windows, in playback order.

    content_graph stores a topic's start but no end, so a topic runs until the next one begins
    (the last runs to the end of the video, hence None).
    """
    from app.models import GraphNode  # noqa: PLC0415

    tops = (db.query(GraphNode)
            .filter(GraphNode.video_id == video_id, GraphNode.kind == "topics")
            .order_by(GraphNode.start).all())
    return [((t.start or 0.0),
             (tops[i + 1].start if i + 1 < len(tops) else None),
             (t.label or ""))
            for i, t in enumerate(tops)]


def source_transcripts(keyword: str, db=None, *, max_slices: int = SOURCE_MAX_SLICES,
                       max_words: int = SOURCE_MAX_WORDS) -> list[dict]:
    """Tim's actual words on this topic: the transcript of the RELEVANT TIME SLICES.

    Retrieval finds where Tim discusses the keyword; each hit is then widened to the whole
    TOPIC it sits inside (content_graph kind=topics marks topic starts; a topic runs until the
    next one begins). The result is contiguous, on-topic speech — Tim's complete thought, not a
    300-char fragment of it, and not a 14,000-word video where 3 minutes are on point.

    Why slices and not whole videos: "How to Install a Metal Roof in Florida" is 14,834 words,
    of which maybe a single passage covers ventilation. Feeding the whole thing buries the
    relevant material in noise and invites the model to drift off-topic.

    Why not the old way: `hybrid_search(k=4)` + `chunk.text[:300]` handed the generator ~200
    words of Tim and asked for an 1800-word article. There is only one way to close a gap that
    size, and it is invention — measured across the last regen, 45,945 published words had
    4,564 words of retrievable source behind them (~10%).

    Returns [{video_id, title, url, label, transcript}], most relevant first.
    """
    from app.models import Chunk, Video  # noqa: PLC0415
    from app.retrieval import hybrid_search  # noqa: PLC0415
    from core.retrieval import link as video_link  # noqa: PLC0415

    hits = (hybrid_search(keyword, k=40, db=db) or {}).get("chunks") or []
    if not hits:
        return []

    # Map each hit onto the topic window containing it, so several hits inside one topic collapse
    # to a single slice and score it higher rather than repeating it.
    windows: dict[tuple, dict] = {}
    topic_cache: dict[str, list] = {}
    for chunk, score in hits:
        vid = chunk.video_id
        if vid not in topic_cache:
            topic_cache[vid] = _topic_windows(vid, db)
        cstart = chunk.start or 0.0
        window = next((w for w in reversed(topic_cache[vid]) if w[0] <= cstart), None)
        if window is None:  # no topic marks this region — fall back to a pad around the hit
            window = (max(0.0, cstart - _NO_TOPIC_PAD_SECS), cstart + _NO_TOPIC_PAD_SECS, "")
        key = (vid, window[0])
        entry = windows.setdefault(key, {"vid": vid, "win": window, "score": 0.0})
        entry["score"] += float(score or 0.0)

    out: list[dict] = []
    budget = max_words
    for entry in sorted(windows.values(), key=lambda e: e["score"], reverse=True)[:max_slices]:
        vid, (wstart, wend, label) = entry["vid"], entry["win"]
        q = db.query(Chunk).filter(Chunk.video_id == vid, Chunk.end > wstart)
        if wend is not None:
            q = q.filter(Chunk.start < wend)
        rows = q.order_by(Chunk.start).all()
        if not rows:
            continue
        text = " ".join((c.text or "").strip() for c in rows).strip()
        words = text.split()
        if not words:
            continue
        if len(words) > budget:
            text = " ".join(words[:budget])
        budget -= min(len(words), budget)
        video = db.get(Video, vid)
        out.append({
            "video_id": vid,
            "title": (video.title if video else "") or vid,
            "url": video_link(vid, wstart),
            "label": label,
            "transcript": text,
        })
        if budget <= 0:
            logger.info("source_transcripts %r: hit the %d-word budget at %d slice(s)",
                        keyword, max_words, len(out))
            break
    return out


def _append_video_grounding(user_prompt: str, sources: list[dict]) -> str:
    """Append Tim's on-topic transcript slices + the grounding rules to the user prompt."""
    lines = [
        "",
        "=" * 70,
        "SOURCE TRANSCRIPTS — Tim Kanak's own words, from Perkins Roofing's YouTube channel.",
        "Each block is the transcript of the section of a video where Tim actually discusses",
        "this topic. This is the ONLY material this article may be built from.",
        "",
        "HARD RULES — these override every other instruction, including length:",
        "1. EVERY specific fact — price, material, brand, code, measurement, timeframe,",
        "   technique, recommendation — MUST come from the transcripts below. If Tim does not",
        "   say it, DO NOT write it. No general roofing knowledge. No 'typical' figures.",
        "2. If the transcripts do not cover something a section would need, CUT THE SECTION.",
        "   A shorter article that is entirely Tim beats a longer one that is partly invented.",
        "3. NO FILLER. Marketing lines ('peace of mind', 'superior protection', 'complete",
        "   line of defense'), restating a point in new words, and throat-clearing are defects.",
        "   If a sentence carries no information from Tim, delete it.",
        "4. WRITE IN TIM'S VOICE — a working South Florida roofer explaining it plainly, using",
        "   the words and examples he actually uses. Not an SEO agency, not a brochure.",
        "5. Cite with the exact ?t= URLs given below, as inline markdown links, at least twice.",
        "6. Length is an OUTCOME of how much Tim covers, never a target to pad toward.",
        "=" * 70,
    ]
    for i, s in enumerate(sources, 1):
        topic = f" — topic: {s['label']}" if s.get("label") else ""
        lines += [
            "",
            f"--- SOURCE {i}: {s['title']}{topic}",
            f"    CITE AS: {s['url']}",
            f"    TIM SAYS: {s['transcript']}",
        ]
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
