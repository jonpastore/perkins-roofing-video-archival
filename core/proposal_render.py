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
    payment_draws: list[dict[str, Any]] | None = field(default=None)
    tc_summary_bullets: list[str] | None = field(default=None)
    tc_faq_items: list[dict] | None = field(default=None)
    tc_text: str | None = field(default=None)
    tc_review_prompts: list[str] | None = field(default=None)
    tc_ai_disclaimer: str | None = field(default=None)
    tc_cover_letter: str | None = field(default=None)


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
    @page { size: Letter; margin: 0.45in; }
    body { font-family: Arial, Helvetica, sans-serif; color: #1f2937; font-size: 11px; line-height: 1.35; margin: 0; }
    .page { max-width: 8in; margin: 0 auto; }
    .top { display: grid; grid-template-columns: 1.2fr 1fr; gap: 18px; border-bottom: 3px solid #ef3c1a; padding-bottom: 12px; margin-bottom: 12px; }
    .brand { color: #1b2a52; font-size: 26px; font-weight: 900; letter-spacing: .02em; }
    .brand small { display:block; color:#667085; font-size:10px; letter-spacing:0; margin-top:2px; font-weight:700; }
    .meta { text-align: right; font-size: 11px; color:#344054; }
    .meta div { margin-bottom: 3px; }
    .label { color:#667085; font-weight:700; text-transform:uppercase; letter-spacing:.04em; font-size:9px; }
    .info-grid { display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0 16px; }
    .info-box { border:1px solid #d0d5dd; border-radius:6px; padding:10px 12px; min-height:54px; }
    h2 { color:#1b2a52; font-size:13px; text-transform:uppercase; letter-spacing:.06em; border-bottom:1px solid #d0d5dd; padding-bottom:5px; margin:18px 0 9px; }
    .scope { border:1px solid #d0d5dd; border-radius:7px; margin: 10px 0 12px; break-inside: avoid; overflow:hidden; }
    .scope-head { display:grid; grid-template-columns: 34px 1fr 130px; gap:10px; align-items:center; background:#f8fafc; border-bottom:1px solid #d0d5dd; padding:9px 12px; }
    .scope-no { width:24px; height:24px; border-radius:50%; background:#1b2a52; color:white; display:flex; align-items:center; justify-content:center; font-weight:800; }
    .scope-title { color:#1b2a52; font-weight:800; font-size:12px; text-transform:uppercase; }
    .scope-price { text-align:right; color:#1b2a52; font-size:14px; font-weight:900; }
    .scope-body { padding:10px 12px; }
    .qty { color:#667085; margin-bottom:6px; font-size:10px; }
    .spec { margin:0; color:#344054; }
    .bonus { margin-top:8px; background:#f0f9ff; border-left:3px solid #1b2a52; padding:7px 9px; font-size:10px; color:#344054; }
    .totals { margin-left:auto; width:260px; border:1px solid #d0d5dd; border-radius:7px; overflow:hidden; margin-top:14px; }
    .totals-row { display:flex; justify-content:space-between; padding:8px 12px; border-bottom:1px solid #eaecf0; }
    .totals-row:last-child { border-bottom:0; background:#1b2a52; color:white; font-weight:900; font-size:14px; }
    .payment { border:1px solid #f59e0b; background:#fffbeb; border-radius:7px; padding:10px 12px; margin: 14px 0; break-inside: avoid; }
    .payment table, .tc-ai-faq table, .lumber table { width:100%; border-collapse:collapse; margin-top:7px; }
    .payment th, .payment td, .tc-ai-faq th, .tc-ai-faq td, .lumber th, .lumber td { padding:5px 7px; border-bottom:1px solid #eaecf0; text-align:left; vertical-align:top; }
    .payment th, .tc-ai-faq th, .lumber th { background:#f8fafc; color:#344054; font-size:9px; text-transform:uppercase; letter-spacing:.04em; }
    .amt { text-align:right !important; white-space:nowrap; }
    .accept { text-align:center; margin:16px 0 18px; padding:14px; border:1px solid #d0d5dd; border-radius:8px; }
    .accept a { display:inline-block; background:#ef3c1a; color:#fff; text-decoration:none; padding:10px 22px; border-radius:6px; font-weight:800; }
    .terms { margin-top:18px; font-size:9px; color:#475467; }
    .terms pre { white-space:pre-wrap; font-family:Arial, Helvetica, sans-serif; margin:0; }
    .tc-ai-cover { margin-top:14px; padding:12px 14px; background:#f4f8ff; border-left:4px solid #2471a3; font-size:10px; }
    .tc-ai-cover p { margin: 0 0 8px 0; }
    .tc-ai-faq { margin-top:18px; page-break-before: always; }
    .tc-ai-faq h2 { color:#2471a3; }
    .lumber { page-break-before: always; font-size:9px; color:#344054; }
    .footer { margin-top:18px; border-top:1px solid #d0d5dd; padding-top:10px; font-size:10px; color:#667085; text-align:center; }
  </style>
</head>
<body><div class="page">
  <div class="top">
    <div>
      <div class="brand">{{ tenant.name }}<small>{% if tenant.license %}License #{{ tenant.license }}{% endif %}</small></div>
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

  <h2>Scope of Work</h2>
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
        <p class="spec">{{ item.description }}</p>
        <div class="bonus"><strong>PERKINS BONUS VALUES:</strong> standard cleanup, project supervision, and warranty support are included unless otherwise noted.</div>
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

  {% if quote.better_price or quote.best_price %}
  <h2>Alternate Package Options</h2>
  <div class="scope">
    <div class="scope-body">
      <div style="display:grid;grid-template-columns:1fr 120px;gap:8px;">
        {% if quote.good_price %}<div>Good</div><div style="text-align:right;font-weight:800;">{{ quote.good_price }}</div>{% endif %}
        {% if quote.better_price %}<div>Better</div><div style="text-align:right;font-weight:800;">{{ quote.better_price }}</div>{% endif %}
        {% if quote.best_price %}<div>Best</div><div style="text-align:right;font-weight:800;">{{ quote.best_price }}</div>{% endif %}
      </div>
    </div>
  </div>
  {% endif %}

  <div class="totals">
    <div class="totals-row"><span>Subtotal</span><span>{{ quote.good_price }}</span></div>
    <div class="totals-row"><span>Tax</span><span>0%</span></div>
    <div class="totals-row"><span>Total</span><span>{{ quote.good_price }}</span></div>
  </div>

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

  <div class="accept">
    <p>Review and accept your proposal online:</p>
    <a href="{{ accept_url }}">Review &amp; Accept Proposal</a>
    <div style="font-size:9px;color:#667085;margin-top:6px;">{{ accept_url }}</div>
  </div>

  <div class="footer">Tim Kanak · Perkins Roofing Jupiter · 15658 Alexander Run, Jupiter, FL 33478</div>

  <div class="terms">
    <h2>Terms &amp; Conditions</h2>
    {% if tc.text %}<pre>{{ tc.text }}</pre>{% else %}<p>Terms and conditions to be attached.</p>{% endif %}
  </div>

  {% if tc.summary_bullets or tc.review_prompts %}
  <div class="tc-ai-cover">
    {% if tc.cover_letter %}<p>{{ tc.cover_letter }}</p>{% elif tc.summary_bullets %}<p>While we recommend reading everything yourself and thoroughly understanding the agreement you&#39;re entering into, we&#39;ve created an FAQ for your review and here&#39;s a concise summary:</p>{% endif %}
    {% if tc.summary_bullets %}<ul>{% for bullet in tc.summary_bullets %}<li>{{ bullet }}</li>{% endfor %}</ul>{% endif %}
    {% if tc.review_prompts %}<p><strong>Helpful AI review prompts:</strong></p><ol>{% for prompt in tc.review_prompts %}<li>{{ prompt }}</li>{% endfor %}</ol>{% endif %}
    {% if tc.ai_disclaimer %}<p><em>{{ tc.ai_disclaimer }}</em></p>{% endif %}
  </div>
  {% endif %}

  {% if tc.faq_items %}
  <div class="tc-ai-faq">
    <h2>Contract FAQ</h2>
    <table>
      {% for item in tc.faq_items %}
      <tr><td><strong>{{ item.q }}</strong></td><td>{{ item.a }}</td></tr>
      {% endfor %}
    </table>
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
