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
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"(<h[23][\s/>])|(^#{2,3}\s)", re.IGNORECASE | re.MULTILINE)
_VIDEO_RE = re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE)
# Answer-first: first 200 chars of body text contain a sentence-ending period or
# a direct declarative phrase (not just a heading or blank space).
_ANSWER_FIRST_RE = re.compile(r"\w{4,}.*?\.", re.DOTALL)


def _word_count(content: str) -> int:
    """Word count with HTML tags and markdown punctuation stripped."""
    text = _TAG_RE.sub(" ", content or "")
    text = re.sub(r"[#*>`_~\[\]]", " ", text)
    return len([w for w in text.split() if w])


def _plain_text_head(content: str, chars: int = 200) -> str:
    """Strip tags/markdown from the first ``chars`` characters of content."""
    text = _TAG_RE.sub(" ", content or "")
    text = re.sub(r"[#*>`_~\[\]]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:chars]


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
         "pass": bool(_VIDEO_RE.search(content_md or ""))},
        {"key": "wordcount", "label": "Word count > 300", "points": 15,
         "pass": words > 300, "detail": f"{words} words"},
    ]
    score = sum(c["points"] for c in checks if c["pass"])
    return {"score": score, "max": sum(c["points"] for c in checks), "checks": checks}


def failing_keys(result: dict) -> list[str]:
    return [c["key"] for c in result["checks"] if not c["pass"]]
