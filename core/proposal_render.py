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
    tc_summary_bullets: list[str] | None = field(default=None)
    tc_faq_items: list[dict] | None = field(default=None)


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
        "tenant": {
            "name": ctx.tenant_name,
            "license": ctx.tenant_license or "",
        },
        "accept_url": ctx.accept_url,
        "tc_summary_bullets": ctx.tc_summary_bullets,
        "tc_faq_items": ctx.tc_faq_items,
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ proposal.title }}</title>
  <style>
    body { font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #222; margin: 0; padding: 0; }
    .page { max-width: 820px; margin: 0 auto; padding: 40px 48px; }
    .header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #C0392B; padding-bottom: 16px; margin-bottom: 24px; }
    .logo-area h1 { margin: 0; font-size: 22px; color: #C0392B; }
    .logo-area p { margin: 2px 0; font-size: 12px; color: #555; }
    .meta-block { text-align: right; font-size: 12px; color: #555; }
    .meta-block .label { font-weight: bold; color: #333; }
    h2 { font-size: 16px; color: #C0392B; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }
    .address-block { background: #f9f9f9; border-left: 4px solid #C0392B; padding: 12px 16px; margin-bottom: 20px; }
    .tier-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    .tier-table th { background: #C0392B; color: #fff; padding: 10px 14px; text-align: left; font-size: 13px; }
    .tier-table td { padding: 10px 14px; border-bottom: 1px solid #eee; }
    .tier-table tr:last-child td { border-bottom: none; }
    .tier-table .price { font-weight: bold; font-size: 16px; color: #C0392B; text-align: right; }
    .line-items-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
    .line-items-table th { background: #555; color: #fff; padding: 6px 10px; text-align: left; }
    .line-items-table td { padding: 6px 10px; border-bottom: 1px solid #f0f0f0; }
    .deposit-box { background: #fff8e1; border: 1px solid #f0c040; border-radius: 4px; padding: 14px 18px; margin-top: 20px; }
    .deposit-box .amount { font-size: 20px; font-weight: bold; color: #333; }
    .accept-section { margin-top: 28px; text-align: center; }
    .accept-section a { display: inline-block; background: #C0392B; color: #fff; padding: 14px 32px; border-radius: 4px; text-decoration: none; font-size: 16px; font-weight: bold; letter-spacing: 0.5px; }
    .tc-block { margin-top: 36px; font-size: 11px; color: #888; border-top: 1px solid #eee; padding-top: 14px; }
    .tc-ai-cover { margin-top: 24px; padding: 16px 20px; background: #f4f8ff; border-left: 4px solid #2471a3; font-size: 12px; color: #333; }
    .tc-ai-cover p { margin: 0 0 10px 0; }
    .tc-ai-cover ul { margin: 8px 0 12px 0; padding-left: 20px; }
    .tc-ai-cover li { margin-bottom: 4px; }
    .tc-ai-prompts { margin-top: 10px; }
    .tc-ai-prompts p { font-weight: bold; margin: 0 0 4px 0; }
    .tc-ai-prompts ol { margin: 0; padding-left: 20px; }
    .tc-ai-prompts li { margin-bottom: 2px; font-style: italic; color: #555; }
    .tc-ai-disclaimer { margin-top: 10px; font-size: 11px; color: #888; font-style: italic; }
    .tc-ai-faq { margin-top: 24px; page-break-before: always; }
    .tc-ai-faq h2 { font-size: 15px; color: #2471a3; border-bottom: 1px solid #cce; padding-bottom: 4px; margin-top: 0; }
    .tc-ai-faq table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .tc-ai-faq th { background: #2471a3; color: #fff; padding: 8px 12px; text-align: left; }
    .tc-ai-faq td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: top; }
    .tc-ai-faq td:first-child { font-weight: bold; width: 35%; }
    .footer { margin-top: 40px; font-size: 11px; color: #aaa; text-align: center; border-top: 1px solid #eee; padding-top: 12px; }
  </style>
</head>
<body>
<div class="page">

  <div class="header">
    <div class="logo-area">
      <h1>{{ tenant.name }}</h1>
      {% if tenant.license %}<p>License #{{ tenant.license }}</p>{% endif %}
    </div>
    <div class="meta-block">
      <p><span class="label">Proposal:</span> {{ proposal.title }}</p>
      <p><span class="label">Date:</span> {{ proposal.date }}</p>
      {% if proposal.version > 1 %}<p><span class="label">Revision:</span> v{{ proposal.version }}</p>{% endif %}
    </div>
  </div>

  <h2>Prepared For</h2>
  <div class="address-block">
    <strong>{{ customer.name }}</strong>{% if customer.company %} — {{ customer.company }}{% endif %}<br>
    {{ property.address }}
    {% if property.county %}<br>County: {{ property.county }}{% endif %}
    {% if property.code_zone %}<br>Wind Zone: {{ property.code_zone }}{% endif %}
  </div>

  <h2>Roof Replacement Options</h2>
  <p>Roof type: <strong>{{ quote.roof_type }}</strong> &nbsp;|&nbsp; Area: <strong>{{ quote.num_squares }} squares</strong></p>

  <table class="tier-table">
    <tr>
      <th>Option</th>
      <th style="text-align:right">Investment</th>
    </tr>
    <tr>
      <td><strong>Good</strong></td>
      <td class="price">{{ quote.good_price }}</td>
    </tr>
    <tr>
      <td><strong>Better</strong></td>
      <td class="price">{{ quote.better_price }}</td>
    </tr>
    <tr>
      <td><strong>Best</strong></td>
      <td class="price">{{ quote.best_price }}</td>
    </tr>
  </table>

  {% if quote.line_items %}
  <h2>Scope of Work</h2>
  <table class="line-items-table">
    <tr>
      <th>Description</th>
      <th>Qty</th>
      <th>Unit</th>
      <th style="text-align:right">Unit Price</th>
      <th style="text-align:right">Total</th>
    </tr>
    {% for item in quote.line_items %}
    <tr>
      <td>{{ item.label }}</td>
      <td>{{ item.qty }}</td>
      <td>{{ item.unit }}</td>
      <td style="text-align:right">${{ "%.2f"|format(item.unit_price) }}</td>
      <td style="text-align:right">${{ "%.2f"|format(item.total) }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  <div class="deposit-box">
    <p style="margin:0 0 6px 0"><strong>Deposit Required to Schedule</strong></p>
    <p class="amount">{{ deposit.amount }}</p>
    {% if deposit.instructions %}<p style="margin:6px 0 0 0; font-size:12px; color:#666;">{{ deposit.instructions }}</p>{% endif %}
  </div>

  <div class="accept-section">
    <p>Ready to move forward? Review and accept your proposal online:</p>
    <a href="{{ accept_url }}">Review &amp; Accept Proposal</a>
    <p style="font-size:11px; color:#999; margin-top:8px;">{{ accept_url }}</p>
  </div>

  <div class="tc-block">
    <p><strong>Terms &amp; Conditions</strong></p>
    <p>
      [PLACEHOLDER — T&amp;C text pending Tim Perkins review and sign-off. This block will be
      replaced with the executed terms from the master service agreement before any proposals
      are sent to clients. Do not use this template in production until T&amp;C are approved.]
    </p>
  </div>

  {% if tc_summary_bullets %}
  <div class="tc-ai-cover">
    <p>While we recommend reading everything yourself and thoroughly understanding the agreement you&#39;re entering into, we&#39;ve created an FAQ for your review on the last page and here&#39;s a concise summary:</p>
    <ul>
      {% for bullet in tc_summary_bullets %}
      <li>{{ bullet }}</li>
      {% endfor %}
    </ul>
    <div class="tc-ai-prompts">
      <p>Questions you might want to ask your AI assistant about this contract:</p>
      <ol>
        <li>Summarize my obligations and what I&#39;m agreeing to.</li>
        <li>What are the payment terms, deposits, and any penalties or late fees?</li>
        <li>What are my cancellation/rescission rights and any fees?</li>
        <li>What warranties and guarantees am I getting, and what voids them?</li>
        <li>What happens in delays, weather, or unforeseen conditions?</li>
        <li>What am I responsible for vs. the contractor?</li>
      </ol>
    </div>
    <p class="tc-ai-disclaimer">AI is not a replacement for legal counsel, and we always recommend for full validation and protection that you have an attorney review this agreement.</p>
  </div>
  {% endif %}

  {% if tc_faq_items %}
  <div class="tc-ai-faq">
    <h2>Frequently Asked Questions</h2>
    <table>
      <tr>
        <th>Question</th>
        <th>Answer</th>
      </tr>
      {% for item in tc_faq_items %}
      <tr>
        <td>{{ item.q }}</td>
        <td>{{ item.a }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  <div class="footer">
    <p>{{ tenant.name }} &nbsp;|&nbsp; {% if tenant.license %}License #{{ tenant.license }} &nbsp;|&nbsp; {% endif %}This proposal is valid for 30 days from the date above.</p>
  </div>

</div>
</body>
</html>
"""
