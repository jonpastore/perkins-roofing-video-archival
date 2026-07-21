"""Configurable map of Perkins Roofing SERVICES pages for internal linking (R2/SEO audit + Wendy).

Pure data + pure matching — no I/O, no LLM. jobs.article_job appends the actual
<a> tags deterministically (append-only, never invented prose); this module only
decides WHICH service pages are relevant to a given article's text.

*** SLUGS/ANCHORS UNCONFIRMED — confirm against the live site before trusting them. ***
Every url below is the obvious/expected path for its service based on naming
convention, NOT verified against perkinsroofing.net's actual permalinks. Update
SERVICE_LINKS with the real slugs (and any anchor copy Wendy/Tim prefer) once
confirmed with the site.
"""
from __future__ import annotations

BASE_URL = "https://perkinsroofing.net"

# TODO(confirm-slugs-with-site): placeholder scaffold, not verified live URLs.
SERVICE_LINKS: list[dict] = [
    {
        "service": "roof repair",
        "url": f"{BASE_URL}/roof-repair/",
        "anchor": "roof repair services",
        "keywords": ["roof repair", "repair your roof", "roof leak repair", "roofing repair"],
    },
    {
        "service": "roof replacement",
        "url": f"{BASE_URL}/roof-replacement/",
        "anchor": "roof replacement services",
        "keywords": ["roof replacement", "replace your roof", "new roof installation", "reroofing"],
    },
    {
        "service": "roof inspection",
        "url": f"{BASE_URL}/roof-inspection/",
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
        "url": f"{BASE_URL}/metal-roofing/",
        "anchor": "metal roofing services",
        "keywords": ["metal roof", "metal roofing", "standing seam"],
    },
    {
        "service": "tile roofing",
        "url": f"{BASE_URL}/tile-roofing/",
        "anchor": "tile roofing services",
        "keywords": ["tile roof", "tile roofing", "clay tile", "concrete tile"],
    },
    {
        "service": "flat roofing",
        "url": f"{BASE_URL}/flat-roofing/",
        "anchor": "flat roofing services",
        "keywords": ["flat roof", "flat roofing", "tpo roof", "modified bitumen"],
    },
]


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
