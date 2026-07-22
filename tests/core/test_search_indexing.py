"""Tests for core/search_indexing.py — pure logic, no I/O."""
from core.search_indexing import (
    MAX_URLS_PER_RUN,
    IndexingStatus,
    article_url,
    indexnow_payload,
    site_url,
    urls_for_articles,
)

# ── IndexingStatus ───────────────────────────────────────────────────────────

def test_status_fully_configured():
    st = IndexingStatus(enabled=True, indexnow_configured=True, google_configured=True)
    assert st.fully_configured is True
    assert st.any_configured is True
    assert st.active is True


def test_status_disabled_is_never_active_even_if_configured():
    st = IndexingStatus(enabled=False, indexnow_configured=True, google_configured=True)
    assert st.active is False


def test_status_enabled_but_unconfigured_is_not_active():
    st = IndexingStatus(enabled=True, indexnow_configured=False, google_configured=False)
    assert st.any_configured is False
    assert st.active is False


def test_status_partial_config_is_active_but_not_fully_configured():
    st = IndexingStatus(enabled=True, indexnow_configured=True, google_configured=False)
    assert st.active is True
    assert st.fully_configured is False


# ── URL builders ──────────────────────────────────────────────────────────────

def test_site_url_normalizes_trailing_slash():
    assert site_url("https://perkinsroofing.net") == "https://perkinsroofing.net/"
    assert site_url("https://perkinsroofing.net/") == "https://perkinsroofing.net/"


def test_article_url_strips_slashes_on_both_sides():
    assert article_url("https://perkinsroofing.net/", "/my-slug/") == "https://perkinsroofing.net/my-slug/"
    assert article_url("https://perkinsroofing.net", "my-slug") == "https://perkinsroofing.net/my-slug/"


# ── urls_for_articles ────────────────────────────────────────────────────────

def test_urls_for_articles_includes_site_root_first():
    urls = urls_for_articles("https://perkinsroofing.net", ["roof-repair-tips"])
    assert urls == [
        "https://perkinsroofing.net/",
        "https://perkinsroofing.net/roof-repair-tips/",
    ]


def test_urls_for_articles_empty_base_url_returns_empty():
    assert urls_for_articles("", ["some-slug"]) == []


def test_urls_for_articles_dedupes_and_preserves_order():
    urls = urls_for_articles("https://perkinsroofing.net", ["a", "b", "a"])
    assert urls == [
        "https://perkinsroofing.net/",
        "https://perkinsroofing.net/a/",
        "https://perkinsroofing.net/b/",
    ]


def test_urls_for_articles_skips_blank_slugs():
    urls = urls_for_articles("https://perkinsroofing.net", ["", "real-slug", None])
    assert urls == [
        "https://perkinsroofing.net/",
        "https://perkinsroofing.net/real-slug/",
    ]


def test_urls_for_articles_caps_at_max_urls_per_run():
    slugs = [f"post-{i}" for i in range(MAX_URLS_PER_RUN + 20)]
    urls = urls_for_articles("https://perkinsroofing.net", slugs)
    assert len(urls) == MAX_URLS_PER_RUN


def test_urls_for_articles_no_slugs_returns_just_site_root():
    assert urls_for_articles("https://perkinsroofing.net", []) == ["https://perkinsroofing.net/"]


# ── indexnow_payload ─────────────────────────────────────────────────────────

def test_indexnow_payload_shape():
    payload = indexnow_payload("perkinsroofing.net", "abc123", ["https://perkinsroofing.net/a/"])
    assert payload == {
        "host": "perkinsroofing.net",
        "key": "abc123",
        "keyLocation": "https://perkinsroofing.net/abc123.txt",
        "urlList": ["https://perkinsroofing.net/a/"],
    }
