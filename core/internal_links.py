"""Configurable map of Perkins Roofing SERVICES pages for internal linking (R2/SEO audit + Wendy).

Pure data + pure matching — no I/O, no LLM. jobs.article_job appends the actual
<a> tags deterministically (append-only, never invented prose); this module only
decides WHICH service pages are relevant to a given article's text.

Slugs VERIFIED against perkinsroofing.net's live sitemap + HTTP 200 checks (2026-07-22).
The earlier naming-convention guesses shipped 2 hard 404s (/roof-replacement/,
/flat-roofing/) and 4 non-canonical redirects (roof-repair, roof-inspection, metal-roofing,
tile-roofing) — all corrected below to the real permalinks. Anchor copy may still be tuned
with Wendy/Tim, but the URLs now resolve 200 directly.
"""
from __future__ import annotations

BASE_URL = "https://perkinsroofing.net"

# Slugs verified live (sitemap + 200) 2026-07-22 — see module docstring.
SERVICE_LINKS: list[dict] = [
    {
        "service": "roof repair",
        "url": f"{BASE_URL}/roof-repair-services/",
        "anchor": "roof repair services",
        "keywords": ["roof repair", "repair your roof", "roof leak repair", "roofing repair"],
    },
    {
        "service": "roof replacement",
        "url": f"{BASE_URL}/new-roof-installers/",
        "anchor": "new roof installation",
        "keywords": ["roof replacement", "replace your roof", "new roof installation", "reroofing"],
    },
    {
        "service": "roof inspection",
        "url": f"{BASE_URL}/roof-insurance-inspections/",
        "anchor": "a professional roof inspection",
        "keywords": ["roof inspection", "roof assessment", "inspect your roof"],
    },
    {
        "service": "commercial roofing",
        "url": f"{BASE_URL}/commercial-roofing/",
        "anchor": "commercial roofing services",
        "keywords": ["commercial roofing", "commercial roof", "business roofing"],
    },
    {
        "service": "residential roofing",
        "url": f"{BASE_URL}/residential-roofing/",
        "anchor": "residential roofing services",
        "keywords": ["residential roofing", "residential roof", "home roofing", "house roof"],
    },
    {
        "service": "metal roofing",
        "url": f"{BASE_URL}/metal-roofing-company/",
        "anchor": "metal roofing services",
        "keywords": ["metal roof", "metal roofing", "standing seam"],
    },
    {
        "service": "tile roofing",
        "url": f"{BASE_URL}/tile-roofing-company/",
        "anchor": "tile roofing services",
        "keywords": ["tile roof", "tile roofing", "clay tile", "concrete tile"],
    },
    {
        "service": "flat roofing",
        "url": f"{BASE_URL}/flat-roofs/",
        "anchor": "flat roofing services",
        "keywords": ["flat roof", "flat roofing", "tpo roof", "modified bitumen"],
    },
    {
        "service": "shingle roofing",
        "url": f"{BASE_URL}/shingle-roofs-company/",
        "anchor": "shingle roofing services",
        "keywords": ["shingle roof", "shingle roofing", "asphalt shingle", "architectural shingle", "3-tab"],
    },
    {
        "service": "gutters",
        "url": f"{BASE_URL}/gutter-sheet-metal-services/",
        "anchor": "gutter and sheet metal services",
        "keywords": ["gutter", "downspout", "roof drainage", "seamless gutter"],
    },
]

# Slugs of the real service PAGES on perkinsroofing.net (not articles). The repair
# pass must treat relative links to these as valid, not unwrap them as dead article
# cross-links. Derived from SERVICE_LINKS so the two never drift.
import re as _re  # noqa: E402

SERVICE_SLUGS: frozenset[str] = frozenset(
    _re.sub(r"^/|/$", "", e["url"].replace(BASE_URL, "")) for e in SERVICE_LINKS
)


def matching_service_links(text: str, *, limit: int = 3) -> list[dict]:
    """Return up to *limit* SERVICE_LINKS entries whose keywords appear in *text*.

    Case-insensitive substring match, in SERVICE_LINKS order. Deliberately never
    returns a service the article doesn't actually mention — links stay contextual
    rather than spammed onto every post regardless of topic.
    """
    text_lower = (text or "").lower()
    matches = []
    for entry in SERVICE_LINKS:
        if len(matches) >= limit:
            break
        if any(kw in text_lower for kw in entry["keywords"]):
            matches.append(entry)
    return matches
