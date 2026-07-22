"""Tests for core.llms_txt."""

from core.llms_txt import article_entries, build_llms_txt


def test_full_output_with_all_fields():
    business = {
        "name": "Test Roof",
        "description": "Desc",
        "about": "About text",
        "site_url": "https://ex.com",
        "phone": "123",
        "email": "a@b.c",
        "service_area": "Area",
    }
    articles = [{"title": "T", "url": "https://ex.com/a", "summary": "S"}]
    out = build_llms_txt(business, articles)
    assert out == (
        "# Test Roof\n\n> Desc\n\n## About\n\nAbout text\n\n## Articles\n\n"
        "- [T](https://ex.com/a): S\n\n## Contact\n\n- Website: https://ex.com\n"
        "- Phone: 123\n- Email: a@b.c\n- Service area: Area\n"
    )


def test_missing_optional_business_fields_omitted():
    out = build_llms_txt({"name": "N"}, [])
    assert out == "# N\n"


def test_default_name():
    assert build_llms_txt({}, []).startswith("# Perkins Roofing\n")


def test_article_without_summary_no_colon_suffix():
    out = build_llms_txt({}, [{"title": "T", "url": "https://ex.com/a"}])
    assert "- [T](https://ex.com/a)\n" in out
    assert "): " not in out


def test_article_missing_url_or_title_skipped():
    out = build_llms_txt({}, [{"title": "T"}, {"url": "u"}])
    assert "## Articles" not in out  # no valid entries -> section omitted


def test_article_entries_url_building():
    rows = [{"title": "T", "slug": "/s/", "meta_description": "M"}]
    assert article_entries("https://ex.com/", rows) == [
        {"title": "T", "url": "https://ex.com/s/", "summary": "M"}
    ]


def test_article_entries_skips_and_empty_base():
    rows = [{"title": "T", "slug": "s"}, {"title": "no-slug"}, {"slug": "no-title"}]
    assert article_entries("", rows) == []
    got = article_entries("https://ex.com", rows)
    assert got == [{"title": "T", "url": "https://ex.com/s/", "summary": ""}]


def test_deterministic_ordering():
    out = build_llms_txt({}, [{"title": "B", "url": "u2"}, {"title": "A", "url": "u1"}])
    assert out.index("- [B](u2)") < out.index("- [A](u1)")


def test_single_trailing_newline():
    for articles in ([], [{"title": "T", "url": "u"}]):
        out = build_llms_txt({}, articles)
        assert out.endswith("\n") and not out.endswith("\n\n")


def test_with_preamble_appends_articles_section():
    from core.llms_txt import with_preamble

    pre = "# Perkins Roofing\n\nHand-written prose.\n"
    out = with_preamble(pre, [{"title": "T", "url": "u", "summary": "S"}])
    assert out == "# Perkins Roofing\n\nHand-written prose.\n\n## Articles\n\n- [T](u): S\n"


def test_with_preamble_no_articles_returns_normalized_preamble():
    from core.llms_txt import with_preamble

    assert with_preamble("pre\n\n\n", []) == "pre\n"
    assert with_preamble("pre", [{"title": "no-url"}]) == "pre\n"
