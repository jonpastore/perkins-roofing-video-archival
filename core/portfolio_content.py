"""Project-page write-up + JSON-LD (pure — no I/O, no LLM).

WHY DETERMINISTIC, NOT GENERATED
Articles were ~90% invented when they were generated from thin retrieval, and the fix was
grounding, not a better prompt. A project record carries very few facts — name, city, section,
dates, a note, and the curated media — so an LLM asked for 500 words about it would fabricate
the other 450. Everything here is assembled from fields that exist; a page reads short rather
than confident-and-wrong. If Perkins supplies real project detail later, that is what should
lengthen these pages.

SCHEMA SCOPE — mirrors the article standard rather than inventing a second one:
  * ``schema_scoped``  — articles emit ONLY FAQPage + VideoObject because Rank Math already
    emits Article/Organization/WebPage/BreadcrumbList, and shipping our own duplicates it
    (fixed 2026-07-22 after exactly that). Project pages get the same treatment: nothing that
    Rank Math owns. ImageObject is added because Rank Math does NOT emit it for gallery images
    and it is the multimodal-AEO lever — AI engines parse ImageObject captions/creator to
    attribute and cite images.
  * ``videoobject_only_embedded`` — Wendy, 2026-07-28: "Google says we can only have video
    object schema for embedded videos, not links to videos." The gallery renders a real
    <video> player per curated video, so one VideoObject each is legitimate. A project whose
    video was NOT curated in gets none.

Every schema field mirrors something visible on the page — an ImageObject caption IS the
image's alt text — because schema that disagrees with visible content is penalised by both
Google and AI engines.
"""
from __future__ import annotations

import html
import re
from typing import Any, Iterable

from core.portfolio import infer_roof_type
from core.portfolio_facts import scope_sentence
from core.seo import ensure_toc

# Location pages live under this tree — e.g.
# /south-florida-service-areas/miami-dade/sunny-isles-beach/. County is not in the project
# record, so the link is built from the city slug and validated by the caller against the
# known page list; an unmatched city yields NO link rather than a guessed 404.
_LOCATION_ROOT = "/south-florida-service-areas"

# Roof type -> the service page that covers it. Keys match core.portfolio's canonical labels.
_SERVICE_PAGES = {
    "Clay Barrel Tile": "/services/tile-roofing/",
    "Tile": "/services/tile-roofing/",
    "Standing Seam Metal": "/services/metal-roofing/",
    "Metal": "/services/metal-roofing/",
    "Asphalt Shingle": "/services/shingle-roofing/",
    "TPO": "/services/flat-roofing/",
    "Flat/Built-Up": "/services/flat-roofing/",
    "Silicone Coating": "/services/roof-coatings/",
    "Polyglass Silicone Restoration": "/services/roof-coatings/",
    "Roof Coating": "/services/roof-coatings/",
    "Soffit": "/services/soffit-fascia/",
    "Concrete Repair": "/services/concrete-repair/",
}


def city_slug(city: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (city or "").lower()).strip("-")


def service_page_for(record: dict, content: str = "",
                     scope_lines: Iterable[str] | None = None) -> tuple[str | None, str | None]:
    """(url, label) of the service page matching this project's roof type, or (None, None).

    The contract scope is a better source than the project NAME: "Miami Beach Olsen Condo"
    names no system, but its scope lines say "13\" Concrete Tile Re-Roof". Without this, such a
    project links to no service page at all.
    """
    scope_text = " ".join(scope_lines or [])
    roof_type = record.get("new_roof_type") or infer_roof_type(
        record.get("name"), content, scope_text)
    if not roof_type:
        return None, None
    return _SERVICE_PAGES.get(roof_type), roof_type


def location_page_for(record: dict, known_location_slugs: Iterable[str] | None = None) -> str | None:
    """Location page URL for the project's city.

    ``known_location_slugs`` are the slugs that actually exist on the site (the caller reads
    them from WordPress). Without that list we return None rather than emit a link that 404s —
    a dead internal link is worse for the page than a missing one.
    """
    slug = city_slug(record.get("city"))
    if not slug or not known_location_slugs:
        return None
    for known in known_location_slugs:
        if known.rstrip("/").endswith(slug):
            return f"/{known.strip('/')}/"
    return None


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def build_meta(record: dict) -> str:
    """Meta description, padded toward the 120-160 band ONLY with facts we hold."""
    name = record.get("name", "").strip()
    city = (record.get("city") or "South Florida").strip()
    _, roof_type = service_page_for(record)
    kind = (record.get("section") or "commercial").lower()
    bits = [f"{name} — a {kind} roofing project in {city}, Florida"]
    if roof_type:
        bits.append(f"{roof_type.lower()} system")
    bits.append("installed by Perkins Roofing")
    meta = ", ".join(bits) + "."
    # Meta descriptions under ~120 chars get rewritten by Google. Extend toward the band with
    # statements about the PAGE (true by construction), never invented project detail.
    if len(meta) < 120:
        meta += " See project photos, scope and location details."
    return meta[:160]


def build_faq(record: dict, *, photo_count: int = 0, video_count: int = 0,
              scope_lines: Iterable[str] | None = None) -> list[dict]:
    """Q&A built ONLY from fields the record holds — never a generated answer.

    A question whose answer we do not have is omitted, so a thin record yields a short FAQ
    rather than a confident invention. These are rendered visibly on the page AND emitted as
    FAQPage schema; the article standard allows FAQPage, and it is the single strongest AEO
    lever we have (AI engines lift Q&A pairs almost verbatim).
    """
    name = (record.get("name") or "this project").strip()
    city = (record.get("city") or "").strip()
    _, roof_type = service_page_for(record, scope_lines=scope_lines)
    start, end = (record.get("date_start") or "").strip(), (record.get("date_end") or "").strip()

    faq: list[dict] = []
    if roof_type:
        faq.append({
            "q": f"What roof system was installed at {name}?",
            "a": f"Perkins Roofing installed a {roof_type.lower()} system.",
        })
    if city:
        faq.append({
            "q": f"Where is {name} located?",
            "a": f"The property is in {city}, Florida, within Perkins Roofing's service area.",
        })
    if start and end:
        faq.append({
            "q": f"When was the work at {name} carried out?",
            "a": f"Crews were on site from {start} to {end}.",
        })
    elif start:
        faq.append({"q": f"When did work begin at {name}?", "a": f"Work began {start}."})
    if photo_count:
        documented = f"{photo_count} photographs"
        if video_count:
            documented += f" and {video_count} site videos"
        faq.append({
            "q": f"Is there photographic documentation of {name}?",
            "a": f"Yes — {documented} were captured on site by the crew and are shown above.",
        })
    scope = list(scope_lines or [])
    if scope:
        faq.append({
            "q": f"What work was included at {name}?",
            "a": f"The contracted scope covered {scope_sentence(scope)}.",
        })
    if (record.get("notes") or "").strip():
        faq.append({
            "q": f"What was the scope of work at {name}?",
            "a": record["notes"].strip(),
        })
    return faq


def render_faq(faq: Iterable[dict]) -> str:
    """Visible FAQ markup. Schema without the matching visible content is a mismatch."""
    items = list(faq)
    if not items:
        return ""
    out = ["<h2>Frequently asked questions</h2>"]
    for pair in items:
        out.append(f"<h3>{_esc(pair['q'])}</h3><p>{_esc(pair['a'])}</p>")
    return "".join(out)


def build_write_up(
    record: dict,
    *,
    gallery_html: str = "",
    known_location_slugs: Iterable[str] | None = None,
    photo_count: int = 0,
    video_count: int = 0,
    scope_lines: Iterable[str] | None = None,
) -> str:
    """Assemble the project page body from known fields.

    Shape follows the article standard: an answer-first opening sentence, H2 sections, a
    definition list of specifics (AI engines extract lists and tables far more reliably than
    prose), internal links to the service and location pages, then the curated gallery.
    """
    name = record.get("name", "").strip()
    city = (record.get("city") or "").strip()
    where = f"{city}, Florida" if city else "South Florida"
    kind = (record.get("section") or "commercial").lower()
    scope = list(scope_lines or [])
    service_url, roof_type = service_page_for(record, scope_lines=scope)
    location_url = location_page_for(record, known_location_slugs)

    system = f"{roof_type.lower()} roof" if roof_type else "roof"
    parts: list[str] = [
        # Answer-first: a complete sentence, and the specifics, before anything else.
        f"<p>Perkins Roofing completed a {_esc(kind)} {_esc(system)} project at "
        f"{_esc(name)} in {_esc(where)}.</p>"
    ]

    facts: list[tuple[str, str]] = []
    if roof_type:
        facts.append(("Roof system", roof_type))
    if city:
        facts.append(("Location", where))
    facts.append(("Project type", "Commercial" if kind == "commercial" else "Residential"))
    start, end = (record.get("date_start") or "").strip(), (record.get("date_end") or "").strip()
    if start and end:
        facts.append(("On site", f"{start} – {end}"))
    elif start:
        facts.append(("Started", start))
    if photo_count:
        facts.append(("Documented", f"{photo_count} site photographs"
                                    + (f" and {video_count} videos" if video_count else "")))

    if facts:
        parts.append("<h2>Project details</h2><ul>")
        parts.extend(f"<li><strong>{_esc(k)}:</strong> {_esc(v)}</li>" for k, v in facts)
        parts.append("</ul>")

    # Scope from the contract record — the only source of real project detail we have, and
    # already filtered to installed (non-optional) work by core.portfolio_facts.
    notes = (record.get("notes") or "").strip()
    if scope or notes:
        parts.append("<h2>Scope of work</h2>")
        if notes:
            parts.append(f"<p>{_esc(notes)}</p>")
        if scope:
            parts.append("<p>The contracted scope included:</p><ul>")
            parts.extend(f"<li>{_esc(line)}</li>" for line in scope)
            parts.append("</ul>")

    links = []
    if service_url and roof_type:
        links.append(f'<a href="{service_url}">{_esc(roof_type)} roofing services</a>')
    if location_url and city:
        links.append(f'<a href="{location_url}">roofing in {_esc(city)}</a>')
    if links:
        parts.append("<h2>Related</h2><p>" + " · ".join(links) + "</p>")

    if gallery_html:
        parts.append("<h2>Project gallery</h2>" + gallery_html)

    parts.append(render_faq(build_faq(record, photo_count=photo_count, video_count=video_count)))

    # Same TOC helper the articles use — Wendy's criteria require an in-content TOC, and the
    # anchor links are also what the rm_toc signal counts.
    return ensure_toc("".join(parts))


def build_project_jsonld(
    record: dict,
    selections: Iterable[dict],
    media_by_id: dict[str, dict],
    *,
    organization_id: str | None = None,
    faq: Iterable[dict] | None = None,
) -> list[dict]:
    """FAQPage + ImageObject per curated photo + VideoObject per curated (embedded) video.

    Deliberately emits NOTHING that Rank Math already owns — no Article, Organization,
    WebPage or BreadcrumbList. See the module docstring.

    ``organization_id`` references the single canonical NAP node when the site has one, so the
    media is attributed without duplicating business identity.
    """
    from core.jsonld import build_faq_page  # noqa: PLC0415

    nodes: list[dict] = []
    city = (record.get("city") or "").strip()
    place = {"@type": "Place", "name": f"{city}, Florida"} if city else None

    faq_items = list(faq or [])
    if faq_items:
        nodes.append(build_faq_page(faq_items))

    for index, sel in enumerate(selections):
        row = media_by_id.get(f"{sel.get('kind')}:{sel.get('id')}")
        if not row or not row.get("url"):
            continue

        if sel.get("kind") == "photo":
            alt = (sel.get("alt") or "").strip()
            node: dict[str, Any] = {
                "@context": "https://schema.org",
                "@type": "ImageObject",
                "contentUrl": row["url"],
                # caption IS the visible alt text — schema that disagrees with the page is
                # treated as a mismatch by Google and by AI engines.
                "caption": alt,
                "representativeOfPage": index == 0,
            }
            if alt:
                node["name"] = alt
            if place:
                node["contentLocation"] = place
            if organization_id:
                node["creator"] = {"@id": organization_id}
            if row.get("captured_at"):
                node["dateCreated"] = row["captured_at"]
            nodes.append(node)

        elif sel.get("kind") == "video":
            node = {
                "@context": "https://schema.org",
                "@type": "VideoObject",
                "name": f"{record.get('name', 'Project')} — site video",
                "description": build_meta(record),
                "contentUrl": row["url"],
            }
            if row.get("thumbnail_url"):
                node["thumbnailUrl"] = row["thumbnail_url"]
            if row.get("captured_at"):
                node["uploadDate"] = row["captured_at"]
            if place:
                node["contentLocation"] = place
            nodes.append(node)

    return nodes
