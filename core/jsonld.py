"""Pure schema.org JSON-LD builders — no I/O, fully deterministic.

Each function returns a plain dict suitable for json.dumps() and insertion into
<script type="application/ld+json">. Callers (adapters/jobs) handle serialisation.
"""

from __future__ import annotations


def build_video_object(
    title: str,
    description: str,
    thumbnail_url: str,
    upload_date: str,
    content_url: str,
    embed_url: str,
    duration_iso: str,
) -> dict:
    """Build a schema.org VideoObject dict.

    Args:
        title:         Human-readable video title.
        description:   Short description / transcript excerpt.
        thumbnail_url: Absolute URL of the thumbnail image.
        upload_date:   ISO 8601 date string, e.g. "2024-03-15".
        content_url:   Direct URL to the video file or YouTube watch URL.
        embed_url:     Embed URL (e.g. https://www.youtube.com/embed/<id>).
        duration_iso:  ISO 8601 duration, e.g. "PT4M30S".

    Returns:
        dict with @context / @type and all required VideoObject fields.
    """
    return {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": title,
        "description": description,
        "thumbnailUrl": thumbnail_url,
        "uploadDate": upload_date,
        "contentUrl": content_url,
        "embedUrl": embed_url,
        "duration": duration_iso,
    }


def build_faq_page(faq: list[dict]) -> dict:
    """Build a schema.org FAQPage dict from a list of Q&A pairs.

    Args:
        faq: List of dicts with keys "q" (question text) and "a" (answer text).

    Returns:
        dict with @context / @type and mainEntity list of Questions.
    """
    # Defensive: LLM-generated FAQ items sometimes arrive shaped {"question","answer"} or
    # with a missing key. Normalize and skip entries with no question rather than KeyError
    # (which upstream catches and discards the WHOLE generated article, see topics.py).
    main_entity = []
    for item in faq:
        q = (item.get("q") or item.get("question") or "").strip()
        a = item.get("a") or item.get("answer") or ""
        if not q:
            continue
        main_entity.append({
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a},
        })
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": main_entity,
    }


def build_breadcrumb_list(items: list[dict]) -> dict:
    """Build a schema.org BreadcrumbList dict.

    Args:
        items: List of dicts with keys "name" (str) and "url" (str).
               Items should be in order from root to current page.

    Returns:
        dict with @context / @type and itemListElement list.

    Example::

        build_breadcrumb_list([
            {"name": "Home", "url": "https://perkinsroofing.net/"},
            {"name": "Blog", "url": "https://perkinsroofing.net/blog/"},
            {"name": "Article Title", "url": "https://perkinsroofing.net/blog/slug"},
        ])
    """
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": pos,
                "name": item["name"],
                "item": item["url"],
            }
            for pos, item in enumerate(items, start=1)
        ],
    }


def build_organization(org: dict) -> dict:
    """Build the single canonical Organization/LocalBusiness node with a stable @id.

    Google's guidance: put business identity (NAP) in ONE @id-addressed node, referenced
    everywhere else — do not duplicate full NAP per page. `org` is a plain data dict (see
    core.brand_identity.ORGANIZATION); this builder stays pure and client-agnostic.
    """
    node = {
        "@context": "https://schema.org",
        "@type": org.get("type", "LocalBusiness"),
        "@id": org["id"],
        "name": org["name"],
        "url": org.get("url"),
        "telephone": org.get("telephone"),
        "email": org.get("email"),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": org.get("street"),
            "addressLocality": org.get("city"),
            "addressRegion": org.get("region"),
            "postalCode": org.get("postal_code"),
            "addressCountry": org.get("country", "US"),
        },
    }
    if org.get("logo"):
        node["logo"] = {"@type": "ImageObject", "url": org["logo"]}
        node["image"] = org["logo"]
    if org.get("area_served"):
        node["areaServed"] = org["area_served"]
    if org.get("opening_hours"):
        node["openingHours"] = org["opening_hours"]
    if org.get("same_as"):
        node["sameAs"] = org["same_as"]
    return {k: v for k, v in node.items() if v is not None}


def build_person(person: dict) -> dict:
    """Build the author Person node with @id + sameAs (E-E-A-T / AI-citation signal)."""
    node = {
        "@type": "Person",
        "@id": person["id"],
        "name": person["name"],
        "url": person.get("url"),
        "jobTitle": person.get("job_title"),
    }
    if person.get("image"):
        node["image"] = person["image"]
    if person.get("same_as"):
        node["sameAs"] = person["same_as"]
    if person.get("works_for"):
        node["worksFor"] = {"@id": person["works_for"]}
    if person.get("knows_about"):
        node["knowsAbout"] = person["knows_about"]
    return {k: v for k, v in node.items() if v is not None}


def build_article(
    headline: str,
    description: str,
    author_name: str,
    date_published: str,
    url: str,
    *,
    author: dict | None = None,
    publisher_id: str | None = None,
    date_modified: str | None = None,
) -> dict:
    """Build a schema.org Article dict.

    Args:
        headline:       Article headline (≤ 110 chars recommended).
        description:    Short article description / meta description.
        author_name:    Fallback author name (used only when `author` node not given).
        date_published: ISO 8601 date string, e.g. "2024-03-15".
        url:            Canonical URL of the published article.
        author:         Full Person node (from build_person) — preferred over author_name so the
                        author carries an @id/sameAs for E-E-A-T. Falls back to a bare name.
        publisher_id:   @id of the canonical Organization node; sets publisher as a reference
                        (Google's recommended pattern) instead of duplicating org fields.
        date_modified:  ISO 8601; freshness signal.
    """
    node = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "author": author if author else {"@type": "Person", "name": author_name},
        "datePublished": date_published,
        "url": url,
        "mainEntityOfPage": url,
    }
    if publisher_id:
        node["publisher"] = {"@id": publisher_id}
    if date_modified:
        node["dateModified"] = date_modified
    return node
