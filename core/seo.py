"""Pure SEO/AIO article scorer — no I/O, deterministic.

Single source of truth for the article quality score shown in the console and
targeted by the generation loop. The SPA mirrors these exact checks so the number
the editor sees matches what generation optimises for. Total = 100 points.

Checks (11 total, 100 pts):
  meta_present    10  Meta description present
  meta_len        10  Meta description 120–160 chars
  title_len        5  Title length 30–65 chars
  keyword_in_title 5  Keyword appears in title (AEO signal)
  headings        10  Has H2/H3 headings in content
  answer_first     5  Answer-first lede: direct sentence in first 200 chars
  faq              5  Has ≥1 FAQ pair
  faq_count       10  Has ≥4 FAQ pairs (FAQPage needs ≥4 to display in SGE)
  jsonld          15  Has JSON-LD structured data
  video           10  Has embedded video link
  wordcount       15  Word count > 300

Rank Math checks (16 total) — see rank_math_checks():
  rm_kw_in_title        focus keyword in SEO title
  rm_kw_in_meta         focus keyword in meta description
  rm_kw_in_slug         focus keyword in URL slug
  rm_kw_in_intro        focus keyword in first ~10% of content
  rm_kw_in_body         focus keyword in body content
  rm_kw_in_heading      focus keyword in at least one H2/H3/H4
  rm_kw_in_img_alt      focus keyword in at least one img alt attribute
  rm_kw_density         keyword density 1.0%–1.5%
  rm_content_length     content ≥ 600 words (Rank Math's floor)
  rm_slug_length        URL slug < 75 chars
  rm_internal_link      at least one internal (relative) link
  rm_external_link      at least one external DoFollow link
  rm_title_kw_position  focus keyword near beginning of title (first half)
  rm_title_sentiment    title contains positive or negative sentiment word
  rm_title_power_word   title contains a power word
  rm_title_number       title contains a number
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"(<h[23][\s/>])|(^#{2,3}\s)", re.IGNORECASE | re.MULTILINE)
_VIDEO_RE = re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE)
# A real embedded video is an <iframe> pointing at YouTube, OR a bare YouTube URL
# on its own line (WordPress oEmbed renders that as a player). A plain <a> citation
# link is NOT an embed — it renders as text, so it must not satisfy this check.
_VIDEO_IFRAME_RE = re.compile(
    r"<iframe\b[^>]*\bsrc=[\"'][^\"']*(?:youtube\.com|youtu\.be)[^\"']*[\"']",
    re.IGNORECASE,
)
_VIDEO_BARE_URL_RE = re.compile(
    r"(?:^|\n)\s*https?://(?:www\.)?(?:youtube\.com/(?:watch|embed)|youtu\.be/)\S*\s*(?:\n|$)",
    re.IGNORECASE,
)


def _has_video_embed(content: str) -> bool:
    """True when content contains a real video embed (iframe or bare oEmbed URL)."""
    text = content or ""
    return bool(_VIDEO_IFRAME_RE.search(text) or _VIDEO_BARE_URL_RE.search(text))


# Answer-first: first 200 chars of body text contain a sentence-ending period or
# a direct declarative phrase (not just a heading or blank space).
_ANSWER_FIRST_RE = re.compile(r"\w{4,}.*?\.", re.DOTALL)

# Rank Math helpers
_H_ANY_RE = re.compile(r"<h[234][^>]*>(.*?)</h[234]>", re.IGNORECASE | re.DOTALL)
_IMG_ALT_RE = re.compile(r"<img[^>]+alt=[\"']([^\"']*)[\"'][^>]*>", re.IGNORECASE)
# Internal link: href starts with / or is relative (no scheme)
_INTERNAL_LINK_RE = re.compile(r'<a\s[^>]*href=["\'](?!//)(/[^"\']*)["\']', re.IGNORECASE)
# External DoFollow link: href=http/https AND no rel containing nofollow
_EXTERNAL_LINK_RE = re.compile(r'<a\s[^>]*href=["\']https?://[^"\']+["\'][^>]*>', re.IGNORECASE)
_REL_NOFOLLOW_RE = re.compile(r'rel=["\'][^"\']*nofollow[^"\']*["\']', re.IGNORECASE)

_POSITIVE_WORDS = {
    "best", "top", "amazing", "proven", "powerful", "ultimate", "perfect",
    "easy", "fast", "free", "guaranteed", "safe", "trusted", "expert",
    "effective", "essential", "complete", "comprehensive", "smart", "simple",
}
_NEGATIVE_WORDS = {
    "worst", "avoid", "danger", "mistake", "warning", "wrong", "bad",
    "never", "stop", "fail", "risk", "problem", "costly", "harmful",
    "shocking", "beware", "critical", "urgent", "hidden", "scam",
}
# Rank Math's content-length threshold — under this it reports "Content is X words long.
# Consider using at least 600 words." Generation targets far more (see core/article_plan
# target_words), but this is the floor an article must clear to score green. Public because
# jobs/article_job expands drafts up to it.
RM_MIN_WORDS = 600

_POWER_WORDS = {
    "secret", "proven", "guaranteed", "instantly", "exclusive", "ultimate",
    "powerful", "shocking", "remarkable", "incredible", "essential", "definitive",
    "complete", "effortless", "revolutionary", "unbeatable", "critical",
    "breakthrough", "surprising", "unexpected", "forbidden", "urgent", "now",
    "free", "bonus", "limited", "new", "discover", "revealed",
}


def _word_count(content: str) -> int:
    """Word count with HTML tags and markdown punctuation stripped."""
    text = _TAG_RE.sub(" ", content or "")
    text = re.sub(r"[#*>`_~\[\]]", " ", text)
    return len([w for w in text.split() if w])


def _plain_text(content: str) -> str:
    """Strip all HTML tags and markdown punctuation from content."""
    text = _TAG_RE.sub(" ", content or "")
    text = re.sub(r"[#*>`_~\[\]]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_text_head(content: str, chars: int = 200) -> str:
    """Strip tags/markdown from the first ``chars`` characters of content."""
    return _plain_text(content)[:chars]


# _plain_text strips markdown/HTML but leaves sentence punctuation attached, so "roof leaks."
# tokenised to ["roof", "leaks."] and never matched ["roof", "leaks"] — every occurrence ending
# a sentence or clause was invisible to density alone. Every sibling check here (kw_in_title /
# _meta / _intro / _body / _heading / _img_alt) uses substring matching and never had that blind
# spot, so the same phrase could pass kw_in_body and be uncountable for density.
#
# Hyphens are deliberately KEPT: "L-flashing" and "L flashing" are not interchangeable, and
# collapsing them has previously produced false calls against real terms Tim uses.
_DENSITY_PUNCT_RE = re.compile(r"[^a-z0-9'\- ]+")


def _kw_density(content: str, keyword: str) -> float:
    """Return keyword density as a fraction (0.0–1.0)."""
    if not keyword:
        return 0.0
    text = _DENSITY_PUNCT_RE.sub(" ", _plain_text(content).lower())
    words = [w for w in text.split() if w]
    total = len(words)
    if total == 0:
        return 0.0
    kw_words = _DENSITY_PUNCT_RE.sub(" ", keyword.lower()).split()
    kw_len = len(kw_words)
    count = 0
    for i in range(len(words) - kw_len + 1):
        if words[i:i + kw_len] == kw_words:
            count += 1
    return count / total


def score_article(
    title: str,
    meta: str,
    content_md: str,
    faq_json: list | None,
    has_jsonld: bool,
    keyword: str = "",
) -> dict:
    """Score an article 0-100 across 11 weighted checks.

    HTML-aware: headings match ``<h2>/<h3>`` (or markdown ``##``); word count
    ignores tags. Returns {score, max, checks:[{key,label,points,pass,detail}]}.

    Args:
        title:      Article title.
        meta:       Meta description string.
        content_md: Article body (may contain HTML or markdown).
        faq_json:   List of {q, a} dicts (or None).
        has_jsonld: True when at least one JSON-LD block was built.
        keyword:    Primary target keyword (used for keyword_in_title check).
                    Pass empty string to skip that check (it will auto-pass).
    """
    meta = meta or ""
    title = title or ""
    faq = [f for f in (faq_json or []) if isinstance(f, dict) and f.get("q")]
    words = _word_count(content_md)
    head200 = _plain_text_head(content_md, 200)

    # keyword_in_title: pass when keyword is absent/empty (can't check without it)
    kw_lower = (keyword or "").strip().lower()
    kw_in_title = (not kw_lower) or (kw_lower in title.lower())

    # answer_first: first 200 plain-text chars contain a complete sentence (has a ".")
    answer_first = bool(_ANSWER_FIRST_RE.search(head200))

    checks = [
        {"key": "meta_present", "label": "Meta description present", "points": 10,
         "pass": bool(meta.strip())},
        {"key": "meta_len", "label": "Meta description 120–160 chars", "points": 10,
         "pass": 120 <= len(meta) <= 160, "detail": f"{len(meta)} chars"},
        {"key": "title_len", "label": "Title length 30–65 chars", "points": 5,
         "pass": 30 <= len(title) <= 65, "detail": f"{len(title)} chars"},
        {"key": "keyword_in_title", "label": "Keyword appears in title", "points": 5,
         "pass": kw_in_title,
         "detail": f"kw: {kw_lower[:30]}" if kw_lower else "no keyword"},
        {"key": "headings", "label": "Has H2/H3 headings in content", "points": 10,
         "pass": bool(_HEADING_RE.search(content_md or ""))},
        {"key": "answer_first", "label": "Answer-first lede (direct sentence early)", "points": 5,
         "pass": answer_first},
        {"key": "faq", "label": "Has FAQ schema (≥1 pair)", "points": 5,
         "pass": len(faq) > 0, "detail": f"{len(faq)} items" if faq else "none"},
        {"key": "faq_count", "label": "FAQ has ≥4 pairs (SGE/AEO)", "points": 10,
         "pass": len(faq) >= 4, "detail": f"{len(faq)} items" if faq else "none"},
        {"key": "jsonld", "label": "Has JSON-LD structured data", "points": 15,
         "pass": bool(has_jsonld)},
        {"key": "video", "label": "Has embedded video link", "points": 10,
         "pass": _has_video_embed(content_md or "")},
        {"key": "wordcount", "label": "Word count > 300", "points": 15,
         "pass": words > 300, "detail": f"{words} words"},
    ]
    score = sum(c["points"] for c in checks if c["pass"])
    return {"score": score, "max": sum(c["points"] for c in checks), "checks": checks}


def failing_keys(result: dict) -> list[str]:
    return [c["key"] for c in result["checks"] if not c["pass"]]


# ---------------------------------------------------------------------------
# Rank Math SEO checks (15 checks)
# ---------------------------------------------------------------------------

def rank_math_checks(
    title: str,
    meta: str,
    slug: str,
    content_md: str,
    focus_keyword: str,
) -> list[dict]:
    """Check an article against all 16 Rank Math SEO requirements.

    Pure function — no I/O. Returns a list of check dicts, each with:
        key     (str)   — machine-readable identifier
        label   (str)   — human-readable description
        pass    (bool)  — True when the check passes
        detail  (str)   — optional diagnostic detail

    Args:
        title:         SEO title of the article.
        meta:          Meta description string.
        slug:          URL slug (no leading slash, no domain).
        content_md:    Article body (HTML or markdown).
        focus_keyword: The Rank Math focus keyword to check against.
    """
    title = title or ""
    meta = meta or ""
    slug = slug or ""
    content_md = content_md or ""
    kw = (focus_keyword or "").strip().lower()

    plain = _plain_text(content_md)
    plain_lower = plain.lower()
    intro_chars = max(200, len(plain) // 10)
    intro_text = plain_lower[:intro_chars]
    content_words = _word_count(content_md)

    # ── Basic SEO ──────────────────────────────────────────────────────────────
    # 1. Keyword in SEO title
    kw_in_title = bool(kw) and (kw in title.lower())

    # 2. Keyword in meta description
    kw_in_meta = bool(kw) and (kw in meta.lower())

    # 3. Keyword in URL slug
    kw_slug = kw.replace(" ", "-")
    kw_in_slug = bool(kw) and (kw_slug in slug.lower() or kw.replace(" ", "") in slug.replace("-", ""))

    # 4. Keyword in beginning of content (first ~10%)
    kw_in_intro = bool(kw) and (kw in intro_text)

    # 5. Keyword in body content
    kw_in_body = bool(kw) and (kw in plain_lower)

    # 6. Keyword in at least one subheading (H2/H3/H4)
    heading_texts = [m.group(1).lower() for m in _H_ANY_RE.finditer(content_md)]
    # also strip tags from heading text
    heading_texts_plain = [_plain_text(h) for h in heading_texts]
    kw_in_heading = bool(kw) and any(kw in h for h in heading_texts_plain)

    # 7. At least one image with alt text containing focus keyword
    img_alts = [m.group(1).lower() for m in _IMG_ALT_RE.finditer(content_md)]
    kw_in_img_alt = bool(kw) and any(kw in alt for alt in img_alts)

    # 8. Keyword density 1.0%–1.5%. Real Rank Math awards full marks at 1.0–1.5%; our old 0.5%
    # floor was LOOSER than the plugin that scores the live site, so regen kept passing here
    # while undershooting the real check (measured 2026-07-16 against 4 published posts).
    density = _kw_density(content_md, kw)
    density_ok = bool(kw) and (0.010 <= density <= 0.015)
    density_pct = f"{density * 100:.2f}%"

    # 9. URL slug < 75 chars
    slug_len_ok = len(slug) < 75

    # 10. At least one internal (relative) link
    has_internal_link = bool(_INTERNAL_LINK_RE.search(content_md))

    # 11. At least one external DoFollow link (href=http/https, no nofollow)
    external_links = _EXTERNAL_LINK_RE.findall(content_md)
    has_external_dofollow = any(
        not _REL_NOFOLLOW_RE.search(tag) for tag in external_links
    )

    # ── Title Readability ──────────────────────────────────────────────────────
    # 12. Focus keyword near BEGINNING of title (in first half of title chars)
    title_lower = title.lower()
    kw_pos = title_lower.find(kw) if kw else -1
    kw_near_start = bool(kw) and (0 <= kw_pos <= len(title) // 2)

    # 13. Title contains a positive OR negative sentiment word
    title_words = set(re.findall(r"[a-z]+", title_lower))
    has_sentiment = bool(title_words & (_POSITIVE_WORDS | _NEGATIVE_WORDS))

    # 14. Title contains a power word
    has_power_word = bool(title_words & _POWER_WORDS)

    # 15. Title contains a number
    has_number = bool(re.search(r"\d", title))

    return [
        {"key": "rm_kw_in_title", "label": "Focus keyword in SEO title",
         "pass": kw_in_title, "detail": f"kw: {kw[:40]}"},
        {"key": "rm_kw_in_meta", "label": "Focus keyword in meta description",
         "pass": kw_in_meta, "detail": f"kw: {kw[:40]}"},
        {"key": "rm_kw_in_slug", "label": "Focus keyword in URL slug",
         "pass": kw_in_slug, "detail": f"slug: {slug[:50]}"},
        {"key": "rm_kw_in_intro", "label": "Focus keyword in first ~10% of content",
         "pass": kw_in_intro, "detail": f"intro {intro_chars} chars"},
        {"key": "rm_kw_in_body", "label": "Focus keyword in body content",
         "pass": kw_in_body},
        {"key": "rm_kw_in_heading", "label": "Focus keyword in a subheading (H2/H3/H4)",
         "pass": kw_in_heading, "detail": f"{len(heading_texts)} headings found"},
        {"key": "rm_kw_in_img_alt", "label": "Focus keyword in an image alt attribute",
         "pass": kw_in_img_alt, "detail": f"{len(img_alts)} img alt(s) found"},
        {"key": "rm_kw_density", "label": "Keyword density 1.0%–1.5%",
         "pass": density_ok, "detail": density_pct},
        {"key": "rm_content_length", "label": f"Content length ≥ {RM_MIN_WORDS} words",
         "pass": content_words >= RM_MIN_WORDS,
         "detail": f"{content_words} words"},
        {"key": "rm_slug_length", "label": "URL slug < 75 chars",
         "pass": slug_len_ok, "detail": f"{len(slug)} chars"},
        {"key": "rm_internal_link", "label": "At least one internal (relative) link",
         "pass": has_internal_link},
        {"key": "rm_external_link", "label": "At least one external DoFollow link",
         "pass": has_external_dofollow},
        {"key": "rm_title_kw_position", "label": "Focus keyword near beginning of title",
         "pass": kw_near_start, "detail": f"pos {kw_pos} of {len(title)}"},
        {"key": "rm_title_sentiment", "label": "Title contains positive or negative sentiment word",
         "pass": has_sentiment},
        {"key": "rm_title_power_word", "label": "Title contains a power word",
         "pass": has_power_word},
        {"key": "rm_title_number", "label": "Title contains a number",
         "pass": has_number},
    ]


def rank_math_failures(
    title: str,
    meta: str,
    slug: str,
    content_md: str,
    focus_keyword: str,
) -> list[str]:
    """Return list of failing Rank Math check keys."""
    checks = rank_math_checks(title, meta, slug, content_md, focus_keyword)
    return [c["key"] for c in checks if not c["pass"]]
