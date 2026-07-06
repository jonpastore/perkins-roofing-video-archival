"""Content QA gate — pure logic where possible; LLM checks live in jobs.

Ported from seo-aio functions/lib/articles/qa-gate.ts.

Pure functions (no I/O):
    verdict(checks)                  — precedence: block > warn > pass
    dedup_jaccard(text_a, text_b, n) — 5-gram shingle Jaccard similarity
    is_duplicate(new_text, existing_texts, threshold) — boolean dedup check

The fact-check and intent-classify checks (which call the LLM) belong in
jobs/article_job.py, not here, to keep this module fully unit-testable.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Verdict precedence (pure)
# ---------------------------------------------------------------------------

_PRECEDENCE = {"block": 2, "warn": 1, "pass": 0}


def verdict(checks: list[dict]) -> str:
    """Return the highest-severity verdict across a list of check results.

    Precedence: block > warn > pass.

    Args:
        checks: List of dicts, each with at least a ``"severity"`` key whose
                value is ``"pass"``, ``"warn"``, or ``"block"``.
                Unknown severity values are treated as ``"pass"``.

    Returns:
        ``"block"``, ``"warn"``, or ``"pass"``.
    """
    result = "pass"
    for check in checks:
        sev = (check.get("severity") or "pass").lower()
        if _PRECEDENCE.get(sev, 0) > _PRECEDENCE[result]:
            result = sev
            if result == "block":
                break  # can't go higher
    return result


# ---------------------------------------------------------------------------
# Jaccard shingle similarity (pure)
# ---------------------------------------------------------------------------

def _shingles(text: str, n: int = 5) -> set[str]:
    """Build a set of n-gram word shingles from *text*.

    Normalises to lowercase, strips non-alphanumeric chars, filters tokens
    shorter than 3 chars (matches seo-aio's ≥3-char filter).
    """
    words = [
        w for w in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
        if len(w) >= 3
    ]
    return {
        " ".join(words[i:i + n])
        for i in range(len(words) - n + 1)
    }


def dedup_jaccard(text_a: str, text_b: str, n: int = 5) -> float:
    """Compute Jaccard similarity between two texts using n-gram word shingles.

    Args:
        text_a: First text.
        text_b: Second text.
        n:      Shingle size in words (default 5, matching seo-aio).

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 if either text yields no shingles.
    """
    sa = _shingles(text_a, n)
    sb = _shingles(text_b, n)
    if not sa or not sb:
        return 0.0
    intersection = len(sa & sb)
    union = len(sa | sb)
    return intersection / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Rank Math SEO hard-failure check (pure)
# ---------------------------------------------------------------------------

# Checks that are HARD failures (block regeneration if ALL fail).
# Soft checks (image alt, power word, sentiment, number) are warnings only.
_RM_HARD_CHECKS = frozenset({
    "rm_kw_in_title",
    "rm_kw_in_meta",
    "rm_kw_in_slug",
    "rm_kw_in_intro",
    "rm_kw_in_body",
    "rm_kw_in_heading",
    "rm_kw_density",
    "rm_slug_length",
    "rm_internal_link",
    "rm_external_link",
    "rm_title_kw_position",
})


def seo_hard_failures(
    title: str,
    meta: str,
    slug: str,
    content_md: str,
    focus_keyword: str,
) -> list[str]:
    """Return list of HARD Rank Math check keys that are currently failing.

    Hard checks are those that Rank Math marks as required for a passing score
    (keyword placement, density, links, slug length). Soft checks (image alt,
    sentiment word, power word, number in title) are omitted — they should be
    warned about but not used to block/regenerate.

    Args:
        title:         SEO title.
        meta:          Meta description.
        slug:          URL slug.
        content_md:    Article body (HTML or markdown).
        focus_keyword: The focus keyword to validate against.

    Returns:
        List of failing check key strings (empty list = all hard checks pass).
    """
    from core.seo import rank_math_checks  # noqa: PLC0415
    checks = rank_math_checks(title, meta, slug, content_md, focus_keyword)
    return [
        c["key"] for c in checks
        if not c["pass"] and c["key"] in _RM_HARD_CHECKS
    ]


def is_duplicate(
    new_text: str,
    existing_texts: list[str],
    threshold: float = 0.85,
) -> bool:
    """Return True if *new_text* is ≥ threshold similar to any text in *existing_texts*.

    Args:
        new_text:       The candidate article text.
        existing_texts: Corpus of already-published article texts.
        threshold:      Jaccard similarity threshold (default 0.85).

    Returns:
        True if a near-duplicate is found, False otherwise.
    """
    for existing in existing_texts:
        if dedup_jaccard(new_text, existing) >= threshold:
            return True
    return False
