"""Pure transform helpers for jobs.restandardize_articles (existing-article dry-run
re-standardization pass). No I/O — DB reads/writes and the actual jsonld rebuild call
(jobs.article_job._build_article_jsonld) live in the job.
"""
from __future__ import annotations

_BLOG_PREFIX = "/blog/"


def strip_blog_links(text: str) -> tuple[str, int]:
    """Rewrite '/blog/<slug>' links to the top-level '/<slug>' path.

    Matches the canonical_url convention in jobs.article_job (WordPress permalinks are
    "Post name", so every post lives at <base>/<slug>, never <base>/blog/<slug>). A literal
    substring replace is safe here: '/blog/' carries no other meaning in article content.
    """
    if not text:
        return text, 0
    count = text.count(_BLOG_PREFIX)
    return text.replace(_BLOG_PREFIX, "/"), count


def strip_blog_links_deep(obj):
    """Recursively apply strip_blog_links to every string in a JSON-LD-shaped
    structure (nested dicts/lists), returning (rewritten_obj, total_count)."""
    if isinstance(obj, str):
        return strip_blog_links(obj)
    if isinstance(obj, dict):
        total = 0
        out = {}
        for k, v in obj.items():
            new_v, n = strip_blog_links_deep(v)
            out[k] = new_v
            total += n
        return out, total
    if isinstance(obj, list):
        total = 0
        out = []
        for v in obj:
            new_v, n = strip_blog_links_deep(v)
            out.append(new_v)
            total += n
        return out, total
    return obj, 0


def video_nodes(jsonld: list[dict] | None) -> list[dict]:
    """Existing VideoObject nodes from a jsonld_json list — carried through unchanged
    into the FAQ+Video-only rebuild (already correct, nothing to regenerate)."""
    return [n for n in (jsonld or []) if isinstance(n, dict) and n.get("@type") == "VideoObject"]


def jsonld_types(jsonld: list[dict] | None) -> list[str]:
    """@type of every node in a jsonld_json list, for dry-run before/after reporting."""
    return [n.get("@type") for n in (jsonld or []) if isinstance(n, dict)]
