"""Pure pillar+cluster content plan builder — no I/O, no LLM calls.

Ported from seo-aio functions/api/admin/articles/strategy.ts (buildPlanFromSerp).

Algorithm (mirrors seo-aio Round-19 SERP-driven path):
  1. Filter keywords to topic candidates (substring match).
  2. Classify each candidate via core.serp_analysis.classify_keyword + extract_paa_questions.
  3. Pillar = highest-PAA-density keyword; clusters = answer-box / faq targets, unranked.
  4. Build internal_link_map: every cluster slug → pillar slug.

Uses core.serp_analysis interfaces:
    classify_keyword(serp)       -> {"intent": str, "template": str}
    extract_paa_questions(serp)  -> list[str]
    analyze_title_patterns(serp) -> dict

If core/serp_analysis.py is absent at import time the module raises ImportError
early — tests mock it.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a string to a URL-safe kebab-case slug (max 80 chars)."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:80]


def _capitalize(s: str) -> str:
    """Title-case every word."""
    return " ".join(w.capitalize() for w in s.split())


_TEMPLATE_SCORE: dict[str, int] = {
    "how_to": 3,
    "faq": 4,
    "comparison": 2,
    "listicle": 1,
    "educational": 1,
    "service_page": 0,
}


def _cluster_score(template: str) -> int:
    """Score a template for cluster desirability (higher = prefer as cluster)."""
    return _TEMPLATE_SCORE.get(template, 1)


def _topic_match(keyword: str, topic: str, kw_topic: str) -> bool:
    """Return True if keyword or its topic field matches the requested topic."""
    topic_lower = topic.lower()
    return topic_lower in keyword.lower() or topic_lower in kw_topic.lower()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_plan(keywords: list[dict], serps: dict) -> dict:
    """Build a pillar + cluster content plan from a keyword list and SERP data.

    Args:
        keywords: List of keyword dicts.  Each must have at minimum::

            {
                "keyword": str,          # the keyword string
                "intent":  str,          # informational|commercial|transactional|navigational
                "topic":   str,          # broad topic label (optional, defaults to "")
                "difficulty": str        # easy|medium|hard (optional)
            }

        serps: Mapping of ``keyword_string → serp_dict`` (as returned by
               adapters.serper.fetch_serp or a test fixture).  Keywords that
               lack a SERP entry are still usable but get ``paa_count=0`` and
               template ``"educational"``.

    Returns:
        Plan dict::

            {
                "topic":            str,
                "pillar":           {keyword, title, slug, intent, angle,
                                     outline, target_words},
                "clusters":         [{keyword, title, slug, intent, angle,
                                      outline, target_words}, ...],
                "internal_link_map": {cluster_slug: pillar_slug, ...},
            }

    Raises:
        ValueError: if fewer than 4 keyword candidates are available after
                    filtering (mirrors seo-aio's ``return null`` guard).
    """
    # Lazy import so callers that don't need SERP analysis can still import
    # the module without the dependency being available.
    from core.serp_analysis import classify_keyword, extract_paa_questions  # noqa: PLC0415

    # ── 1. Infer topic from keywords if not stored on items ──────────────────
    # Use the most common topic field; fall back to the first keyword's keyword.
    topic_votes: dict[str, int] = {}
    for kw in keywords:
        t = (kw.get("topic") or "").strip()
        if t:
            topic_votes[t] = topic_votes.get(t, 0) + 1
    topic = max(topic_votes, key=lambda k: topic_votes[k]) if topic_votes else (
        keywords[0]["keyword"] if keywords else "general"
    )

    # ── 2. Filter to informational / commercial candidates ───────────────────
    candidates = [
        kw for kw in keywords
        if kw.get("intent") in ("informational", "commercial")
    ]
    if len(candidates) < 4:
        raise ValueError(
            f"Insufficient keyword candidates: need ≥4 informational/commercial keywords, "
            f"got {len(candidates)}. Add more keywords or loosen intent filter."
        )

    # ── 3. Classify each candidate via SERP data ─────────────────────────────
    classified: list[dict] = []
    for kw in candidates:
        kw_str = kw["keyword"]
        serp = serps.get(kw_str) or {}
        profile = (
            classify_keyword(serp) if serp
            else {"intent": kw.get("intent", "informational"), "template": "educational"}
        )
        paa_count = len(extract_paa_questions(serp)) if serp else 0
        classified.append({
            "kw": kw,
            "profile": profile,
            "paa_count": paa_count,
        })

    # ── 4. Pillar selection — most PAA-dense, tie-break by keyword length ────
    classified.sort(
        key=lambda c: (c["paa_count"], len(c["kw"]["keyword"])),
        reverse=True,
    )
    pillar_entry = classified[0]
    pillar_kw = pillar_entry["kw"]
    pillar_slug = _slugify(pillar_kw["keyword"])
    pillar_title = f"{_capitalize(pillar_kw['keyword'])}: A Comprehensive Guide"

    pillar = {
        "keyword": pillar_kw["keyword"],
        "title": pillar_title,
        "slug": pillar_slug,
        "intent": pillar_kw.get("intent", "informational"),
        "angle": (
            f"PILLAR: comprehensive overview of {topic}. "
            "This keyword has the most People-Also-Ask depth in the topic, naturally a pillar. "
            "Answer all the major sub-questions; link DOWN to specific cluster articles for deep-dives."
        ),
        "outline": [
            f"What is {topic}?",
            f"Who {topic} is for",
            "Key benefits and outcomes",
            "How to choose / what to look for",
            "Costs and considerations",
            "Common mistakes to avoid",
            "When to consult a professional",
            "Next steps",
        ],
        "target_words": 2500,
    }

    # ── 5. Cluster selection — prefer faq / how_to / comparison templates ────
    cluster_candidates = [
        c for c in classified[1:]
        # Exclude pillar keyword
        if c["kw"]["keyword"] != pillar_kw["keyword"]
    ]
    cluster_candidates.sort(
        key=lambda c: (_cluster_score(c["profile"].get("template", "")), c["paa_count"]),
        reverse=True,
    )

    seen_slugs: set[str] = {pillar_slug}
    clusters: list[dict] = []
    for c in cluster_candidates:
        if len(clusters) >= 12:
            break
        slug = _slugify(c["kw"]["keyword"])
        # Deduplicate slugs
        if slug in seen_slugs:
            n = 2
            while f"{slug}-{n}" in seen_slugs and n < 20:
                n += 1
            slug = f"{slug}-{n}"
        seen_slugs.add(slug)
        tmpl = c["profile"].get("template", "educational")
        if tmpl == "faq":
            angle = (
                f'Answer-rich article — Google\'s PAA shows user questions. '
                f'Lead with answer-first lede; structure as Q&A. '
                f'Link UP to the pillar "{pillar_title}".'
            )
        elif tmpl == "how_to":
            angle = (
                f"Procedural guide — top-3 SERP shows step-by-step format wins. "
                f'Link UP to the pillar "{pillar_title}".'
            )
        elif tmpl == "comparison":
            angle = (
                f"Comparison content — top-3 SERP has versus / alternatives format. "
                f'Link UP to the pillar "{pillar_title}".'
            )
        else:
            angle = (
                f'Focused deep-dive on this specific aspect of {topic}. '
                f'Link UP to the pillar "{pillar_title}" in intro and near-end section.'
            )
        clusters.append({
            "keyword": c["kw"]["keyword"],
            "title": _capitalize(c["kw"]["keyword"]),
            "slug": slug,
            "intent": c["kw"].get("intent", "informational"),
            "angle": f'CLUSTER (under pillar "{pillar_title}"): {angle}',
            "outline": [
                "Direct answer (40-60 word lede)",
                "Detailed explanation",
                "Specific examples or data",
                "Common mistakes",
                "Related topics (link to pillar + sibling clusters)",
            ],
            "target_words": 1800,
        })

    # ── 6. Internal-link map ──────────────────────────────────────────────────
    internal_link_map = {c["slug"]: pillar_slug for c in clusters}

    return {
        "topic": topic,
        "pillar": pillar,
        "clusters": clusters,
        "internal_link_map": internal_link_map,
    }
