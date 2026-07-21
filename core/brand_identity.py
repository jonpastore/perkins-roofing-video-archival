"""Canonical business identity for tenant 1 (Perkins Roofing) — the single source of NAP.

All values verified 2026-07-16 from the company's own live site (perkinsroofing.net JSON-LD),
Florida Sunbiz corporate records, and BBB. Sources noted inline. This is deliberately ONE place:
NAP duplicated across articles is drift waiting to happen (Google's own guidance — put the
business identity in a single @id-addressed node, reference it everywhere else).

Multi-tenant note: only tenant 1 exists today. When a second tenant lands, move this into
tenant settings (core/tenant_settings.py) keyed by tenant_id; the builders in core/jsonld.py
already take the data as a dict, so nothing there changes.

Canonical domain is perkinsroofing.net (the live site that already ships this exact schema via
Rank Math), NOT the myftpupload staging host — so the Organization @id resolves to the same
entity Google already knows.
"""
from __future__ import annotations

ORG_ID = "https://perkinsroofing.net/#organization"
AUTHOR_ID = "https://perkinsroofing.net/tim-kanak-vice-president/#person"

# schema.org RoofingContractor (a LocalBusiness subtype — matches what the live site uses).
# Miami HQ address: PERKINS ROOFING CORPORATION, oldest branch, Sunbiz doc L84213 filed 1990.
ORGANIZATION: dict = {
    "id": ORG_ID,
    "type": "RoofingContractor",
    "name": "Perkins Roofing Corp.",
    "url": "https://perkinsroofing.net/",
    "logo": "https://perkinsroofing.net/wp-content/uploads/2026/04/perkins-logo-sq.jpg",
    "telephone": "+1-305-642-7663",          # site-displayed Miami HQ line (not the BBB call-tracking number)
    "email": "hello@perkinsroofing.net",
    "street": "575 NW 152nd St",
    "city": "Miami",
    "region": "FL",
    "postal_code": "33169",
    "country": "US",
    "area_served": [
        "Miami-Dade County", "Broward County", "Palm Beach County",
        "Martin County", "St. Lucie County", "Monroe County",
    ],
    "opening_hours": ["Mo-Fr 08:00-17:00", "Sa 09:00-13:00"],
    "same_as": [
        "https://www.facebook.com/PerkinsRoofingCorp/",
        "https://www.instagram.com/perkinsroofingcorp/",
        "https://www.youtube.com/@perkinsroofingcorp",
        "https://www.linkedin.com/company/perkins-roofing-corp",
        "https://www.tiktok.com/@perkinsroofingcorp",
        "https://maps.app.goo.gl/CtHpswior56K4Nb59",
    ],
    "license": "CCC1331944",                  # FL roofing contractor license (site + BBB)
}

# Tim Kanak — President & Owner (site bio jobTitle "Owner"); FL licensed roofing contractor since
# 2019; the face of the brand in the videos. A named Person author with @id + sameAs is the
# per-article E-E-A-T lever that measurably lifts AI-answer-engine citation.
AUTHOR: dict = {
    "id": AUTHOR_ID,
    "name": "Tim Kanak",
    "job_title": "Owner",
    "url": "https://perkinsroofing.net/tim-kanak-vice-president/",
    "image": "https://b3177863.smushcdn.com/3177863/wp-content/uploads/2026/05/tim-kanak-principal-consultant.webp",
    "same_as": ["https://www.linkedin.com/in/timkanak/"],
    "works_for": ORG_ID,
    "knows_about": [
        "roofing", "tile roofing", "flat roof waterproofing", "roof insurance claims",
        "Florida High-Velocity Hurricane Zone building code",
    ],
}

# Footer CTA link appended to every generated article (jobs/article_job._ensure_footer_link).
# Canonical channel-ID form — stable even if the @handle above ever changes.
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/UChJZpBYXOuR0j1EHJugv5hg"
