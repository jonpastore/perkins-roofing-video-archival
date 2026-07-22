from core.article_restandardize import (
    jsonld_types,
    strip_blog_links,
    strip_blog_links_deep,
    video_nodes,
)


def test_strip_blog_links_absolute_url():
    text = "See https://perkinsroofing.net/blog/roof-repair for details."
    out, count = strip_blog_links(text)
    assert out == "See https://perkinsroofing.net/roof-repair for details."
    assert count == 1


def test_strip_blog_links_relative_and_multiple():
    text = 'a href="/blog/foo" and again /blog/bar'
    out, count = strip_blog_links(text)
    assert out == 'a href="/foo" and again /bar'
    assert count == 2


def test_strip_blog_links_no_match():
    text = "https://perkinsroofing.net/roof-repair"
    out, count = strip_blog_links(text)
    assert out == text
    assert count == 0


def test_strip_blog_links_empty():
    assert strip_blog_links("") == ("", 0)
    assert strip_blog_links(None) == (None, 0)


def test_strip_blog_links_deep_nested():
    obj = {
        "@type": "Article",
        "url": "https://perkinsroofing.net/blog/roof-repair",
        "mentions": [
            {"url": "https://perkinsroofing.net/blog/metal-roofing"},
            {"url": "https://perkinsroofing.net/roof-inspection"},
        ],
        "count": 3,
    }
    out, total = strip_blog_links_deep(obj)
    assert out["url"] == "https://perkinsroofing.net/roof-repair"
    assert out["mentions"][0]["url"] == "https://perkinsroofing.net/metal-roofing"
    assert out["mentions"][1]["url"] == "https://perkinsroofing.net/roof-inspection"
    assert out["count"] == 3  # non-strings pass through unchanged
    assert total == 2


def test_video_nodes_filters_by_type():
    jsonld = [
        {"@type": "Article", "headline": "x"},
        {"@type": "VideoObject", "name": "v1"},
        {"@type": "Organization"},
        {"@type": "VideoObject", "name": "v2"},
    ]
    assert video_nodes(jsonld) == [
        {"@type": "VideoObject", "name": "v1"},
        {"@type": "VideoObject", "name": "v2"},
    ]


def test_video_nodes_empty_or_none():
    assert video_nodes(None) == []
    assert video_nodes([]) == []
    assert video_nodes([{"no_type": True}]) == []


def test_jsonld_types():
    jsonld = [{"@type": "FAQPage"}, {"@type": "VideoObject"}, "garbage-not-a-dict"]
    assert jsonld_types(jsonld) == ["FAQPage", "VideoObject"]
    assert jsonld_types(None) == []
