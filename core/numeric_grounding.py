"""Deterministic numeric-claim grounding check: does the article state a figure the source
material never gave?

Pure string logic, no LLM and no I/O — same philosophy as core.grounding (proper nouns), but
for numbers. A wrong wind rating, gauge, or price on a licensed roofer's site is a liability an
invented adjective is not, so this check is narrower and stricter than the prose-fabrication
guard: it only looks at numbers anchored to a unit/currency/date context that makes them an
actual factual claim (mph, $, %, gauge, years, inches, mm, ft, lb, degrees, dates, dimensions).
Structural numbers — list counts ("5 signs"), step numbers, a bare heading year ("...in 2026")
— have no such anchor and are never extracted, so they never need a special-case exclusion.

This is the "typed check... requiring a matched evidence span from the source" that the
_enforce_grounding docstring in jobs/article_job.py flags as not yet built.
"""
from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")

# Hyphen-ish characters seen in real copy (typographic minus/en-dash/non-breaking hyphen), used
# both as a range separator ("190‑220 mph") and as a compound-adjective joiner ("24-gauge").
_H = r"[-‐‑‒–—−]"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_RANGE_SEP = rf"(?:\s*{_H}\s*|\s+to\s+)"

_MONTHS = (r"January|February|March|April|May|June|July|August|September|October|November|"
           r"December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec")

# (kind, compiled pattern, group indices holding the numeric value(s)).
# Order matters only in that a number is claimed by the first pattern that matches it — real
# overlaps between these unit vocabularies are effectively impossible.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("date", re.compile(
        rf"\b(?:{_MONTHS})\.?\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?(\d{{4}})\b",
        re.IGNORECASE)),
    ("dollar", re.compile(rf"\$\s*({_NUM})(?:{_RANGE_SEP}\$?\s*({_NUM}))?")),
    ("dollar", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*dollars?\b", re.IGNORECASE)),
    ("percent", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*(?:%|percent)\b", re.IGNORECASE)),
    ("mph", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*mph\b", re.IGNORECASE)),
    ("gauge", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*{_H}?\s*(?:gauge|ga)\b",
                         re.IGNORECASE)),
    ("year", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*{_H}?\s*(?:years?|yrs?)\b",
                        re.IGNORECASE)),
    ("inch", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*(?:{_H}\s*in\b|inch(?:es)?\b|\")",
                        re.IGNORECASE)),
    ("mm", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*mm\b", re.IGNORECASE)),
    ("ft", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*{_H}?\s*(?:ft|feet|foot)\b",
                      re.IGNORECASE)),
    ("lb", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*{_H}?\s*(?:lbs?|pounds?)\b",
                      re.IGNORECASE)),
    ("degree", re.compile(rf"\b({_NUM}){_RANGE_SEP}?({_NUM})?\s*(?:°|degrees?)\b",
                          re.IGNORECASE)),
    ("dimension", re.compile(rf"\b({_NUM})\s*[x×]\s*({_NUM})\b", re.IGNORECASE)),
]

_EPS = 1e-6


def _plain(text: str) -> str:
    """Strip HTML tags and URLs — a number inside a href/timestamp is not a claim."""
    text = _URL.sub(" ", text or "")
    return _TAG.sub(" ", text)


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def extract_numeric_claims(text: str) -> list[dict]:
    """Extract factual numeric claims from *text*.

    Each claim is a dict: {"raw": matched substring, "kind": unit category,
    "values": tuple of 1-2 floats}. Only numbers anchored to a unit/currency/date word are
    extracted — a bare "5" or "2026" with nothing around it is structural, not a claim, and is
    never returned.
    """
    plain = _plain(text)
    claims: list[dict] = []
    claimed: list[tuple[int, int]] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(plain):
            span = m.span()
            if any(span[0] < e and s < span[1] for s, e in claimed):
                continue  # already claimed by an earlier (more specific) pattern
            groups = [g for g in m.groups() if g]
            values = tuple(v for v in (_to_float(g) for g in groups) if v is not None)
            if not values:
                continue
            claimed.append(span)
            claims.append({"raw": m.group(0).strip(), "kind": kind, "values": values})
    return claims


def check_numeric_claims(article_text: str, source_text: str) -> tuple[list[str], list[str]]:
    """Check every numeric claim in *article_text* against *source_text*.

    A claim is supported if every number it contains (one, or two for a range) appears among
    the same-kind numbers stated in the source, or falls within a same-kind range the source
    states — commas, "to" vs "-", and unit synonyms (gauge/ga, ft/feet/foot, lb/pounds...) are
    all reasonable variance. The unit-kind itself must match: a "24" that grounds a gauge claim
    does not also ground an unrelated "24 mph" claim elsewhere.

    Returns:
        (supported, unsupported) — lists of the raw claim substrings from article_text.
    """
    singles: dict[str, set[float]] = {}
    ranges: dict[str, list[tuple[float, float]]] = {}
    for c in extract_numeric_claims(source_text):
        vals = c["values"]
        singles.setdefault(c["kind"], set()).update(vals)
        if len(vals) == 2:
            lo, hi = min(vals), max(vals)
            ranges.setdefault(c["kind"], []).append((lo, hi))

    def _value_supported(kind: str, v: float) -> bool:
        if v in singles.get(kind, ()):
            return True
        return any(lo - _EPS <= v <= hi + _EPS for lo, hi in ranges.get(kind, ()))

    supported: list[str] = []
    unsupported: list[str] = []
    for c in extract_numeric_claims(article_text):
        if all(_value_supported(c["kind"], v) for v in c["values"]):
            supported.append(c["raw"])
        else:
            unsupported.append(c["raw"])
    return supported, unsupported
