"""llms.txt manifest builder — pure (no I/O). Spec: https://llmstxt.org.

AI engines (ChatGPT/Perplexity/Claude) have no push/submission API — the two real
AIO levers are (a) crawler access via robots.txt (see the robots_txt filter in
wp-plugin/perkins-jsonld) and (b) this pull-based manifest served at /llms.txt.
Serving + push I/O live in adapters/wordpress.py (push_llms_txt); this module only
builds the text, fed by the published-article index."""

from typing import Any


def build_llms_txt(business: dict[str, Any], articles: list[dict[str, Any]]) -> str:
    """Build the llms.txt manifest. Deterministic: article order preserved, no timestamps.

    business keys (all optional): name, description, about, site_url, phone, email,
    service_area. articles: dicts with title, url, optional summary — entries missing
    title or url are skipped."""
    name = business.get("name") or "Perkins Roofing"
    description = business.get("description") or ""
    about = business.get("about") or ""

    lines: list[str] = [f"# {name}"]

    if description:
        lines.extend(["", f"> {description}"])

    if about:
        lines.extend(["", "## About", "", about])

    entries = _article_lines(articles)
    if entries:
        lines.extend(["", "## Articles", "", *entries])

    contact_lines: list[str] = []
    for label, key in (("Website", "site_url"), ("Phone", "phone"),
                       ("Email", "email"), ("Service area", "service_area")):
        val = business.get(key) or ""
        if val:
            contact_lines.append(f"- {label}: {val}")
    if contact_lines:
        lines.extend(["", "## Contact", "", *contact_lines])

    return "\n".join(lines) + "\n"


def _article_lines(articles: list[dict[str, Any]]) -> list[str]:
    """One '- [title](url): summary' line per valid article (summary optional)."""
    entries: list[str] = []
    for article in articles:
        title = article.get("title")
        url = article.get("url")
        if not title or not url:
            continue
        summary = article.get("summary") or ""
        entries.append(f"- [{title}]({url}): {summary}" if summary else f"- [{title}]({url})")
    return entries


def with_preamble(preamble: str, articles: list[dict[str, Any]]) -> str:
    """Append the generated '## Articles' section to a hand-written preamble.

    The live site already carries a hand-authored llms.txt (stored as the preamble in
    PlatformConfig LLMS_TXT_PREAMBLE) — never regenerate or overwrite that prose; only
    the article index is machine-maintained. The preamble must not itself contain an
    '## Articles' section (it is stored separately from the generated output, so re-runs
    always start from the same preamble — no replace logic needed)."""
    base = preamble.rstrip("\n")
    entries = _article_lines(articles)
    if not entries:
        return base + "\n"
    return base + "\n\n## Articles\n\n" + "\n".join(entries) + "\n"


def article_entries(base_url: str, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Map DB-ish article rows ({title, slug, meta_description}) to manifest entries.

    URL shape matches core.search_indexing.article_url (top-level permalink, trailing
    slash). Rows missing slug or title are skipped; empty base_url returns []."""
    if not base_url:
        return []
    base = base_url.rstrip("/")
    result: list[dict[str, str]] = []
    for row in rows:
        slug = row.get("slug")
        title = row.get("title")
        if not slug or not title:
            continue
        result.append({
            "title": title,
            "url": f"{base}/{slug.strip('/')}/",
            "summary": row.get("meta_description") or "",
        })
    return result
