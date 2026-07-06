"""Tests for article HTML sanitizer, residual-markdown detector, placeholder detector,
and JSON-LD completeness helpers in jobs/article_job.py."""

from jobs.article_job import (
    has_placeholder,
    has_residual_markdown,
    sanitize_article_html,
)
from core.jsonld import build_breadcrumb_list


# ---------------------------------------------------------------------------
# has_placeholder
# ---------------------------------------------------------------------------

class TestHasPlaceholder:
    def test_todo_detected(self):
        assert has_placeholder("Some text TODO fill this in.")

    def test_todo_case_insensitive(self):
        assert has_placeholder("todo: add content here")

    def test_lorem_detected(self):
        assert has_placeholder("Lorem ipsum dolor sit amet.")

    def test_insert_bracket_detected(self):
        assert has_placeholder("Contact [insert phone number] for more info.")

    def test_add_bracket_detected(self):
        assert has_placeholder("See [add image here] for details.")

    def test_your_bracket_detected(self):
        assert has_placeholder("Call [your name] today.")

    def test_keyword_bracket_detected(self):
        assert has_placeholder("Learn about [keyword] in South Florida.")

    def test_handlebars_detected(self):
        assert has_placeholder("Welcome {{user_name}} to the platform.")

    def test_xxxx_detected(self):
        assert has_placeholder("Call us at XXXX for a free estimate.")

    def test_generic_placeholder_bracket(self):
        assert has_placeholder("See [CONTENT HERE] for more.")

    def test_clean_content_passes(self):
        assert not has_placeholder(
            "<h2>Roof Repair in Miami</h2>"
            "<p>Perkins Roofing provides expert roof repair services across South Florida.</p>"
        )

    def test_youtube_link_not_flagged(self):
        assert not has_placeholder(
            '<a href="https://youtu.be/abc?t=5">Watch our video</a>'
        )

    def test_empty_string_passes(self):
        assert not has_placeholder("")

    def test_none_passes(self):
        assert not has_placeholder(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# has_residual_markdown
# ---------------------------------------------------------------------------

class TestHasResidualMarkdown:
    def test_heading_detected(self):
        assert has_residual_markdown("## Section Heading\nsome content")

    def test_bold_double_asterisk_detected(self):
        assert has_residual_markdown("This is **important** text.")

    def test_bold_double_underscore_detected(self):
        assert has_residual_markdown("This is __important__ text.")

    def test_italic_asterisk_detected(self):
        assert has_residual_markdown("This is *italic* text.")

    def test_strikethrough_detected(self):
        assert has_residual_markdown("This is ~~deleted~~ text.")

    def test_markdown_link_detected(self):
        assert has_residual_markdown("See [our guide](/blog/guide) for more.")

    def test_bullet_detected(self):
        assert has_residual_markdown("- Item one\n- Item two")

    def test_pipe_table_detected(self):
        assert has_residual_markdown("| Col A | Col B |\n|---|---|\n| 1 | 2 |")

    def test_clean_html_passes(self):
        assert not has_residual_markdown(
            "<h2>Section</h2><p>Content here.</p>"
            "<ul><li>Item one</li></ul>"
            '<a href="https://youtu.be/x">video</a>'
        )

    def test_empty_passes(self):
        assert not has_residual_markdown("")


# ---------------------------------------------------------------------------
# sanitize_article_html — markdown completeness
# ---------------------------------------------------------------------------

class TestSanitizeArticleHtml:
    def test_converts_h2_heading(self):
        result = sanitize_article_html("## My Section\nContent here.")
        assert "<h2>My Section</h2>" in result
        assert "##" not in result

    def test_converts_h3_heading(self):
        result = sanitize_article_html("### Sub Section\nContent.")
        assert "<h3>Sub Section</h3>" in result

    def test_converts_bold(self):
        result = sanitize_article_html("This is **bold text** here.")
        assert "<strong>bold text</strong>" in result
        assert "**" not in result

    def test_converts_italic(self):
        result = sanitize_article_html("This is *italic* text.")
        assert "<em>italic</em>" in result
        assert result.count("*") == 0 or "<em>" in result

    def test_converts_link(self):
        result = sanitize_article_html("[Watch video](https://youtu.be/abc)")
        assert '<a href="https://youtu.be/abc">Watch video</a>' in result

    def test_converts_bullets(self):
        result = sanitize_article_html("- First item\n- Second item")
        assert "<ul>" in result
        assert "<li>First item</li>" in result
        assert "<li>Second item</li>" in result

    def test_converts_pipe_table(self):
        md = "| Name | Cost |\n|---|---|\n| Repair | $200 |"
        result = sanitize_article_html(md)
        assert "<table>" in result
        assert "<th>Name</th>" in result
        assert "<td>Repair</td>" in result

    def test_converts_admonition(self):
        md = "> [!TIP]\n> Check your roof annually."
        result = sanitize_article_html(md)
        assert "<aside" in result
        assert "Check your roof annually." in result

    def test_no_residual_after_sanitize(self):
        md = (
            "## Section\n"
            "This is **bold** and *italic* text.\n"
            "- Bullet one\n- Bullet two\n"
            "[Link](https://example.com/page)\n"
            "| A | B |\n|---|---|\n| 1 | 2 |"
        )
        result = sanitize_article_html(md)
        assert not has_residual_markdown(result), f"Residual markdown in: {result!r}"

    def test_html_passthrough(self):
        html = "<h2>Already HTML</h2><p>Content here.</p>"
        result = sanitize_article_html(html)
        assert result == html


# ---------------------------------------------------------------------------
# build_breadcrumb_list
# ---------------------------------------------------------------------------

class TestBuildBreadcrumbList:
    def test_schema_type(self):
        result = build_breadcrumb_list([
            {"name": "Home", "url": "https://example.com/"},
        ])
        assert result["@type"] == "BreadcrumbList"
        assert result["@context"] == "https://schema.org"

    def test_positions_are_1_indexed(self):
        result = build_breadcrumb_list([
            {"name": "Home", "url": "https://example.com/"},
            {"name": "Blog", "url": "https://example.com/blog/"},
            {"name": "Article", "url": "https://example.com/blog/article"},
        ])
        items = result["itemListElement"]
        assert len(items) == 3
        assert items[0]["position"] == 1
        assert items[1]["position"] == 2
        assert items[2]["position"] == 3

    def test_item_fields(self):
        result = build_breadcrumb_list([
            {"name": "Home", "url": "https://example.com/"},
        ])
        item = result["itemListElement"][0]
        assert item["@type"] == "ListItem"
        assert item["name"] == "Home"
        assert item["item"] == "https://example.com/"

    def test_empty_list(self):
        result = build_breadcrumb_list([])
        assert result["itemListElement"] == []
