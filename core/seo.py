"""Pure SEO/AIO article scorer — no I/O, deterministic.

Single source of truth for the article quality score shown in the console and
targeted by the generation loop. The SPA mirrors these exact checks so the number
the editor sees matches what generation optimises for. Total = 100 points.
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"(<h[23][\s/>])|(^#{2,3}\s)", re.IGNORECASE | re.MULTILINE)
_VIDEO_RE = re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE)


def _word_count(content: str) -> int:
    """Word count with HTML tags and markdown punctuation stripped."""
    text = _TAG_RE.sub(" ", content or "")
    text = re.sub(r"[#*>`_~\[\]]", " ", text)
    return len([w for w in text.split() if w])


def score_article(
    title: str,
    meta: str,
    content_md: str,
    faq_json: list | None,
    has_jsonld: bool,
) -> dict:
    """Score an article 0-100 across 8 weighted checks.

    HTML-aware: headings match ``<h2>/<h3>`` (or markdown ``##``); word count
    ignores tags. Returns {score, max, checks:[{key,label,points,pass,detail}]}.
    """
    meta = meta or ""
    title = title or ""
    faq = [f for f in (faq_json or []) if isinstance(f, dict) and f.get("q")]
    words = _word_count(content_md)

    checks = [
        {"key": "meta_present", "label": "Meta description present", "points": 10,
         "pass": bool(meta.strip())},
        {"key": "meta_len", "label": "Meta description 120–160 chars", "points": 10,
         "pass": 120 <= len(meta) <= 160, "detail": f"{len(meta)} chars"},
        {"key": "title_len", "label": "Title length 30–65 chars", "points": 10,
         "pass": 30 <= len(title) <= 65, "detail": f"{len(title)} chars"},
        {"key": "headings", "label": "Has H2/H3 headings in content", "points": 15,
         "pass": bool(_HEADING_RE.search(content_md or ""))},
        {"key": "faq", "label": "Has FAQ schema", "points": 15,
         "pass": len(faq) > 0, "detail": f"{len(faq)} items" if faq else "none"},
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
