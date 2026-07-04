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
    main_entity = [
        {
            "@type": "Question",
            "name": item["q"],
            "acceptedAnswer": {
                "@type": "Answer",
                "text": item["a"],
            },
        }
        for item in faq
    ]
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": main_entity,
    }


def build_article(
    headline: str,
    description: str,
    author_name: str,
    date_published: str,
    url: str,
) -> dict:
    """Build a schema.org Article dict.

    Args:
        headline:       Article headline (≤ 110 chars recommended).
        description:    Short article description / meta description.
        author_name:    Full name of the author or organisation.
        date_published: ISO 8601 date string, e.g. "2024-03-15".
        url:            Canonical URL of the published article.

    Returns:
        dict with @context / @type and all required Article fields.
    """
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "author": {
            "@type": "Person",
            "name": author_name,
        },
        "datePublished": date_published,
        "url": url,
    }
