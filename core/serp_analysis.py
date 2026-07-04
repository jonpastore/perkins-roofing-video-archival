"""Pure SERP analysis — no I/O, no LLM. Ported from seo-aio analysis.ts."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse  # noqa: F401 (used by _host)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _host(url: str) -> str:
    """Extract bare hostname (no www.) from a URL string. Returns '' on error."""
    try:
        return urlparse(url).hostname.replace("www.", "", 1).lower()
    except Exception:
        return ""


_INFORMATIONAL_DOMAINS = re.compile(
    r"\b(wikipedia|britannica|investopedia|healthline|webmd|mayoclinic|"
    r"medlineplus|nih\.gov|cdc\.gov|wikihow|verywell)\b",
    re.IGNORECASE,
)
_TRANSACTIONAL_DOMAINS = re.compile(
    r"\b(amazon|walmart|target|homedepot|lowes|ebay|etsy|shopify\.com|alibaba)\b",
    re.IGNORECASE,
)
_NEWS_DOMAINS = re.compile(
    r"\b(forbes|cnn|nytimes|wsj|reuters|bbc|bloomberg|techcrunch)\b",
    re.IGNORECASE,
)
_COMMERCIAL_TITLE = re.compile(
    r"\bvs\.?\b|\bversus\b|\bcompar(e|ison)\b|\bbest\s+\d+\b|\breview",
    re.IGNORECASE,
)
_INFORMATIONAL_TITLE = re.compile(
    r"\bhow\s+to\b|\bguide\b|\btutorial\b|\bsteps?\b|\bwhat\s+is\b",
    re.IGNORECASE,
)
_LOCAL_PACK_DOMAINS = re.compile(
    r"yelp|yellowpages|tripadvisor|opentable|bbb\.org|trustpilot",
    re.IGNORECASE,
)
_VIDEO_DOMAINS = re.compile(r"youtube\.com|vimeo\.com|wistia", re.IGNORECASE)


def _classify_result_intent(result: dict) -> str | None:
    """Classify a single organic result's intent. Returns None for no signal."""
    host = _host(result.get("link", ""))
    title = (result.get("title") or "").lower()

    if _INFORMATIONAL_DOMAINS.search(host):
        return "informational"
    if _TRANSACTIONAL_DOMAINS.search(host):
        return "transactional"
    if _NEWS_DOMAINS.search(host):
        return "informational"
    if _COMMERCIAL_TITLE.search(title):
        return "commercial"
    if _INFORMATIONAL_TITLE.search(title):
        return "informational"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_keyword(serp: dict) -> dict:
    """Classify a SERP into intent + recommended content template.

    Args:
        serp: normalized SERP dict (from adapters.serper.fetch_serp or fixture).

    Returns:
        {
            "intent": "informational" | "transactional" | "commercial" |
                      "navigational" | "mixed",
            "template": "how_to" | "faq" | "listicle" | "comparison" |
                        "service_page" | "educational",
        }
    """
    organic = serp.get("organic") or []
    paa = serp.get("peopleAlsoAsk") or []
    answer_box = serp.get("answerBox")
    knowledge_graph = serp.get("knowledgeGraph")

    # Feature flags (mirrors seo-aio's features array)
    has_answer_box = bool(
        answer_box and (answer_box.get("answer") or answer_box.get("snippet"))
    )
    has_knowledge_panel = bool(knowledge_graph)
    paa_dense = len(paa) >= 5

    top3_hosts = [_host(r.get("link", "")) for r in organic[:3]]
    has_video = any(_VIDEO_DOMAINS.search(h) for h in top3_hosts if h)
    local_count = sum(
        1
        for r in organic[:5]
        if _LOCAL_PACK_DOMAINS.search(_host(r.get("link", "")))
    )
    has_local_pack = local_count >= 2

    # Intent — majority vote across top-10, fallback "mixed"
    votes: Counter = Counter()
    for r in organic[:10]:
        intent_vote = _classify_result_intent(r)
        if intent_vote:
            votes[intent_vote] += 1

    intent = "mixed"
    for candidate, count in votes.most_common(1):
        if count >= 4:
            intent = candidate

    # Local-pack overrides mixed → transactional
    if intent == "mixed" and has_local_pack:
        intent = "transactional"

    # Template — mirrors seo-aio recommendedTemplate logic, mapped to
    # the Python enum values in the plan spec.
    if has_answer_box and intent != "transactional":
        template = "how_to"          # snippet-hijack → answer-first how-to
    elif has_local_pack or intent == "transactional":
        template = "service_page"
    elif intent == "commercial":
        template = "comparison"
    elif paa_dense:
        template = "faq"
    elif has_knowledge_panel or intent == "informational":
        template = "educational"
    elif has_video:
        template = "how_to"
    else:
        # "listicle" is the neutral/mixed fallback for when nothing fires
        template = "listicle"

    return {"intent": intent, "template": template}


def analyze_title_patterns(serp: dict) -> dict:
    """Analyze top-3 organic titles for format hints.

    Returns:
        {
            "has_number": bool,   True if ≥2 of top-3 titles start with a digit
            "has_year":   bool,   True if ≥2 of top-3 titles contain a 20xx year
            "avg_length": int,    average character length of top-3 titles
            "common_words": list[str],  non-stopword tokens in ≥2 of top-3 titles
        }
    """
    organic = serp.get("organic") or []
    top3 = organic[:3]
    if not top3:
        return {"has_number": False, "has_year": False, "avg_length": 0, "common_words": []}

    titles = [r.get("title") or "" for r in top3]

    number_led = sum(1 for t in titles if re.match(r"^\d+\s", t.strip()))
    year_present = sum(1 for t in titles if re.search(r"\b20[2-9]\d\b", t))
    avg_length = round(sum(len(t) for t in titles) / len(titles))

    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would", "should",
        "could", "this", "that", "these", "those",
    }
    word_freq: Counter = Counter()
    for title in titles:
        seen: set[str] = set()
        for token in re.sub(r"[^a-z0-9\s]", " ", title.lower()).split():
            if len(token) < 3 or token in stopwords or token in seen:
                continue
            seen.add(token)
            word_freq[token] += 1

    common_words = [w for w, c in word_freq.most_common() if c >= 2]

    return {
        "has_number": number_led >= 2,
        "has_year": year_present >= 2,
        "avg_length": avg_length,
        "common_words": common_words,
    }


def aggregate_authority_citations(top3_bodies: list[str]) -> list[str]:
    """Extract authority domains/entities cited across top-3 page bodies.

    Simplified port of seo-aio aggregateAuthorityCitations: extracts bare
    domain tokens that look like authority sources (gov, edu, org, or known
    reference sites) from plain-text bodies. Returns domains appearing in
    ≥2 of the supplied texts.

    Args:
        top3_bodies: list of plain-text page bodies (up to 3 items).

    Returns:
        Sorted list of authority domain strings seen in ≥2 bodies.
    """
    _AUTHORITY_PATTERN = re.compile(
        r"\b([\w-]+\.(?:gov|edu|org|ac\.uk|nhs\.uk))\b|"
        r"\b(wikipedia\.org|healthline\.com|webmd\.com|mayoclinic\.org|"
        r"nih\.gov|cdc\.gov|who\.int|bbc\.com|reuters\.com|"
        r"investopedia\.com|britannica\.com)\b",
        re.IGNORECASE,
    )

    domain_counts: Counter = Counter()
    for body in top3_bodies:
        seen: set[str] = set()
        for m in _AUTHORITY_PATTERN.finditer(body):
            domain = (m.group(1) or m.group(2) or "").lower()
            if domain and domain not in seen:
                seen.add(domain)
                domain_counts[domain] += 1

    return sorted(d for d, c in domain_counts.items() if c >= 2)


def extract_paa_questions(serp: dict) -> list[str]:
    """Return People-Also-Ask questions for FAQ seeding.

    Args:
        serp: normalized SERP dict.

    Returns:
        List of question strings from the peopleAlsoAsk field.
    """
    paa = serp.get("peopleAlsoAsk") or []
    return [
        item.get("question", "").strip()
        for item in paa
        if (item.get("question") or "").strip()
    ]
