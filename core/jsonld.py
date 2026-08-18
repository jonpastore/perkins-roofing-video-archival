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
    # Fields the live Rank Math graph publishes today. Omitting any of them on a migration
    # away from Rank Math is a silent downgrade of an entity Google has already indexed.
    if org.get("geo"):
        node["geo"] = {"@type": "GeoCoordinates", **org["geo"]}
        lat, lon = org["geo"].get("latitude"), org["geo"].get("longitude")
        if lat and lon:
            node["hasMap"] = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    if org.get("alternate_name"):
        node["alternateName"] = org["alternate_name"]
    if org.get("price_range"):
        node["priceRange"] = org["price_range"]
    if org.get("description"):
        node["description"] = org["description"]
    if org.get("license"):
        # Not emitted by Rank Math — a real gain on migration. A FL roofing licence is the
        # single strongest trust signal this business has.
        node["hasCredential"] = {
            "@type": "EducationalOccupationalCredential",
            "credentialCategory": "license",
            "identifier": org["license"],
        }
    return {k: v for k, v in node.items() if v is not None}


def build_website(org: dict, *, site_url: str, site_name: str) -> dict:
    """The WebSite node, publisher-linked to the Organization.

    Rank Math emits this on every page; nothing in this codebase did before, so a migration
    would have dropped it entirely.
    """
    node = {
        "@type": "WebSite",
        "@id": f"{site_url.rstrip('/')}/#website",
        "url": site_url,
        "name": site_name,
        "publisher": {"@id": org["id"]},
        "inLanguage": "en-US",
    }
    if org.get("alternate_name"):
        node["alternateName"] = org["alternate_name"]
    return node


def build_webpage(
    url: str,
    name: str,
    *,
    site_url: str,
    description: str | None = None,
    date_published: str | None = None,
    date_modified: str | None = None,
    breadcrumb_id: str | None = None,
    primary_image: str | None = None,
) -> dict:
    """The per-URL WebPage node, linked to the WebSite and its BreadcrumbList.

    ``isPartOf`` + ``breadcrumb`` are what tie a page into the site graph; without them the
    per-page nodes float free and Google treats each page as an island.
    """
    node = {
        "@type": "WebPage",
        "@id": f"{url}#webpage",
        "url": url,
        "name": name,
        "isPartOf": {"@id": f"{site_url.rstrip('/')}/#website"},
        "inLanguage": "en-US",
    }
    if description:
        node["description"] = description
    if date_published:
        node["datePublished"] = date_published
    if date_modified:
        node["dateModified"] = date_modified
    if breadcrumb_id:
        node["breadcrumb"] = {"@id": breadcrumb_id}
    if primary_image:
        node["primaryImageOfPage"] = {"@type": "ImageObject", "url": primary_image}
    return node


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


# ---------------------------------------------------------------------------
# The FULL @graph — for life after Rank Math
# ---------------------------------------------------------------------------
#
# Everything above this line was, until now, half-wired: build_faq_page and
# build_video_object had callers, while build_article, build_organization, build_person and
# build_breadcrumb_list had NONE anywhere in the codebase. That was not an oversight — the
# per-page schema we inject is deliberately scoped to the two node types Rank Math does not
# emit, because emitting Article/Organization/Person/BreadcrumbList alongside it would
# duplicate what Rank Math already puts on every page.
#
# Measured on the live site 2026-08-12:
#   staging article  -> 2 blocks: Rank Math's @graph, plus OUR FAQPage + VideoObject. No overlap.
#   prod article     -> 1 block:  Rank Math only (those posts carry no _perkins_jsonld meta).
#   the 9 project pages -> 0 blocks. No structured data at all, from anyone.
#
# So the day Rank Math goes away, every page silently loses BlogPosting/Article, Organization
# (NAP + geo + hours + sameAs), Person, WebSite, WebPage and BreadcrumbList. build_full_graph
# is what replaces it, and PUBLISH_FULL_GRAPH is what keeps it off until that day — running
# both at once is the duplication this scoping exists to avoid.

#: Node types Rank Math owns. While it is live, our injected schema must contain NONE of
#: these; once it is gone, ours must contain ALL of them. Both criteria checkers gate on this.
RANK_MATH_OWNED = frozenset({
    "Article", "BlogPosting", "Organization", "LocalBusiness", "RoofingContractor",
    "Person", "WebSite", "WebPage", "BreadcrumbList", "ListItem",
})

#: What we inject while Rank Math is live (the complement).
COMPLEMENT_TYPES = frozenset({"FAQPage", "ImageObject", "VideoObject"})


def graph_nodes(jsonld) -> list[dict]:
    """The node list, whether stored flat or as one ``{@graph: [...]}`` document."""
    nodes = [n for n in (jsonld or []) if isinstance(n, dict)]
    if len(nodes) == 1 and nodes[0].get("@graph"):
        return [n for n in nodes[0]["@graph"] if isinstance(n, dict)]
    return nodes


def full_graph_enabled() -> bool:
    """Articles and projects publish to Astro. Rank Math is not in that stack, so we emit
    the types it used to own (Organization, WebSite, WebPage, Person, BreadcrumbList,
    BlogPosting on articles). Complement-only output would silently drop those nodes."""
    return True


def build_full_graph(
    *,
    org: dict,
    author: dict,
    site_url: str,
    site_name: str,
    page_url: str,
    page_name: str,
    description: str,
    breadcrumbs: list[dict],
    date_published: str | None = None,
    date_modified: str | None = None,
    article: bool = True,
    extra_nodes: list[dict] | None = None,
) -> dict:
    """Assemble the single ``@graph`` document that replaces Rank Math's.

    One document with cross-referenced ``@id``s, not a pile of standalone nodes: that is
    Google's stated preference and it is what the live site already ships, so the migration
    keeps the same shape rather than inventing a new one.

    ``extra_nodes`` carries the FAQPage / ImageObject / VideoObject we already build, so the
    complement we emit today becomes part of the full graph tomorrow instead of a second
    <script> block competing with it.
    """
    breadcrumb = build_breadcrumb_list(breadcrumbs) if breadcrumbs else None
    breadcrumb_id = f"{page_url}#breadcrumb" if breadcrumb else None
    if breadcrumb:
        breadcrumb.pop("@context", None)
        breadcrumb["@id"] = breadcrumb_id

    organization = build_organization(org)
    organization.pop("@context", None)

    person = build_person(author)

    webpage = build_webpage(
        page_url, page_name, site_url=site_url, description=description,
        date_published=date_published, date_modified=date_modified,
        breadcrumb_id=breadcrumb_id,
    )

    graph: list[dict] = [organization, build_website(org, site_url=site_url, site_name=site_name),
                         person, webpage]
    if breadcrumb:
        graph.append(breadcrumb)

    if article:
        node = build_article(
            headline=page_name, description=description, author_name=author["name"],
            date_published=date_published or "", url=page_url,
            author={"@id": author["id"]}, publisher_id=org["id"],
            date_modified=date_modified,
        )
        node.pop("@context", None)
        # BlogPosting is what the live site uses for posts; keep the same subtype so the
        # migration is invisible to anything already consuming it.
        node["@type"] = "BlogPosting"
        node["isPartOf"] = {"@id": webpage["@id"]}
        node["mainEntityOfPage"] = {"@id": webpage["@id"]}
        graph.append(node)

    for extra in (extra_nodes or []):
        node = dict(extra)
        node.pop("@context", None)
        graph.append(node)

    return {"@context": "https://schema.org", "@graph": graph}
