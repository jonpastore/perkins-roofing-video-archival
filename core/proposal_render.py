"""Proposal HTML template renderer (core — 100% coverable, no I/O).

Renders a Jinja2 HTML template against a ProposalRenderContext.
Autoescape is ALWAYS ON — proposals embed client-supplied data (names,
addresses, company names) directly into HTML that becomes a PDF. A single
unescaped XSS payload could corrupt the PDF or, if the accept page re-renders
the same data, execute in a client browser.

Public API:
    render_proposal_html(template_html: str, ctx: ProposalRenderContext) -> str

The default Perkins template is available as DEFAULT_TEMPLATE_HTML.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import jinja2
from markupsafe import Markup

# ---------------------------------------------------------------------------
# Context dataclass — maps to the TRD §3.2 variable contract
# ---------------------------------------------------------------------------

@dataclass
class ProposalRenderContext:
    """All variables available to a proposal template.

    Field names map to the Jinja2 namespace keys listed in TRD §3.2.
    """
    proposal_title: str
    proposal_date: str
    proposal_version: int
    customer_name: str
    customer_company: str | None
    property_address: str
    property_county: str | None
    property_code_zone: str
    quote_roof_type: str
    quote_num_squares: float
    quote_good_price: str
    quote_better_price: str
    quote_best_price: str
    quote_line_items: list[dict[str, Any]]
    deposit_amount: str
    deposit_instructions: str
    tenant_name: str
    tenant_license: str | None
    accept_url: str
    payment_draws: list[dict[str, Any]] | None = field(default=None)
    tc_summary_bullets: list[str] | None = field(default=None)
    tc_faq_items: list[dict] | None = field(default=None)
    tc_text: str | None = field(default=None)
    tc_review_prompts: list[str] | None = field(default=None)
    tc_ai_disclaimer: str | None = field(default=None)
    tc_cover_letter: str | None = field(default=None)
    # Section toggles (quote_snapshot.include_terms / include_contract_faq). Default True —
    # every proposal rendered before the toggles existed included both, and a proposal that
    # silently drops its T&C is a contract defect, not a formatting choice.
    include_terms: bool = field(default=True)
    include_contract_faq: bool = field(default=True)
    # "How this price was built" — the per-line formula trace the engine already produces for
    # debug=true. Off by default: it is internal build-up, not customer-facing boilerplate. Turned
    # on when the reader needs to check our arithmetic against their own sheet rather than take a
    # total on faith, which is exactly what Tim asked for on the 2026-07-17 call.
    calc_lines: list[dict[str, Any]] | None = field(default=None)
    calc_trace: list[dict[str, Any]] | None = field(default=None)
    include_calc_breakdown: bool = field(default=False)
    # Which build-up was rendered. Frozen into the snapshot at send time so a re-render of an old
    # proposal reproduces what the customer actually received, not what today's default would be.
    calc_audience: str = field(default="internal")


class _SilentUndefined(jinja2.Undefined):
    """Jinja2 Undefined subclass that silently returns empty string for any
    attribute access or string conversion — including chained access like
    ``{{ foo.bar.baz }}`` where ``foo`` is undefined.

    With autoescape ON, markupsafe calls __html__() before escaping.  We
    implement it to return Markup("") so the Undefined is treated as a
    pre-escaped empty string and never raises UndefinedError.
    """

    def __getattr__(self, name: str) -> "_SilentUndefined":
        return _SilentUndefined()

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return ""

    def __html__(self) -> Markup:
        return Markup("")

    def __iter__(self):
        return iter([])

    def __bool__(self) -> bool:
        return False


def _build_jinja_env() -> jinja2.Environment:
    """Return a SANDBOXED Jinja2 Environment with autoescape ON and silent undefined.

    SandboxedEnvironment (deepsec L2): html_body is tenant-editable, so template
    SOURCE is untrusted — autoescape only covers ctx data. The sandbox raises
    SecurityError on unsafe attribute access ({{ ''.__class__... }} SSTI → RCE)."""
    from jinja2.sandbox import SandboxedEnvironment
    return SandboxedEnvironment(
        autoescape=True,
        undefined=_SilentUndefined,
        keep_trailing_newline=True,
    )


_ENV = _build_jinja_env()


def _ctx_to_dict(ctx: ProposalRenderContext) -> dict[str, Any]:
    """Map ProposalRenderContext fields to the nested Jinja2 variable namespace."""
    return {
        "proposal": {
            "title": ctx.proposal_title,
            "date": ctx.proposal_date,
            "version": ctx.proposal_version,
        },
        "customer": {
            "name": ctx.customer_name,
            "company": ctx.customer_company or "",
        },
        "property": {
            "address": ctx.property_address,
            "county": ctx.property_county or "",
            "code_zone": ctx.property_code_zone,
        },
        "quote": {
            "roof_type": ctx.quote_roof_type,
            "num_squares": ctx.quote_num_squares,
            "good_price": ctx.quote_good_price,
            "better_price": ctx.quote_better_price,
            "best_price": ctx.quote_best_price,
            "line_items": ctx.quote_line_items,
        },
        "deposit": {
            "amount": ctx.deposit_amount,
            "instructions": ctx.deposit_instructions,
        },
        "payment": {
            "draws": ctx.payment_draws or [],
        },
        "tenant": {
            "name": ctx.tenant_name,
            "license": ctx.tenant_license or "",
        },
        "accept_url": ctx.accept_url,
        "calc": {
            "include": ctx.include_calc_breakdown,
            "lines": ctx.calc_lines or [],
            "trace": ctx.calc_trace or [],
            "total_display": (ctx.calc_lines or [{}])[-1].get("running_display") if ctx.calc_lines else None,
            "audience": ctx.calc_audience,
        },
        "tc_summary_bullets": ctx.tc_summary_bullets,
        "tc_faq_items": ctx.tc_faq_items,
        "tc_text": ctx.tc_text or "",
        "tc_review_prompts": ctx.tc_review_prompts or [],
        "tc_ai_disclaimer": ctx.tc_ai_disclaimer or "",
        "tc_cover_letter": ctx.tc_cover_letter or "",
        "tc": {
            "text": ctx.tc_text or "",
            "summary_bullets": ctx.tc_summary_bullets or [],
            "faq_items": ctx.tc_faq_items or [],
            "review_prompts": ctx.tc_review_prompts or [],
            "ai_disclaimer": ctx.tc_ai_disclaimer or "",
            "cover_letter": ctx.tc_cover_letter or "",
            "include_terms": ctx.include_terms,
            "include_contract_faq": ctx.include_contract_faq,
        },
    }


def render_proposal_html(template_html: str, ctx: ProposalRenderContext) -> str:
    """Render *template_html* against *ctx* and return the resulting HTML string.

    Autoescape is always enabled — all ctx values are treated as unsafe user
    data. Template authors who need literal HTML in the template body should
    write it directly in the template source, not inject it via context vars.

    Undefined template variables render as empty string (silent Jinja2
    Undefined), matching the TRD §3.2 contract.
    """
    tmpl = _ENV.from_string(template_html)
    return tmpl.render(**_ctx_to_dict(ctx))


# ---------------------------------------------------------------------------
# Default Perkins proposal template
# T&C block is a PLACEHOLDER — pending Tim's review and sign-off.
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{{ proposal.title }}</title>
  <style>
    /* Design system: docs/design/2026-07-24-proposal-pdf-redesign.md. One token per role —
       no new hex literals in this template. Accent is Perkins light blue (#41B1E5, from Tim's
       signature + the logo), NOT the previous #ef3c1a red, which appears nowhere in his brand
       or in the Knowify proposals this document has to sit alongside. */
    @page { size: Letter; margin: 0.5in; }
    :root {
      --fs-brand: 26px; --fs-hero-price: 20px; --fs-h1: 16px; --fs-h2: 13px; --fs-h3: 12px;
      --fs-body: 11px; --fs-legal: 10px; --fs-small: 9px;
      --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 20px; --sp-6: 24px;
      --ink: #1f2937; --ink-muted: #475467; --ink-label: #667085;
      --brand-navy: #1b2a52; --brand-accent: #41b1e5;
      --border: #d0d5dd; --border-hairline: #eaecf0;
      --surface-alt: #f8fafc; --surface-tint-navy: #eef1f8; --surface-tint-info: #f0f9ff;
      --warn-border: #f59e0b; --warn-bg: #fffbeb;
    }
    body { font-family: Arial, Helvetica, sans-serif; color: var(--ink); font-size: var(--fs-body); line-height: 1.45; margin: 0; }
    .page { max-width: 8in; margin: 0 auto; }
    .top { display: grid; grid-template-columns: 1.2fr 1fr; gap: var(--sp-5); border-bottom: 3px solid var(--brand-accent); padding-bottom: var(--sp-3); margin-bottom: var(--sp-3); }
    .brand { color: var(--brand-navy); font-size: var(--fs-brand); font-weight: 900; letter-spacing: .02em; }
    .brand small { display:block; color: var(--ink-label); font-size: var(--fs-small); letter-spacing:0; margin-top:2px; font-weight:700; }
    .page-title { font-size: var(--fs-h1); font-weight:800; color: var(--brand-navy); margin: var(--sp-2) 0 0; }
    .meta { text-align: right; font-size: var(--fs-body); color: var(--ink-muted); }
    .meta div { margin-bottom: 3px; }
    .label { color: var(--ink-label); font-weight:700; text-transform:uppercase; letter-spacing:.04em; font-size: var(--fs-small); }
    .info-grid { display:grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); margin: var(--sp-3) 0 var(--sp-5); }
    .info-box { border:1px solid var(--border); border-radius:6px; padding: var(--sp-3); min-height:54px; }
    /* break-after: avoid keeps a section header with its content. Without it the page-1 break
       landed before "Scope of Work" and the scope card (break-inside: avoid) then didn't fit
       the remainder, leaving page 2 holding nothing but a heading. */
    h2 { color: var(--brand-navy); font-size: var(--fs-h2); font-weight:800; text-transform:uppercase; letter-spacing:.06em; border-bottom:1px solid var(--border); padding-bottom: var(--sp-2); margin: var(--sp-6) 0 var(--sp-3); break-after: avoid; page-break-after: avoid; }
    /* Page 1 is the decision page; this forces everything after the CTA onto page 2. */
    .page-break-1 { break-before: page; page-break-before: always; }
    .tiers { display:grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); margin: var(--sp-3) 0; break-inside: avoid; }
    .tier-card { position:relative; border:1px solid var(--border); border-radius:8px; padding: var(--sp-4) var(--sp-3); text-align:center; }
    .tier-card--featured { border-color: var(--brand-navy); border-width:2px; }
    .tier-flag { position:absolute; top:-10px; left:50%; transform:translateX(-50%); background: var(--brand-navy); color:#fff; font-size: var(--fs-small); font-weight:800; text-transform:uppercase; letter-spacing:.04em; padding:2px 10px; border-radius:10px; }
    .tier-name { color: var(--ink-label); font-size: var(--fs-small); font-weight:800; text-transform:uppercase; letter-spacing:.04em; margin-bottom: var(--sp-1); }
    .tier-price { color: var(--brand-navy); font-size: var(--fs-h3); font-weight:900; }
    .hero-total { margin: var(--sp-5) 0; padding: var(--sp-4); border:1px solid var(--border); border-radius:8px; text-align:center; break-inside: avoid; }
    .hero-total-label { font-size: var(--fs-small); text-transform:uppercase; letter-spacing:.04em; color: var(--ink-label); font-weight:800; }
    .hero-total-price { font-size: var(--fs-hero-price); font-weight:900; color: var(--brand-navy); margin: var(--sp-1) 0; }
    .hero-total-due { font-size: var(--fs-body); color: var(--ink-muted); }
    /* A real Perkins scope runs 5,000+ characters — longer than a page — so it must be allowed
       to flow. Only the header is pinned to the body that follows it. */
    .scope { border:1px solid var(--border); border-radius:7px; margin: var(--sp-2) 0 var(--sp-3); overflow:hidden; }
    .scope-head { display:grid; grid-template-columns: 34px 1fr 130px; gap: var(--sp-2); align-items:center; background: var(--surface-alt); border-bottom:1px solid var(--border); padding: var(--sp-2) var(--sp-3); break-after: avoid; page-break-after: avoid; }
    .scope-no { width:24px; height:24px; border-radius:50%; background: var(--brand-navy); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; }
    .scope-title { color: var(--brand-navy); font-weight:800; font-size: var(--fs-h3); text-transform:uppercase; }
    .scope-price { text-align:right; color: var(--brand-navy); font-size: var(--fs-h3); font-weight:900; }
    .scope-body { padding: var(--sp-3); }
    .qty { color: var(--ink-label); margin-bottom: var(--sp-1); font-size: var(--fs-small); }
    .spec { margin:0; color: var(--ink-muted); white-space: pre-line; }
    .bonus { margin-top: var(--sp-2); background: var(--surface-tint-info); border-left:3px solid var(--brand-navy); padding: var(--sp-2); font-size: var(--fs-small); color: var(--ink-muted); }
    .payment { border:1px solid var(--warn-border); background: var(--warn-bg); border-radius:7px; padding: var(--sp-3); margin: var(--sp-4) 0; break-inside: avoid; }
    .payment table, .tc-ai-faq table, .lumber table { width:100%; border-collapse:collapse; margin-top: var(--sp-2); }
    .payment th, .payment td, .tc-ai-faq th, .tc-ai-faq td, .lumber th, .lumber td { padding: var(--sp-1) 7px; border-bottom:1px solid var(--border-hairline); text-align:left; vertical-align:top; }
    .payment th, .tc-ai-faq th, .lumber th { background: var(--surface-alt); color: var(--ink-muted); font-size: var(--fs-small); text-transform:uppercase; letter-spacing:.04em; }
    .payment tbody tr:first-child td { font-weight:800; }
    .lumber tbody tr:nth-child(even) td, .payment tbody tr:nth-child(even) td { background: var(--surface-alt); }
    .amt { text-align:right !important; white-space:nowrap; }
    .accept { text-align:center; margin: var(--sp-4) 0 var(--sp-5); padding: var(--sp-4); border-radius:8px; background: var(--surface-tint-info); break-inside: avoid; }
    .accept a { display:inline-block; background: var(--brand-navy); color:#fff; text-decoration:none; padding:12px 28px; border-radius:6px; font-weight:800; font-size:13px; }
    .calc { margin: var(--sp-4) 0; border:1px solid var(--border); border-radius:7px; overflow:hidden; break-inside: avoid; }
    .calc-head { background: var(--surface-tint-navy); border-bottom:1px solid var(--border); padding: var(--sp-2) var(--sp-3); font-weight:800; color: var(--brand-navy); font-size: var(--fs-h3); }
    .calc table { width:100%; border-collapse:collapse; }
    .calc th, .calc td { padding: var(--sp-1) var(--sp-3); border-bottom:1px solid var(--border-hairline); text-align:left; vertical-align:top; font-size: var(--fs-small); }
    .calc th { background: var(--surface-alt); color: var(--ink-label); text-transform:uppercase; letter-spacing:.04em; }
    .calc td.formula { color: var(--ink-label); font-family: "Courier New", monospace; }
    .calc tr.total td { font-weight:800; color: var(--brand-navy); border-top:2px solid var(--brand-navy); font-size: var(--fs-body); }
    .calc-note { padding: var(--sp-2) var(--sp-3); background: var(--surface-alt); color: var(--ink-muted); font-size: var(--fs-small); }
    .terms { margin-top: var(--sp-5); font-size: var(--fs-legal); color: var(--ink-muted); }
    /* pre-line, not pre-wrap: keeps the author's blank-line paragraphs, drops the hard-wrap
       ragged edges that made the T&C read as one blob. Content is untouched. */
    .terms pre { white-space: pre-line; font-family:Arial, Helvetica, sans-serif; line-height:1.6; margin:0; }
    .tc-ai-cover { margin-top: var(--sp-4); padding: var(--sp-3) var(--sp-4); background: var(--surface-tint-navy); border-left:4px solid var(--brand-navy); font-size: var(--fs-small); }
    .tc-ai-cover p { margin: 0 0 var(--sp-2) 0; }
    .tc-ai-faq { margin-top: var(--sp-5); page-break-before: always; }
    .faq-item { break-inside: avoid; padding: var(--sp-3) 0; border-bottom:1px solid var(--border-hairline); }
    .faq-item:last-child { border-bottom:0; }
    .faq-q { font-weight:800; color: var(--brand-navy); margin-bottom: var(--sp-1); }
    .faq-a { color: var(--ink); }
    .lumber { page-break-before: always; font-size: var(--fs-legal); color: var(--ink-muted); }
    .footer { margin-top: var(--sp-4); border-top:1px solid var(--border); padding-top: var(--sp-3); font-size: var(--fs-body); color: var(--ink-label); text-align:center; }
  </style>
</head>
<body><div class="page">
  <div class="top">
    <div>
      <div class="brand">{{ tenant.name }}<small>{% if tenant.license %}License #{{ tenant.license }}{% endif %}</small></div>
      <h1 class="page-title">Roofing Proposal</h1>
    </div>
    <div class="meta">
      <div><span class="label">Project</span> {{ proposal.title }}</div>
      <div><span class="label">Date</span> {{ proposal.date }}</div>
      {% if proposal.version > 1 %}<div><span class="label">Revision</span> v{{ proposal.version }}</div>{% endif %}
    </div>
  </div>

  <div class="info-grid">
    <div class="info-box"><div class="label">To</div><strong>{{ customer.name }}</strong>{% if customer.company %}<br>{{ customer.company }}{% endif %}</div>
    <div class="info-box"><div class="label">Address</div><strong>{{ property.address }}</strong>{% if property.county %}<br>{{ property.county }} County{% endif %}{% if property.code_zone %}<br>{{ property.code_zone }}{% endif %}</div>
  </div>

  {# ── Page 1: the decision page — options, price, signature. Detail follows overleaf. ── #}
  {% if quote.better_price or quote.best_price %}
  <h2>Your Options</h2>
  <div class="tiers">
    {% for name, price, featured in [("Good", quote.good_price, False), ("Better", quote.better_price, True), ("Best", quote.best_price, False)] %}
      {% if price %}
      <div class="tier-card{% if featured %} tier-card--featured{% endif %}">
        {% if featured %}<div class="tier-flag">Recommended</div>{% endif %}
        <div class="tier-name">{{ name }}</div>
        <div class="tier-price">{{ price }}</div>
      </div>
      {% endif %}
    {% endfor %}
  </div>
  {% endif %}

  <div class="hero-total">
    <div class="hero-total-label">Total Investment</div>
    <div class="hero-total-price">{{ quote.good_price }}</div>
    {% if deposit.amount %}<div class="hero-total-due">Due at signing: {{ deposit.amount }}</div>{% endif %}
  </div>

  <div class="accept">
    <p>Review and accept your proposal online:</p>
    <a href="{{ accept_url }}">Review &amp; Accept Proposal</a>
    <div style="font-size:9px;color:#667085;margin-top:6px;">{{ accept_url }}</div>
  </div>

  <h2 class="page-break-1">Scope of Work</h2>
  {% if quote.line_items %}
    {% for item in quote.line_items %}
    <div class="scope">
      <div class="scope-head">
        <div class="scope-no">{{ loop.index }}</div>
        <div class="scope-title">{{ item.label }}</div>
        <div class="scope-price">{{ item.price_display or ("$%.2f"|format(item.total)) }}</div>
      </div>
      <div class="scope-body">
        {% if item.qty_display %}<div class="qty">Quantity: {{ item.qty_display }} {{ item.unit }}</div>{% endif %}
        {# label is description-up-to-the-em-dash, so with no em-dash the two are identical —
           printing both repeats the card title verbatim as its own body. #}
        {% if item.description and item.description != item.label %}<p class="spec">{{ item.description }}</p>{% endif %}
        {# Josh's real scope templates carry their own itemised BONUS VALUES list; don't print
           the generic summary underneath it. #}
        {% if "BONUS VALUE" not in (item.description or "")|upper %}
        <div class="bonus"><strong>PERKINS BONUS VALUES:</strong> standard cleanup, project supervision, and warranty support are included unless otherwise noted.</div>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  {% else %}
    <div class="scope">
      <div class="scope-head"><div class="scope-no">1</div><div class="scope-title">Roof Replacement Proposal</div><div class="scope-price">{{ quote.good_price }}</div></div>
      <div class="scope-body"><p class="spec">Roof type: {{ quote.roof_type }}{% if quote.num_squares %}; area {{ quote.num_squares }} squares{% endif %}.</p></div>
    </div>
    {% if quote.better_price %}<div class="scope"><div class="scope-head"><div class="scope-no">2</div><div class="scope-title">Better Option</div><div class="scope-price">{{ quote.better_price }}</div></div></div>{% endif %}
    {% if quote.best_price %}<div class="scope"><div class="scope-head"><div class="scope-no">3</div><div class="scope-title">Best Option</div><div class="scope-price">{{ quote.best_price }}</div></div></div>{% endif %}
  {% endif %}

  {# The old Subtotal/Tax 0%/Total block was three rows of the same number plus an invented tax
     line; page 1's hero total carries the price now. #}
  <div class="payment">
    <strong>Payment Schedule</strong>
    {% if payment.draws %}
    <table>
      <thead><tr><th>#</th><th>Milestone</th><th class="amt">%</th><th class="amt">Amount</th></tr></thead>
      <tbody>
        {% for draw in payment.draws %}
        <tr><td>{{ draw.sequence }}</td><td>{{ draw.label }}</td><td class="amt">{{ draw.pct }}</td><td class="amt">{{ draw.amount }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p>Deposit: <strong>{{ deposit.amount or "None" }}</strong></p>
    {% endif %}
    {% if deposit.instructions %}<p>{{ deposit.instructions }}</p>{% endif %}
  </div>

  {% if calc.include and calc.lines %}
  <div class="calc">
    <div class="calc-head">How this price was built</div>
    <table>
      <thead><tr><th>Line</th><th>How it is calculated</th><th class="amt">Amount</th></tr></thead>
      <tbody>
        {% for line in calc.lines %}
        <tr>
          <td>{{ line.label }}</td>
          <td class="formula">{{ line.formula }}</td>
          <td class="amt">{{ line.amount_display }}</td>
        </tr>
        {% endfor %}
        {% if calc.total_display %}
        <tr class="total"><td>Total</td><td></td><td class="amt">{{ calc.total_display }}</td></tr>
        {% endif %}
      </tbody>
    </table>
    <div class="calc-note">Every figure above comes from the price book in force on the date of
      this proposal; nothing is entered by hand. The reference beside each line is the rule it was
      taken from, so this quote can be checked line by line rather than accepted on the total.</div>
  </div>
  {% endif %}

  <div class="footer">{{ tenant.name }}{% if tenant.license %} · License #{{ tenant.license }}{% endif %} · 575 NW 152nd St, Miami, FL 33169 · 15658 Alexander Run, Jupiter, FL 33478</div>

  {% if tc.include_terms %}
  <div class="terms">
    <h2>Terms &amp; Conditions</h2>
    {% if tc.text %}<pre>{{ tc.text }}</pre>{% else %}<p>Terms and conditions to be attached.</p>{% endif %}
  </div>
  {% endif %}

  {% if tc.include_terms and (tc.summary_bullets or tc.review_prompts) %}
  <div class="tc-ai-cover">
    {% if tc.cover_letter %}<p>{{ tc.cover_letter }}</p>{% elif tc.summary_bullets %}<p>While we recommend reading everything yourself and thoroughly understanding the agreement you&#39;re entering into, we&#39;ve created an FAQ for your review and here&#39;s a concise summary:</p>{% endif %}
    {% if tc.summary_bullets %}<ul>{% for bullet in tc.summary_bullets %}<li>{{ bullet }}</li>{% endfor %}</ul>{% endif %}
    {% if tc.review_prompts %}<p><strong>Helpful AI review prompts:</strong></p><ol>{% for prompt in tc.review_prompts %}<li>{{ prompt }}</li>{% endfor %}</ol>{% endif %}
    {% if tc.ai_disclaimer %}<p><em>{{ tc.ai_disclaimer }}</em></p>{% endif %}
  </div>
  {% endif %}

  {% if tc.include_contract_faq and tc.faq_items %}
  <div class="tc-ai-faq">
    <h2>Contract FAQ</h2>
    {# Stacked Q/A cards: a 2-column table is the wrong primitive for prose. #}
    <div class="faq-list">
      {% for item in tc.faq_items %}
      <div class="faq-item">
        <div class="faq-q">{{ item.q }}</div>
        <div class="faq-a">{{ item.a }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  <div class="lumber">
    <h2>Lumber Schedule / Additional Work Exhibit</h2>
    <p>Wood replacement and unforeseen substrate repairs are billed as required by the contract. Standard proposals include the wood allotment stated in the scope; additional wood and extra work are billed at the schedule below unless otherwise written in the proposal.</p>
    <table>
      <tr><th>Category</th><th>Representative schedule</th></tr>
      <tr><td>Decking</td><td>T&amp;G 1x6, T&amp;G 1x8, 1/2&quot;, 5/8&quot;, and 3/4&quot; plywood charged per published Perkins schedule.</td></tr>
      <tr><td>Fascia / nailers</td><td>Yellow pine and cedar dimensional lumber billed per linear foot by actual size used.</td></tr>
      <tr><td>Double demo / insulation</td><td>Additional interply, anchor sheet, self-adhered direct-to-deck, and insulation work billed per square foot where required.</td></tr>
      <tr><td>Other unit work</td><td>Vents, drains, hurricane straps, flashing, stucco, and related extras billed by unit or time-and-materials as applicable.</td></tr>
    </table>
  </div>
</div></body></html>
"""


def _fold_for_customer(
    details: list[dict[str, Any]], result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collapse base cost, overhead and profit into a single per-square line.

    Order is preserved by folding in place at the position of the first folded line, so the
    customer's page reads in the same sequence as the internal one.
    """
    folded_total = sum(float(li.get("amount") or 0)
                       for li in details if li.get("key") in _CUSTOMER_FOLDED_KEYS)
    squares = float(result.get("num_squares") or 0)
    per_sq = folded_total / squares if squares else 0.0
    out: list[dict[str, Any]] = []
    placed = False
    for li in details:
        if li.get("key") not in _CUSTOMER_FOLDED_KEYS:
            out.append(li)
            continue
        if placed:
            continue
        placed = True
        out.append({
            "key": "labour_materials_overhead",
            "label": _CUSTOMER_FOLD_LABEL,
            "amount": folded_total,
            # A pre-substituted formula: _line_formula would otherwise see no per_sq/explain and
            # fall through to "fixed amount", which is exactly the opposite of the point.
            "explain": {"inputs": {"per_sq": per_sq, "squares": squares}},
        })
    return out


# Back-end lines: what the money pays US, not what it buys the homeowner. Tim, 2026-07-27:
# *"the PM incentive is not something the customer ever needs to see… we usually don't want to show
# them any of the back-end stuff."* The first cut of the fold list was built as the
# margin-recovery set (base+overhead+profit) rather than the back-end set, so PM Incentive still
# printed as its own row on a customer document.
#
# `new_bonus_values` ($1,350 fixed) is the open case and is deliberately NOT here: Tim's sheet lists
# it beside permit and delivery, which customers do see, and his proposals show a customer-facing
# "PERKINS BONUS VALUES" stack — so folding it is a guess, not his instruction. Pending Tim.
_BACK_END_KEYS = ("profit", "pm_incentive")

# Lines folded into one figure for a customer. Overhead and profit alone are not enough: Tim
# publishes a per-square overhead ($185/sq FBC 13" tile), so "base + overhead+profit" would let a
# reader subtract the published overhead and land within a few dollars of the margin. Folding the
# base in too leaves one all-in per-square price, which is what his published sheet quotes anyway.
_CUSTOMER_FOLDED_KEYS = ("base_cost_lm", "overhead", *_BACK_END_KEYS)
_CUSTOMER_FOLD_LABEL = "Labour, materials and overhead"


def calc_lines_from_estimate(
    result: dict[str, Any], *, audience: str = "internal",
) -> list[dict[str, Any]]:
    """Turn an estimate's debug trace into proposal-ready "how this was built" rows.

    The engine already produces a formula + inputs for every priced line when debug=true; it was
    only ever returned to an admin on the quote response and stripped before persistence, so a
    customer could see the total but never the arithmetic. Tim's whole objection on the
    2026-07-17 call was to numbers he could not check against his own sheet.

    Substitutes the actual values into the formula so a reader sees "35 sq x $783.88" rather than
    "per_sq x squares", and keeps a running subtotal so the last row's total is verifiable.

    Two audiences, because they want opposite things (Jon, 2026-07-25: *"we can collapse the price
    with days in to price per sq. to show the customer. we don't want to show them the profit"*):

    ``internal``  Tim, Marco, Josh, us. Every line, overhead as "5 days tile x $745 + 3 days demo
                  x $1,050" because the days are the whole argument, and profit shown.
    ``customer``  the homeowner. Base cost, overhead and every back-end line (profit, PM
                  incentive) fold into ONE per-square figure.

    Hiding the profit row is not sufficient on its own — the remaining rows still sum to the total,
    so anything left out can be recovered by subtraction. Folding keeps the arithmetic closed:
    every row a customer sees is real, they add up to the total, and no combination of them
    isolates the margin. ``test_customer_mode_cannot_be_differenced_back_to_profit`` proves it by
    brute force over every subset of the customer rows.
    """
    if audience not in ("internal", "customer"):
        raise ValueError(f"unknown calc audience {audience!r}")
    details = list(result.get("line_items_detail") or [])
    if audience == "customer":
        details = _fold_for_customer(details, result)

    out: list[dict[str, Any]] = []
    running = 0.0
    for li in details:
        amount = float(li.get("amount") or 0)
        running += amount
        explain = li.get("explain") or {}
        inputs = explain.get("inputs") or {}
        per_sq, squares = inputs.get("per_sq"), inputs.get("squares")
        day_parts = [
            f"{v:g} days {k[:-5].replace('_', ' ')} x ${float(inputs.get(k[:-5] + '_rate', 0)):,.0f}"
            for k, v in inputs.items()
            if k.endswith("_days") and v and inputs.get(k[:-5] + "_rate")
        ]
        if day_parts:
            # Overhead is the one line Tim insists is time-driven, so show the DAYS rather than
            # collapsing to a per-square figure that hides them.
            formula = " + ".join(day_parts)
        elif per_sq is not None and squares:
            formula = f"{squares:g} squares x ${float(per_sq):,.2f}"
        elif li.get("per_sq"):
            formula = f"{result.get('num_squares', 0):g} squares x ${float(li['per_sq']):,.2f}"
        else:
            # Config-key names leak internals into a customer document; keep the first clause only.
            # Internal annotations ("NOTE: ...", config key names, pending-Tim asides) must not
            # reach a customer document.
            raw = (explain.get("formula") or "")
            raw = re.split(r"\.\s|\(|,|NOTE:", raw)[0].strip().rstrip(".")
            formula = raw if raw and "_" not in raw else "fixed amount"
        out.append({
            "key": li.get("key"),
            "label": li.get("label") or li.get("key"),
            "formula": formula,
            "amount_display": f"${amount:,.2f}",
            "running_display": f"${running:,.2f}",
        })
    return out
