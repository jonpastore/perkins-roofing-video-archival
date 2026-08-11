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
    structure_groups,
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

    def test_default_template_contains_payment_draw_table(self):
        ctx = _minimal_context(
            payment_draws=[
                {"sequence": 1, "label": "Acceptance / prior to permitting", "pct": "30%", "amount": "$5,520.00"},
                {
                    "sequence": 4,
                    "label": "Substantial completion (net balance)",
                    "pct": "Balance",
                    "amount": "$1,840.00",
                },
            ],
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "Payment Schedule" in html
        assert "Acceptance / prior to permitting" in html
        assert "Substantial completion (net balance)" in html

    def test_default_template_contains_lumber_schedule_exhibit(self):
        """The exhibit must state RATES, not promise a schedule it never shows.

        It shipped for weeks saying decking was "charged per published Perkins schedule" and
        fascia "billed per linear foot by actual size used" — no numbers anywhere. This is an
        exhibit to the contract, so a customer signing it was agreeing to prices they could not
        read. Tim's real schedule (~/perkins-corpus/pricing/Lumber Schedule.pdf) is a full rate
        card; these are his figures.
        """
        ctx = _minimal_context()
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "Lumber Schedule" in html
        assert "Roof deck" in html
        for rate in ("$120 per sheet", "$110 per sheet", "$145 per sheet",
                     "$8.25 per LF", "$0.75 per SF", "$110 per man-hour"):
            assert rate in html, f"lumber exhibit no longer states {rate!r}"
        # The 2-storey carpentry surcharge explicitly does NOT apply to roof decking.
        assert "roof decking wood excepted" in html

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


class TestSandboxedRender:
    """L2 (deepsec): html_body is tenant-editable — template-source SSTI must be
    blocked by Jinja2's sandbox, not just autoescape (which only covers ctx data)."""

    def test_ssti_attribute_access_is_blocked(self):
        import jinja2.exceptions
        import pytest as _pytest

        from core.proposal_render import ProposalRenderContext, render_proposal_html
        ctx = ProposalRenderContext(
            proposal_title="t", proposal_date="d", proposal_version=1,
            customer_name="c", customer_company=None, property_address="a",
            property_county=None, property_code_zone="z", quote_roof_type="r",
            quote_num_squares=1.0, quote_good_price="1", quote_better_price="2",
            quote_best_price="3", quote_line_items=[], deposit_amount="1",
            deposit_instructions="", tenant_name="t", tenant_license=None,
            accept_url="")
        with _pytest.raises(jinja2.exceptions.SecurityError):
            render_proposal_html(
                "{{ ''.__class__.__mro__[1].__subclasses__() }}", ctx)


# ---------------------------------------------------------------------------
# T&C AI-FAQ rendering
# ---------------------------------------------------------------------------

class TestTcAiFaqRendering:
    """Tests for tc_summary_bullets and tc_faq_items rendering in DEFAULT_TEMPLATE_HTML."""

    def _ctx(self, **overrides) -> ProposalRenderContext:
        base = _minimal_context()
        for k, v in overrides.items():
            object.__setattr__(base, k, v)
        return base

    def test_no_ai_blocks_when_bullets_none(self):
        ctx = self._ctx(tc_summary_bullets=None, tc_faq_items=None)
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert 'class="tc-ai-cover"' not in html
        assert 'class="tc-ai-faq"' not in html

    def test_no_ai_blocks_when_bullets_empty_list(self):
        ctx = self._ctx(tc_summary_bullets=[], tc_faq_items=None)
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert 'class="tc-ai-cover"' not in html

    def test_cover_letter_rendered_when_bullets_present(self):
        ctx = self._ctx(
            tc_summary_bullets=["Bullet one", "Bullet two"],
            tc_faq_items=None,
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert 'class="tc-ai-cover"' in html
        assert "FAQ" in html

    def test_bullets_appear_in_output(self):
        ctx = self._ctx(
            tc_summary_bullets=["Bullet one", "Bullet two"],
            tc_faq_items=None,
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "Bullet one" in html
        assert "Bullet two" in html

    def test_faq_block_rendered_when_items_present(self):
        ctx = self._ctx(
            tc_summary_bullets=None,
            tc_faq_items=[{"q": "What is the payment schedule?", "a": "30% upfront."}],
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert 'class="tc-ai-faq"' in html
        assert "What is the payment schedule?" in html
        assert "30% upfront." in html

    def test_both_blocks_rendered_when_both_set(self):
        ctx = self._ctx(
            tc_summary_bullets=["Bullet one"],
            tc_faq_items=[{"q": "Q?", "a": "A."}],
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert 'class="tc-ai-cover"' in html
        assert 'class="tc-ai-faq"' in html

    def test_xss_in_bullet_is_escaped(self):
        ctx = self._ctx(
            tc_summary_bullets=['<script>alert("xss")</script>'],
            tc_faq_items=None,
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_xss_in_faq_question_is_escaped(self):
        ctx = self._ctx(
            tc_summary_bullets=None,
            tc_faq_items=[{"q": '<script>evil()</script>', "a": "A."}],
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "<script>" not in html

    def test_xss_in_faq_answer_is_escaped(self):
        ctx = self._ctx(
            tc_summary_bullets=None,
            tc_faq_items=[{"q": "Q?", "a": '<img src=x onerror=alert(1)>'}],
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "<img" not in html

    def test_tc_text_replaces_placeholder_when_present(self):
        ctx = self._ctx(tc_text="Payment terms go here.")
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "Payment terms go here." in html
        assert "PLACEHOLDER" not in html

    def test_tc_review_prompts_render_from_context(self):
        ctx = self._ctx(
            tc_review_prompts=["Ask this contract question."],
            tc_ai_disclaimer="AI disclaimer text.",
            tc_cover_letter="Cover letter text.",
        )
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "Ask this contract question." in html
        assert "AI disclaimer text." in html
        assert "Cover letter text." in html

    def test_custom_template_can_access_nested_tc_namespace(self):
        ctx = self._ctx(
            tc_text="Saved terms",
            tc_review_prompts=["Prompt one"],
            tc_faq_items=[{"q": "Nested Q?", "a": "Nested A."}],
        )
        html = render_proposal_html("{{ tc.text }} / {{ tc.review_prompts[0] }} / {{ tc.faq_items[0].q }}", ctx)
        assert "Saved terms / Prompt one / Nested Q?" in html

    def test_default_template_renders_when_both_none(self):
        ctx = self._ctx(tc_summary_bullets=None, tc_faq_items=None)
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert len(html) > 100


class TestTcSectionToggles:
    """quote_snapshot include_terms / include_contract_faq drop their sections from the PDF."""

    def _ctx(self, **overrides) -> ProposalRenderContext:
        base = _minimal_context()
        object.__setattr__(base, "tc_text", "These are the terms.")
        object.__setattr__(base, "tc_summary_bullets", ["Bullet one"])
        object.__setattr__(base, "tc_faq_items", [{"q": "Q?", "a": "A."}])
        for k, v in overrides.items():
            object.__setattr__(base, k, v)
        return base

    def test_both_sections_render_by_default(self):
        """Default must stay ON — a proposal that silently drops its T&C is a contract defect."""
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, self._ctx())
        assert "These are the terms." in html
        assert 'class="tc-ai-cover"' in html
        assert 'class="tc-ai-faq"' in html

    def test_include_terms_false_drops_terms_and_summary(self):
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, self._ctx(include_terms=False))
        assert "These are the terms." not in html
        assert "Terms and conditions to be attached." not in html
        assert 'class="terms"' not in html
        assert 'class="tc-ai-cover"' not in html
        assert 'class="tc-ai-faq"' in html, "the FAQ has its own toggle"

    def test_include_contract_faq_false_drops_only_the_faq(self):
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, self._ctx(include_contract_faq=False))
        assert 'class="tc-ai-faq"' not in html
        assert "These are the terms." in html

    def test_custom_template_can_read_the_flags(self):
        ctx = self._ctx(include_terms=False, include_contract_faq=True)
        html = render_proposal_html("{{ tc.include_terms }}/{{ tc.include_contract_faq }}", ctx)
        assert "False/True" in html


def test_calc_lines_show_days_for_overhead_and_leak_no_internals():
    """The build-up must show Tim's DAY math and never print config keys at a customer.

    Overhead is the one line he insists is time-driven; collapsing it to a per-square figure hides
    the days that justify it. And the engine's raw formula strings carry internal annotations
    ("NOTE: ...", pending-Tim asides, config key names) that must not reach a proposal.
    """
    from core.proposal_render import calc_lines_from_estimate

    result = {
        "line_items_detail": [
            {"key": "base_cost_lm", "label": "Base Cost (L+M)", "amount": 27435.76, "per_sq": 783.88,
             "explain": {"formula": "per_sq x squares", "inputs": {"per_sq": 783.88, "squares": 35.0}}},
            {"key": "overhead", "label": "Overhead", "amount": 6875.0, "per_sq": 196.43,
             "explain": {"formula": "sum(days x daily_rate) per series, then / squares.",
                         "inputs": {"tile_days": 5.0, "tile_rate": 745.0,
                                    "demo_dry_in_flat_days": 3.0, "demo_dry_in_flat_rate": 1050.0}}},
            {"key": "pm_incentive", "label": "PM Incentive", "amount": 100.0,
             "explain": {"formula": "band lookup on squares. NOTE: Tim's sheet keys this on SIZE "
                                    "ONLY (<20 $50 / 20-50 $100), pending item #1 with Tim",
                         "inputs": {"squares": 35.0}}},
        ]
    }
    lines = calc_lines_from_estimate(result)

    assert "5 days tile x $745" in lines[1]["formula"]
    assert "3 days demo dry in flat x $1,050" in lines[1]["formula"]
    assert "196.43" not in lines[1]["formula"]          # days, not the collapsed per-square
    assert lines[0]["formula"] == "35 squares x $783.88"

    # no internal annotation, config key or pending-Tim aside survives into the document
    for ln in lines:
        assert "NOTE" not in ln["formula"]
        assert "pending" not in ln["formula"].lower()
        assert "_" not in ln["formula"]

    # running total is verifiable line by line
    assert lines[-1]["running_display"] == "$34,410.76"


# ---------------------------------------------------------------------------
# Customer vs internal build-up. Jon, 2026-07-25: "we can collapse the price with days in to price
# per sq. to show the customer. we don't want to show them the profit."
# ---------------------------------------------------------------------------

def _calc_result():
    """918 Mil Creek as the estimator produces it — the home in Tim's worked-proposals pack."""
    return {
        "num_squares": 35.0,
        "line_items_detail": [
            {"key": "base_cost_lm", "label": "Base Cost (L+M)", "amount": 26950.0,
             "explain": {"formula": "per_sq x squares", "inputs": {"per_sq": 770.0, "squares": 35.0}}},
            {"key": "overhead", "label": "Overhead", "amount": 6875.0,
             "explain": {"formula": "sum(days x daily_rate) per series",
                         "inputs": {"tile_days": 5.0, "tile_rate": 745.0,
                                    "demo_dry_in_flat_days": 3.0, "demo_dry_in_flat_rate": 1050.0}}},
            {"key": "profit", "label": "Profit", "amount": 5000.0,
             "explain": {"formula": "profit floor applied", "inputs": {"per_sq": 142.86, "squares": 35.0}}},
            {"key": "tile_demo", "label": "Tile Demo", "amount": 1050.0,
             "explain": {"formula": "per_sq x squares", "inputs": {"per_sq": 30.0, "squares": 35.0}}},
            {"key": "delivery_plywood_vents", "label": "Delivery / Plywood / Vents", "amount": 650.0,
             "explain": {"formula": "fixed"}},
            {"key": "new_bonus_values", "label": "Bonus Values", "amount": 1350.0,
             "explain": {"formula": "fixed"}},
            {"key": "permit_processing", "label": "Permit Processing", "amount": 500.0,
             "explain": {"formula": "fixed"}},
            {"key": "tile_dumpster", "label": "Tile Dumpsters", "amount": 600.0,
             "explain": {"formula": "fixed"}},
            {"key": "pm_incentive", "label": "PM Incentive", "amount": 100.0,
             "explain": {"formula": "band lookup on squares", "inputs": {"squares": 35.0}}},
        ],
    }


def _amount(line):
    return float(line["amount_display"].replace("$", "").replace(",", ""))


def test_internal_mode_still_shows_days_and_profit():
    from core.proposal_render import calc_lines_from_estimate
    lines = calc_lines_from_estimate(_calc_result(), audience="internal")
    keys = [ln["key"] for ln in lines]
    assert "profit" in keys
    assert "5 days tile x $745" in lines[1]["formula"]
    assert lines[-1]["running_display"] == "$43,075.00"


def test_customer_mode_hides_profit_but_still_sums_to_the_same_total():
    """The whole point: rows a customer can add up, landing on the price they were quoted."""
    from core.proposal_render import calc_lines_from_estimate
    result = _calc_result()
    internal = calc_lines_from_estimate(result, audience="internal")
    customer = calc_lines_from_estimate(result, audience="customer")

    assert customer[-1]["running_display"] == internal[-1]["running_display"] == "$43,075.00"
    assert sum(_amount(ln) for ln in customer) == pytest.approx(43075.00, abs=0.01)

    # no profit row, and nothing that names one
    assert not any(ln["key"] == "profit" for ln in customer)
    blob = " ".join(f"{ln['label']} {ln['formula']}" for ln in customer).lower()
    for word in ("profit", "margin", "markup"):
        assert word not in blob, f"{word!r} leaked into the customer build-up"

    # the folded line is a real per-square price, not "fixed amount"
    fold = customer[0]
    assert fold["label"] == "Labour, materials and overhead"
    assert fold["formula"] == "everything required to install this roof"
    # base + overhead + every back-end line (profit, PM incentive, bonus values)
    assert _amount(fold) == pytest.approx(26950 + 6875 + 5000 + 100 + 1350, abs=0.01)


def test_customer_mode_cannot_be_differenced_back_to_profit():
    """Hiding the row is not enough — brute-force every subset of what the customer can see.

    If any combination of the visible amounts equalled the profit figure, a customer with a
    calculator could recover the margin, and the section would be worse than not shipping it.
    Checks the profit value itself AND the total-minus-subset complement, which is the same
    attack from the other end.
    """
    from itertools import combinations

    from core.proposal_render import calc_lines_from_estimate
    result = _calc_result()
    profit = 5000.0
    total = 43075.0
    amounts = [_amount(ln) for ln in calc_lines_from_estimate(result, audience="customer")]

    reachable = set()
    for r in range(1, len(amounts) + 1):
        for combo in combinations(amounts, r):
            s = round(sum(combo), 2)
            reachable.add(s)
            reachable.add(round(total - s, 2))
    assert profit not in reachable, "profit is recoverable by differencing the customer rows"

    # sanity: the check is capable of failing — the internal rows DO expose it
    internal_amounts = [_amount(ln)
                        for ln in calc_lines_from_estimate(result, audience="internal")]
    assert profit in {round(a, 2) for a in internal_amounts}


def test_no_back_end_key_survives_customer_mode():
    """Tim, 2026-07-27: "the PM incentive is not something the customer ever needs to see…
    we usually don't want to show them any of the back-end stuff."

    Every back-end key must be gone as a row AND as a word — a folded amount is fine, a labelled
    row is not. Driven off _BACK_END_KEYS so adding one there without folding it fails here.
    """
    from core.proposal_render import _BACK_END_KEYS, calc_lines_from_estimate
    result = _calc_result()
    customer = calc_lines_from_estimate(result, audience="customer")

    keys = {ln["key"] for ln in customer}
    blob = " ".join(f"{ln['key']} {ln['label']} {ln['formula']}" for ln in customer).lower()
    for key in _BACK_END_KEYS:
        assert key not in keys, f"{key!r} still prints as its own row for a customer"
    for word in ("profit", "margin", "markup", "incentive", "bonus", "commission"):
        assert word not in blob, f"{word!r} leaked into the customer build-up"

    # sanity: the fixture actually carries these rows, so the assertions above can fail
    internal_keys = {ln["key"] for ln in calc_lines_from_estimate(result, audience="internal")}
    assert set(_BACK_END_KEYS) <= internal_keys
    # and folding them kept the arithmetic closed
    assert sum(_amount(ln) for ln in customer) == pytest.approx(43075.00, abs=0.01)


def test_unknown_audience_is_rejected():
    """A typo must not silently fall through to the internal view on a customer document."""
    from core.proposal_render import calc_lines_from_estimate
    with pytest.raises(ValueError, match="audience"):
        calc_lines_from_estimate(_calc_result(), audience="homeowner")


# ---------------------------------------------------------------------------
# Snapshot freezing — the rows a customer received must survive a later re-render
# ---------------------------------------------------------------------------

def _snap(**over):
    snap = {
        "include_calc_breakdown": True,
        "calc_audience": "customer",
        "estimate_result": _calc_result() | {"calculation_trace": [{"section": "profit_scale"}]},
    }
    snap.update(over)
    return snap


def test_freeze_stores_rows_and_keeps_the_raw_trace_out_of_the_database():
    """Ticking a checkbox must not route around the gate that keeps traces out of readable rows.

    api/routes/estimator._audit_payload strips explain + calculation_trace before an estimate is
    persisted, because `sales` can read those rows. A proposal snapshot has the same readership.
    """
    from api.routes.proposals import _freeze_calc_breakdown
    snap = _freeze_calc_breakdown(_snap())

    assert snap["calc_lines"], "rows must be frozen at create time, not rebuilt on render"
    assert snap["calc_audience"] == "customer"
    assert "calculation_trace" not in snap["estimate_result"]
    assert not any("explain" in li for li in snap["estimate_result"]["line_items_detail"])
    # and the frozen rows are the customer view, not the internal one
    assert not any(ln["key"] == "profit" for ln in snap["calc_lines"])


def test_freeze_is_a_no_op_when_the_box_is_unticked():
    from api.routes.proposals import _freeze_calc_breakdown
    snap = _freeze_calc_breakdown(_snap(include_calc_breakdown=False))
    assert "calc_lines" not in snap


def test_freeze_fails_closed_when_the_estimate_carries_no_trace():
    """debug is gated on estimating_manage. A sales quote has no `explain`, so every formula would
    read "fixed amount" — a build-up section that builds up nothing. Suppress it instead."""
    from api.routes.proposals import _freeze_calc_breakdown
    bare = {"num_squares": 35.0,
            "line_items_detail": [{"key": "base_cost_lm", "label": "Base", "amount": 100.0}]}
    snap = _freeze_calc_breakdown(_snap(estimate_result=bare))
    assert snap["include_calc_breakdown"] is False
    assert "calc_lines" not in snap


def test_freeze_rejects_an_unknown_audience():
    from fastapi import HTTPException

    from api.routes.proposals import _freeze_calc_breakdown
    with pytest.raises(HTTPException):
        _freeze_calc_breakdown(_snap(calc_audience="homeowner"))


def test_an_absent_audience_defaults_to_internal_and_that_default_shows_profit():
    """#447(2): the default path had no test, and it is where #433's class of bug reopens.

    `calc_audience` is optional; omitting it yields "internal", and internal INCLUDES the profit
    row. So a caller that simply forgets the field gets a snapshot carrying margin. That is the
    correct default — staff are the ones who tick this box — but it must be a decision somebody
    made on purpose, not an accident nobody has pinned.

    If the default ever flips, or internal quietly stops carrying profit, this fails and whoever
    changed it has to say so.
    """
    from api.routes.proposals import _freeze_calc_breakdown

    snap = _snap()
    del snap["calc_audience"]
    frozen = _freeze_calc_breakdown(snap)

    assert frozen["calc_audience"] == "internal", "omitting the field must not silently vary"
    assert any(ln["key"] == "profit" for ln in frozen["calc_lines"]), (
        "internal is the profit-bearing view; if this stops being true the customer/internal "
        "split has moved and the default needs re-deciding"
    )


def test_an_explicitly_null_audience_also_defaults_rather_than_erroring():
    """`snap.get(...) or "internal"` treats None and "" as absent — pin that, it is load-bearing."""
    from api.routes.proposals import _freeze_calc_breakdown

    for empty in (None, ""):
        frozen = _freeze_calc_breakdown(_snap(calc_audience=empty))
        assert frozen["calc_audience"] == "internal", empty


# ---------------------------------------------------------------------------
# Per-building addresses (#6) — Tim, 2026-08-02: "yes but they can share"
# ---------------------------------------------------------------------------

def test_structures_sharing_an_address_collapse_to_one_row():
    """Nine Evergrene buildings on one parkway must not print the same street nine times."""
    groups = structure_groups(
        [{"name": "Clubhouse", "squares": 206}, {"name": "Bus Stop", "squares": 3}],
        default_address="650 Evergrene Pkwy, Palm Beach Gardens FL",
    )
    assert len(groups) == 1
    assert groups[0]["names"] == ["Clubhouse", "Bus Stop"]
    assert groups[0]["address"] == "650 Evergrene Pkwy, Palm Beach Gardens FL"
    assert groups[0]["squares"] == 209


def test_a_structure_on_another_road_gets_its_own_row():
    """The case the column exists for: two Evergrene gates are on different roads."""
    groups = structure_groups(
        [
            {"name": "Clubhouse", "squares": 206},
            {"name": "North Gate", "squares": 4, "address": "1 Hood Rd"},
            {"name": "South Gate", "squares": 4, "address": "1 Hood Rd"},
        ],
        default_address="650 Evergrene Pkwy",
    )
    assert [(g["address"], g["names"]) for g in groups] == [
        ("650 Evergrene Pkwy", ["Clubhouse"]),
        ("1 Hood Rd", ["North Gate", "South Gate"]),
    ]
    # Insertion order, not alphabetical — the document reads in bid-capture order.
    assert groups[0]["names"] == ["Clubhouse"]


def test_structures_render_into_the_default_template():
    html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(
        structures=[{"address": "650 Evergrene Pkwy", "names": ["Clubhouse", "Bus Stop"],
                     "squares": 209.0}]))
    assert "Structures Covered" in html
    assert "Clubhouse, Bus Stop" in html
    assert "650 Evergrene Pkwy" in html


def test_a_single_roof_proposal_renders_no_structures_section():
    """Additive: an ordinary proposal is unchanged, section and all."""
    html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context())
    assert "Structures Covered" not in html
    assert "Scope of Work" in html


def test_a_property_with_no_street_prints_an_absent_address_not_a_blank_cell():
    """create_proposal_from_project accepts a property whose street is unset, so the fallback
    address can be "". A blank cell reads as a missing value; the em dash says nobody stated one."""
    groups = structure_groups([{"name": "Clubhouse", "squares": 30}], default_address="")
    assert groups[0]["address"] == ""
    html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(structures=groups))
    assert "Structures Covered" in html
    assert "—" in html.split("Structures Covered", 1)[1].split("Scope of Work", 1)[0]


# ---------------------------------------------------------------------------
# Per-job notes on the CUSTOMER document (#387)
# ---------------------------------------------------------------------------
# `quote_snapshot.notes` was read in exactly one place — _assemble_review_text, which builds the
# text for the pre-send AI review. So a note an estimator wrote was read by the reviewer and never
# printed on the thing the customer signs. None of the four document renderers touched it.

class TestJobNotes:
    def test_notes_render_on_the_document(self):
        html = render_proposal_html(
            DEFAULT_TEMPLATE_HTML,
            _minimal_context(notes="Gate code 4417. Homeowner clears the patio."))
        assert "Gate code 4417" in html
        assert "Notes for This Job" in html

    def test_no_empty_block_when_there_are_no_notes(self):
        """The heading must not print on the ~every proposal that carries no notes — an empty
        'Notes for This Job' section on a signed contract reads as something omitted."""
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context())
        assert "Notes for This Job" not in html

    def test_blank_and_whitespace_notes_do_not_render_the_block(self):
        for value in ("", None):
            html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(notes=value))
            assert "Notes for This Job" not in html, repr(value)

    def test_notes_are_html_escaped(self):
        """Operator-supplied text into HTML. The env is autoescape+sandboxed, and this pins it for
        THIS field rather than trusting the global setting stays on."""
        html = render_proposal_html(
            DEFAULT_TEMPLATE_HTML,
            _minimal_context(notes='<script>alert("xss")</script> & "quoted"'))
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_notes_default_to_absent_so_old_snapshots_are_unchanged(self):
        """Every proposal rendered before #387 has no `notes` key. The field must default to None
        and change nothing about those documents."""
        ctx = _minimal_context()
        assert ctx.notes is None
        before = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
        assert "Notes for This Job" not in before


# ---------------------------------------------------------------------------
# Scope of work on the CUSTOMER document
# ---------------------------------------------------------------------------
# The estimate form has sent `quote_snapshot.scope_of_work_text` since the field existed and NO
# renderer read it — no context field, no template block. The estimator wrote what the crew would
# do, and the customer received a document that priced the job without ever describing it.

class TestScopeOfWork:
    def test_scope_renders_on_the_document(self):
        html = render_proposal_html(
            DEFAULT_TEMPLATE_HTML,
            _minimal_context(scope_of_work="Tear off to deck.\nInstall underlayment.\nNew tile."))
        assert "Tear off to deck." in html
        assert "New tile." in html

    def test_scope_text_sits_under_the_scope_heading_not_in_a_second_section(self):
        """The document already has a Scope of Work heading over the priced cards. The written
        scope belongs under it — a second heading with the same name reads as a different
        section."""
        html = render_proposal_html(
            DEFAULT_TEMPLATE_HTML, _minimal_context(scope_of_work="Tear off to deck."))
        assert html.count(">Scope of Work</h2>") == 1
        assert html.index(">Scope of Work</h2>") < html.index("Tear off to deck.")

    def test_nothing_extra_renders_without_a_scope(self):
        for value in ("", None):
            html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(scope_of_work=value))
            assert html.count(">Scope of Work</h2>") == 1, repr(value)

    def test_scope_is_html_escaped(self):
        html = render_proposal_html(
            DEFAULT_TEMPLATE_HTML,
            _minimal_context(scope_of_work='<script>alert("xss")</script>'))
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_scope_defaults_to_absent_so_old_snapshots_are_unchanged(self):
        ctx = _minimal_context()
        assert ctx.scope_of_work is None
        assert render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx) == render_proposal_html(
            DEFAULT_TEMPLATE_HTML, _minimal_context())


# ---------------------------------------------------------------------------
# Metal-roof warranty at the property's own address
# ---------------------------------------------------------------------------
# Two "metal roofs" quoted on the same house can carry completely different coverage, and the
# difference is the brand's distance-to-salt-water rule rather than the metal. That is the one
# warranty fact a competing quote does not have, so it belongs on the document.

_MW = {
    "distance_ft": "77",
    "water_name": "ICWW ABOVE ROYAL PALM BRIDGE",
    "materials": [
        {"name": "Kynar/PVDF-painted steel (Galvalume / AZ50)", "state": "void",
         "manufacturers": [{"manufacturer": "Metal Alliance", "state": "void",
                            "phrase": "No warranty within 1,500 ft", "note": ""}]},
        {"name": "Aluminum (Kynar/PVDF or Tedlar coated)", "state": "cond",
         "manufacturers": [{"manufacturer": "Metal Alliance", "state": "cond",
                            "phrase": "Covered, with conditions inside 1,500 ft", "note": ""}]},
    ],
    "warranty_terms": [
        {"issuer": "Metal Alliance", "years": 25, "covers": "substrate corrosion", "condition": ""},
        {"issuer": "Metal Alliance", "years": 40, "covers": "Kynar 500 finish", "condition": ""},
    ],
}


class TestMetalWarrantySection:
    def test_it_renders_the_distance_and_every_manufacturer(self):
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(metal_warranty=_MW))
        assert "Metal Roof Warranty at This Address" in html
        assert "77 ft to salt water" in html
        assert "ICWW ABOVE ROYAL PALM BRIDGE" in html
        assert "No warranty within 1,500 ft" in html
        assert "Covered, with conditions inside 1,500 ft" in html

    def test_steel_and_aluminium_are_visibly_different(self):
        """If both read the same, the section has stopped saying the thing it exists to say."""
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(metal_warranty=_MW))
        assert 'class="void"' in html
        assert 'class="cond"' in html

    def test_absent_on_a_non_metal_proposal(self):
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context())
        assert "Metal Roof Warranty at This Address" not in html

    def test_defaults_to_absent_so_older_snapshots_are_unchanged(self):
        ctx = _minimal_context()
        assert ctx.metal_warranty is None
        assert render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx) == render_proposal_html(
            DEFAULT_TEMPLATE_HTML, _minimal_context())

    def test_the_warranty_terms_perkins_actually_sells_are_printed(self):
        """Quoted from Tim's own proposal (5/26/2026): 25 yr substrate corrosion, 40 yr Kynar.
        The selling point is that this address gets a real warranty from a named manufacturer,
        which the distance table alone does not say."""
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(metal_warranty=_MW))
        assert "25 years" in html and "substrate corrosion" in html
        assert "40 years" in html and "Kynar 500 finish" in html

    def test_manufacturer_text_is_html_escaped(self):
        bad = {**_MW, "water_name": '<script>alert("x")</script>'}
        html = render_proposal_html(DEFAULT_TEMPLATE_HTML, _minimal_context(metal_warranty=bad))
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html
