"""TDD tests for core/proposal_render.py — FAIL-FIRST, then implement.

Tests cover:
- Variable substitution from context dict
- Tier table rendering
- XSS/injection neutralization (autoescape ON — client data in HTML)
- Undefined variables render as empty string (silent Jinja2 Undefined)
- Default Perkins template renders without error
"""
from __future__ import annotations

import pytest

from core.proposal_render import (
    DEFAULT_TEMPLATE_HTML,
    ProposalRenderContext,
    render_proposal_html,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_context(**overrides) -> ProposalRenderContext:
    base = ProposalRenderContext(
        proposal_title="Roof Replacement — 123 Main St",
        proposal_date="July 8, 2026",
        proposal_version=1,
        customer_name="Tim Perkins",
        customer_company="Perkins Roofing",
        property_address="123 Main St, Miami FL 33101",
        property_county="Miami-Dade",
        property_code_zone="HVHZ",
        quote_roof_type="Dimensional Shingle",
        quote_num_squares=28.0,
        quote_good_price="$18,400.00",
        quote_better_price="$21,200.00",
        quote_best_price="$24,800.00",
        quote_line_items=[
            {"label": "Shingles", "qty": 28, "unit": "sq", "unit_price": 350.0, "total": 9800.0},
        ],
        deposit_amount="$9,200.00",
        deposit_instructions="Check payable to Perkins Roofing",
        tenant_name="Perkins Roofing",
        tenant_license="CCC1234567",
        accept_url="https://app.perkinsroofing.net/p/abc123",
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------

class TestVariableSubstitution:
    def test_customer_name_substituted(self):
        template = "<p>Dear {{ customer.name }}</p>"
        ctx = _minimal_context(customer_name="Tim Perkins")
        html = render_proposal_html(template, ctx)
        assert "Tim Perkins" in html

    def test_proposal_title_substituted(self):
        template = "<h1>{{ proposal.title }}</h1>"
        ctx = _minimal_context(proposal_title="Roof Job 123")
        html = render_proposal_html(template, ctx)
        assert "Roof Job 123" in html

    def test_accept_url_substituted(self):
        template = '<a href="{{ accept_url }}">Accept</a>'
        ctx = _minimal_context(accept_url="https://example.com/p/tok123")
        html = render_proposal_html(template, ctx)
        assert "https://example.com/p/tok123" in html

    def test_tenant_license_substituted(self):
        template = "License: {{ tenant.license }}"
        ctx = _minimal_context(tenant_license="CCC9999999")
        html = render_proposal_html(template, ctx)
        assert "CCC9999999" in html

    def test_deposit_amount_substituted(self):
        template = "Deposit: {{ deposit.amount }}"
        ctx = _minimal_context(deposit_amount="$5,000.00")
        html = render_proposal_html(template, ctx)
        assert "$5,000.00" in html

    def test_quote_good_price_substituted(self):
        template = "Good: {{ quote.good_price }}"
        ctx = _minimal_context(quote_good_price="$18,400.00")
        html = render_proposal_html(template, ctx)
        assert "$18,400.00" in html

    def test_all_tier_prices_substituted(self):
        template = "{{ quote.good_price }} / {{ quote.better_price }} / {{ quote.best_price }}"
        ctx = _minimal_context(
            quote_good_price="$18,400.00",
            quote_better_price="$21,200.00",
            quote_best_price="$24,800.00",
        )
        html = render_proposal_html(template, ctx)
        assert "$18,400.00" in html
        assert "$21,200.00" in html
        assert "$24,800.00" in html

    def test_property_address_substituted(self):
        template = "Property: {{ property.address }}"
        ctx = _minimal_context(property_address="456 Oak Ave, Boca Raton FL 33431")
        html = render_proposal_html(template, ctx)
        assert "456 Oak Ave, Boca Raton FL 33431" in html

    def test_property_county_substituted(self):
        template = "County: {{ property.county }}"
        ctx = _minimal_context(property_county="Broward")
        html = render_proposal_html(template, ctx)
        assert "Broward" in html

    def test_property_code_zone_substituted(self):
        template = "Zone: {{ property.code_zone }}"
        ctx = _minimal_context(property_code_zone="FBC")
        html = render_proposal_html(template, ctx)
        assert "FBC" in html

    def test_version_number_substituted(self):
        template = "Version: {{ proposal.version }}"
        ctx = _minimal_context(proposal_version=3)
        html = render_proposal_html(template, ctx)
        assert "3" in html


# ---------------------------------------------------------------------------
# Undefined variables → empty string (silent)
# ---------------------------------------------------------------------------

class TestUndefinedVariables:
    def test_undefined_variable_renders_empty(self):
        template = "Hello {{ totally_undefined_var }}!"
        ctx = _minimal_context()
        html = render_proposal_html(template, ctx)
        assert "Hello !" in html

    def test_undefined_nested_variable_renders_empty(self):
        template = "{{ foo.bar.baz }}"
        ctx = _minimal_context()
        html = render_proposal_html(template, ctx)
        assert html.strip() == ""


# ---------------------------------------------------------------------------
# XSS / injection neutralization (autoescape MUST be ON)
# ---------------------------------------------------------------------------

class TestXSSNeutralization:
    def test_script_injection_in_customer_name_escaped(self):
        """Client-supplied customer name with <script> must be HTML-escaped."""
        template = "<p>{{ customer.name }}</p>"
        ctx = _minimal_context(customer_name='<script>alert("xss")</script>')
        html = render_proposal_html(template, ctx)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_script_injection_in_proposal_title_escaped(self):
        template = "<h1>{{ proposal.title }}</h1>"
        ctx = _minimal_context(proposal_title='<img src=x onerror=alert(1)>')
        html = render_proposal_html(template, ctx)
        assert "<img" not in html
        assert "&lt;img" in html

    def test_attribute_injection_in_accept_url_escaped(self):
        """URL with embedded quote chars must not break out of href attribute."""
        template = '<a href="{{ accept_url }}">Accept</a>'
        ctx = _minimal_context(accept_url='javascript:alert(1)" onclick="bad')
        html = render_proposal_html(template, ctx)
        # The raw quote char must not appear unescaped in the output
        assert 'onclick="bad"' not in html

    def test_html_in_company_name_escaped(self):
        template = "{{ customer.company }}"
        ctx = _minimal_context(customer_company="<b>Evil Corp</b>")
        html = render_proposal_html(template, ctx)
        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    def test_html_in_deposit_instructions_escaped(self):
        template = "{{ deposit.instructions }}"
        ctx = _minimal_context(deposit_instructions='<script>steal()</script>')
        html = render_proposal_html(template, ctx)
        assert "<script>" not in html

    def test_html_in_tenant_name_escaped(self):
        template = "{{ tenant.name }}"
        ctx = _minimal_context(tenant_name='<b>Inject</b>')
        html = render_proposal_html(template, ctx)
        assert "<b>" not in html


# ---------------------------------------------------------------------------
# Line items table rendering
# ---------------------------------------------------------------------------

class TestLineItemsTable:
    def test_line_items_rendered_in_loop(self):
        template = (
            "{% for item in quote.line_items %}"
            "{{ item.label }}|{{ item.total }}"
            "{% endfor %}"
        )
        ctx = _minimal_context(quote_line_items=[
            {"label": "Shingles", "qty": 28, "unit": "sq", "unit_price": 350.0, "total": 9800.0},
            {"label": "Underlayment", "qty": 28, "unit": "sq", "unit_price": 50.0, "total": 1400.0},
        ])
        html = render_proposal_html(template, ctx)
        assert "Shingles" in html
        assert "Underlayment" in html
        assert "9800" in html

    def test_line_items_labels_escaped(self):
        """XSS in line item labels must be escaped."""
        template = (
            "{% for item in quote.line_items %}"
            "{{ item.label }}"
            "{% endfor %}"
        )
        ctx = _minimal_context(quote_line_items=[
            {"label": '<script>alert(1)</script>', "qty": 1, "unit": "ea", "unit_price": 0.0, "total": 0.0},
        ])
        html = render_proposal_html(template, ctx)
        assert "<script>" not in html

    def test_empty_line_items_renders_without_error(self):
        template = "{% for item in quote.line_items %}{{ item.label }}{% endfor %}"
        ctx = _minimal_context(quote_line_items=[])
        html = render_proposal_html(template, ctx)
        assert html == ""


# ---------------------------------------------------------------------------
# Default Perkins template smoke test
# ---------------------------------------------------------------------------

class TestSilentUndefined:
    """Direct tests for _SilentUndefined internal class to reach 100% coverage."""

    def test_silent_undefined_str_is_empty(self):
        from core.proposal_render import _SilentUndefined
        u = _SilentUndefined()
        assert str(u) == ""

    def test_silent_undefined_repr_is_empty(self):
        from core.proposal_render import _SilentUndefined
        u = _SilentUndefined()
        assert repr(u) == ""

    def test_silent_undefined_iter_is_empty(self):
        from core.proposal_render import _SilentUndefined
        u = _SilentUndefined()
        assert list(u) == []

    def test_silent_undefined_bool_is_false(self):
        from core.proposal_render import _SilentUndefined
        u = _SilentUndefined()
        assert bool(u) is False

    def test_silent_undefined_html_is_empty_markup(self):
        from markupsafe import Markup
        from core.proposal_render import _SilentUndefined
        u = _SilentUndefined()
        result = u.__html__()
        assert result == Markup("")


class TestDefaultTemplate:
    def test_default_template_renders_without_error(self):
        ctx = _minimal_context()
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert len(html) > 100

    def test_default_template_contains_customer_name(self):
        ctx = _minimal_context(customer_name="John Smith")
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "John Smith" in html

    def test_default_template_contains_accept_url(self):
        ctx = _minimal_context(accept_url="https://app.perkinsroofing.net/p/TESTTOKEN")
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "TESTTOKEN" in html

    def test_default_template_contains_tier_prices(self):
        ctx = _minimal_context(
            quote_good_price="$18,400.00",
            quote_better_price="$21,200.00",
            quote_best_price="$24,800.00",
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "$18,400.00" in html
        assert "$21,200.00" in html
        assert "$24,800.00" in html

    def test_default_template_is_valid_html_fragment(self):
        ctx = _minimal_context()
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        # Must contain an HTML structural element
        assert "<html" in html.lower() or "<div" in html.lower() or "<p" in html.lower() or "<h" in html.lower()

    def test_default_template_no_unrendered_placeholders(self):
        """After render with full context, no {{ ... }} placeholders remain."""
        ctx = _minimal_context()
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "{{" not in html
        assert "}}" not in html
