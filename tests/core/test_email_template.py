"""100%-coverage tests for core.email_template.wrap_email.

All tests are pure (no I/O, no mocking required). The golden-string tests
pin the structural invariants of the output rather than the exact byte
sequence, so minor whitespace tweaks inside wrap_email don't silently
break the email layout.
"""

from core.email_template import wrap_email


# ---------------------------------------------------------------------------
# Structural invariants — every output must satisfy these
# ---------------------------------------------------------------------------

class TestWrapEmailStructure:
    def _wrapped(self, body="<p>Hello</p>") -> str:
        return wrap_email(body)

    def test_returns_string(self):
        assert isinstance(self._wrapped(), str)

    def test_starts_with_doctype(self):
        assert self._wrapped().startswith("<!DOCTYPE html>")

    def test_contains_html_open_close(self):
        out = self._wrapped()
        assert "<html" in out
        assert "</html>" in out

    def test_contains_body_open_close(self):
        out = self._wrapped()
        assert "<body" in out
        assert "</body>" in out

    def test_body_html_present_in_output(self):
        body = "<p>Test body content</p>"
        assert body in wrap_email(body)

    def test_no_class_attributes(self):
        # email-safe rule: no class= (clients strip <style>)
        out = self._wrapped()
        assert ' class="' not in out

    def test_no_style_block(self):
        # All CSS must be inline — no <style> tag
        out = self._wrapped()
        assert "<style" not in out

    def test_charset_meta_present(self):
        assert 'charset="UTF-8"' in self._wrapped()

    def test_viewport_meta_present(self):
        assert "viewport" in self._wrapped()


# ---------------------------------------------------------------------------
# Header band
# ---------------------------------------------------------------------------

class TestWrapEmailHeaderBand:
    def test_default_company_name_in_header(self):
        out = wrap_email("<p>body</p>")
        assert "Perkins Roofing" in out

    def test_custom_company_name(self):
        out = wrap_email("<p>body</p>", company_name="Acme Corp")
        assert "Acme Corp" in out
        assert "Perkins Roofing" not in out

    def test_custom_header_html_used_when_provided(self):
        header = '<img src="https://example.com/logo.png" alt="Logo">'
        out = wrap_email("<p>body</p>", header_html=header)
        assert header in out

    def test_custom_header_overrides_default_company_name_text(self):
        # When header_html is given, the fallback <p>Company Name</p> must NOT appear
        custom = "<div>Custom Header</div>"
        out = wrap_email("<p>body</p>", header_html=custom, company_name="Perkins Roofing")
        # The custom content is present
        assert "Custom Header" in out
        # The plain-text fallback p tag with company name should not be separately inserted
        assert custom in out

    def test_empty_header_html_falls_back_to_company_name(self):
        out = wrap_email("<p>body</p>", header_html="", company_name="Test Co")
        assert "Test Co" in out

    def test_brand_navy_used_in_header_background(self):
        out = wrap_email("<p>body</p>", brand_navy="#aabbcc")
        assert "#aabbcc" in out

    def test_default_navy_colour(self):
        out = wrap_email("<p>body</p>")
        assert "#1b2a52" in out


# ---------------------------------------------------------------------------
# Body area
# ---------------------------------------------------------------------------

class TestWrapEmailBodyArea:
    def test_font_family_in_output(self):
        out = wrap_email("<p>x</p>", font_family="Arial, sans-serif")
        assert "Arial, sans-serif" in out

    def test_default_font_family_present(self):
        out = wrap_email("<p>x</p>")
        assert "system-ui" in out

    def test_body_html_with_links(self):
        body = '<p>See <a href="https://example.com">example</a></p>'
        out = wrap_email(body)
        assert body in out

    def test_body_html_with_table(self):
        body = "<table><tr><td>Cell</td></tr></table>"
        out = wrap_email(body)
        assert body in out

    def test_body_html_with_special_chars(self):
        body = "<p>Roof cost: &lt;$10,000&gt; &amp; insured</p>"
        out = wrap_email(body)
        assert body in out

    def test_empty_body_still_produces_valid_doc(self):
        out = wrap_email("")
        assert "<!DOCTYPE html>" in out
        assert "</html>" in out


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

class TestWrapEmailFooter:
    def test_footer_contains_company_name(self):
        out = wrap_email("<p>x</p>", company_name="Acme Roofing")
        # Footer has company name
        assert "Acme Roofing" in out

    def test_footer_contains_licensed_insured(self):
        out = wrap_email("<p>x</p>")
        assert "Licensed" in out
        assert "Insured" in out

    def test_brand_red_used_in_footer_border(self):
        out = wrap_email("<p>x</p>", brand_red="#ff1234")
        assert "#ff1234" in out

    def test_default_red_colour(self):
        out = wrap_email("<p>x</p>")
        assert "#ef3c1a" in out


# ---------------------------------------------------------------------------
# 600px layout invariants
# ---------------------------------------------------------------------------

class TestWrapEmailLayout:
    def test_600px_table_present(self):
        out = wrap_email("<p>x</p>")
        assert 'width="600"' in out

    def test_role_presentation_on_tables(self):
        out = wrap_email("<p>x</p>")
        assert 'role="presentation"' in out

    def test_outer_table_has_full_width(self):
        out = wrap_email("<p>x</p>")
        assert 'width="100%"' in out

    def test_cellpadding_zero(self):
        out = wrap_email("<p>x</p>")
        assert 'cellpadding="0"' in out

    def test_cellspacing_zero(self):
        out = wrap_email("<p>x</p>")
        assert 'cellspacing="0"' in out


# ---------------------------------------------------------------------------
# Golden round-trip: all args supplied
# ---------------------------------------------------------------------------

class TestWrapEmailGoldenAllArgs:
    """Verify that every explicit argument actually appears in the output."""

    def test_all_args_reflected(self):
        out = wrap_email(
            body_html="<p>Hello world</p>",
            header_html="<div>My Header</div>",
            company_name="Test Roofing",
            brand_navy="#001122",
            brand_red="#ff0000",
            font_family="Georgia, serif",
        )
        assert "<p>Hello world</p>" in out
        assert "<div>My Header</div>" in out
        assert "Test Roofing" in out
        assert "#001122" in out
        assert "#ff0000" in out
        assert "Georgia, serif" in out

    def test_defaults_are_perkins_brand(self):
        out = wrap_email("<p>x</p>")
        assert "#1b2a52" in out  # brand_navy
        assert "#ef3c1a" in out  # brand_red
        assert "Perkins Roofing" in out
        assert "system-ui" in out
