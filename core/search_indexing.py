"""Search-engine indexing — pure decision/URL/payload logic (no I/O).

Two providers, one job:
  (a) IndexNow — a single POST reaches Bing, Yandex, Seznam, Naver (NOT Google).
      Needs env INDEXNOW_KEY (any random 8-128 char alnum string) AND that exact
      key hosted as a static file at https://{host}/{key}.txt (WordPress must
      serve this — see adapters/search_indexing.py module docstring).
  (b) Google Indexing API — one URL_UPDATED notification per URL. Needs env
      GOOGLE_INDEXING_CREDENTIALS (a service-account JSON key, inline or a file
      path) for an account that Search Console has added as a site OWNER, with
      the Indexing API enabled on the GCP project.

The admin on/off toggle is SEARCH_INDEXING_ENABLED (platform_config override,
else env, default "false" (OFF until explicitly enabled) — see
adapters.search_indexing._enabled). I/O for both
providers lives in adapters/search_indexing.py; this module only builds the
inputs and decides readiness state (consumed by core/production_gates.py).
"""
from __future__ import annotations

from dataclasses import dataclass

# Google Indexing API's published quota is 200 publish calls/day per project.
# Bounding every run well under that keeps the daily catch-up + on-publish
# submissions from ever tripping the quota even on a busy publishing day.
MAX_URLS_PER_RUN = 100


@dataclass(frozen=True)
class IndexingStatus:
    enabled: bool
    indexnow_configured: bool
    google_configured: bool

    @property
    def fully_configured(self) -> bool:
        return self.indexnow_configured and self.google_configured

    @property
    def any_configured(self) -> bool:
        return self.indexnow_configured or self.google_configured

    @property
    def active(self) -> bool:
        """True only when the toggle is on AND at least one provider will fire."""
        return self.enabled and self.any_configured


def site_url(base_url: str) -> str:
    """The site root URL, normalized to a single trailing slash."""
    return base_url.rstrip("/") + "/"


def article_url(base_url: str, slug: str) -> str:
    """An article's public URL — WordPress permalinks are top-level (no /blog/
    prefix; see adapters.wordpress.publish, which uses the article's own slug)."""
    return f"{base_url.rstrip('/')}/{slug.strip('/')}/"


def urls_for_articles(base_url: str, slugs: list[str]) -> list[str]:
    """Site root + one URL per article slug, de-duplicated, order preserved,
    capped at MAX_URLS_PER_RUN (rate-limit awareness — see module docstring).
    Returns [] when base_url is unset (WP_URL not configured — nothing to submit)."""
    if not base_url:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for u in [site_url(base_url), *(article_url(base_url, s) for s in slugs if s)]:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:MAX_URLS_PER_RUN]


def indexnow_payload(host: str, key: str, urls: list[str]) -> dict:
    """The IndexNow API request body — https://www.indexnow.org/documentation."""
    return {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": urls,
    }
