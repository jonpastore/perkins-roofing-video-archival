"""Proposal/contract document renderer for the JB3 engine (core — pure, no I/O).

Renders a `compose_proposal(...)` result into contract HTML: the composable scope
blocks, package tier, subtotal/$0-tax/total, the payment-schedule draws, the
metal-vs-standard expiry, the HVHZ conditional, and (optionally) the grounded
T&C-summary bullets from core/contract_faq.py.

Distinct from core/proposal_render.py, which renders the older Good/Better/Best
quote shape. This one consumes the multi-scope + tier + draw-schedule structure the
JB3 engine produces and the 8 golden sold proposals use.

    render_proposal_doc_html(template_html, ctx) -> str
    proposal_doc_context(proposal, ...) -> ProposalDocContext   # from compose_proposal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jinja2

from core.proposal_render import _SilentUndefined


@dataclass
class ProposalDocContext:
    title: str
    date: str
    customer_name: str
    property_address: str
    hvhz: bool
    scope_lines: list[dict[str, Any]]      # from proposal["scope_lines"]
    subtotal: str
    tax: str
    contract_total: str
    draws: list[dict[str, Any]]            # from proposal["payment_schedule"]["draws"]
    expiry_days: int
    tenant_name: str
    tenant_license: str | None = None
    tc_summary_bullets: list[str] | None = field(default=None)
    marketing_appendix: str | None = None


def _build_jinja_env() -> jinja2.Environment:
    from jinja2.sandbox import SandboxedEnvironment
    return SandboxedEnvironment(autoescape=True, undefined=_SilentUndefined, keep_trailing_newline=True)


_ENV = _build_jinja_env()


def _ctx_to_dict(ctx: ProposalDocContext) -> dict[str, Any]:
    return {
        "proposal": {"title": ctx.title, "date": ctx.date, "expiry_days": ctx.expiry_days,
                     "subtotal": ctx.subtotal, "tax": ctx.tax, "total": ctx.contract_total,
                     "hvhz": ctx.hvhz},
        "customer": {"name": ctx.customer_name},
        "property": {"address": ctx.property_address},
        "scope_lines": ctx.scope_lines,
        "draws": ctx.draws,
        "tenant": {"name": ctx.tenant_name, "license": ctx.tenant_license or ""},
        "tc_summary_bullets": ctx.tc_summary_bullets,
        "marketing_appendix": ctx.marketing_appendix or "",
    }


def render_proposal_doc_html(template_html: str, ctx: ProposalDocContext) -> str:
    return _ENV.from_string(template_html).render(**_ctx_to_dict(ctx))


def proposal_doc_context(
    proposal: dict,
    *,
    date: str,
    tenant_name: str,
    tenant_license: str | None = None,
    tc_summary_bullets: list[str] | None = None,
    marketing_appendix: str | None = None,
) -> ProposalDocContext:
    """Build the render context from a core.proposal_gen.compose_proposal(...) result."""
    lines = []
    for ln in proposal.get("scope_lines", []):
        optional = ln.get("is_optional") and not ln.get("included")
        desc = ln.get("description", "")
        if ln.get("is_optional"):
            desc = f"(OPTIONAL) {desc}" if not desc.startswith("(OPTIONAL)") else desc
        lines.append({
            "description": desc,
            "squares": ln.get("squares") or "",
            "unit_price": ln.get("unit_price") or "",
            "line_total": ln.get("line_total", "0.00"),
            "excluded": bool(optional),
        })
    return ProposalDocContext(
        title=proposal.get("project_name") or f"Roofing Proposal — {proposal.get('customer', '')}",
        date=date,
        customer_name=proposal.get("customer", ""),
        property_address=proposal.get("property", ""),
        hvhz=bool(proposal.get("hvhz", False)),
        scope_lines=lines,
        subtotal=proposal.get("subtotal", "0.00"),
        tax=proposal.get("tax", "0.00"),
        contract_total=proposal.get("contract_total", "0.00"),
        draws=proposal.get("payment_schedule", {}).get("draws", []),
        expiry_days=int(proposal.get("expiry_days", 30)),
        tenant_name=tenant_name,
        tenant_license=tenant_license,
        tc_summary_bullets=tc_summary_bullets,
        marketing_appendix=marketing_appendix,
    )


DEFAULT_PROPOSAL_TEMPLATE_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body { font-family: Arial, Helvetica, sans-serif; color:#222; font-size:12px; margin:36px; }
  .head { display:flex; justify-content:space-between; align-items:flex-start; }
  .tenant { font-size:16px; font-weight:bold; }
  h1 { font-size:20px; margin:0; }
  table { width:100%; border-collapse:collapse; margin-top:14px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #ddd; }
  td.amt, th.amt { text-align:right; }
  .sub { color:#666; font-size:11px; }
  .excl { color:#888; }
  tfoot .total { font-weight:bold; font-size:14px; border-top:2px solid #222; }
  .hvhz { background:#fff4d6; padding:6px 10px; margin-top:10px; border:1px solid #e6cf7a; }
</style></head><body>
  <div class="head">
    <div><div class="tenant">{{ tenant.name }}</div>
      {% if tenant.license %}<div class="sub">Lic# {{ tenant.license }}</div>{% endif %}</div>
    <div style="text-align:right"><h1>{{ proposal.title }}</h1><div class="sub">{{ proposal.date }}</div></div>
  </div>

  <p style="margin-top:14px"><b>Prepared for:</b> {{ customer.name }}<br>
     <b>Property:</b> {{ property.address }}</p>
  {% if proposal.hvhz %}<div class="hvhz"><b>HVHZ:</b> This scope complies with the Florida
     Building Code High-Velocity Hurricane Zone requirements.</div>{% endif %}

  <table>
    <thead><tr><th>Scope</th><th>Squares</th>
      <th class="amt">$/Square</th><th class="amt">Amount</th></tr></thead>
    <tbody>
      {% for ln in scope_lines %}
      <tr class="{{ 'excl' if ln.excluded else '' }}">
        <td>{{ ln.description }}</td><td>{{ ln.squares }}</td>
        <td class="amt">{% if ln.unit_price %}${{ ln.unit_price }}{% endif %}</td>
        <td class="amt">${{ ln.line_total }}{% if ln.excluded %} <span class="sub">(not in total)</span>{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
    <tfoot>
      <tr><td colspan="3" class="amt">Subtotal</td><td class="amt">${{ proposal.subtotal }}</td></tr>
      <tr><td colspan="3" class="amt">Taxes</td><td class="amt">${{ proposal.tax }}</td></tr>
      <tr><td colspan="3" class="amt total">CONTRACT TOTAL</td><td class="amt total">${{ proposal.total }}</td></tr>
    </tfoot>
  </table>

  <h3 style="margin-top:18px">Payment schedule</h3>
  <table>
    <thead><tr><th>#</th><th>Milestone</th><th class="amt">%</th><th class="amt">Amount</th></tr></thead>
    <tbody>
      {% for d in draws %}
      <tr><td>{{ d.sequence }}</td><td>{{ d.label }}</td>
        <td class="amt">{% if d.pct is not none %}{{ d.pct }}%{% else %}Balance{% endif %}</td>
        <td class="amt">${{ d.amount }}</td></tr>
      {% endfor %}
    </tbody>
  </table>

  <p class="sub" style="margin-top:14px">This proposal is valid for {{ proposal.expiry_days }} days
     from the date above. Florida roofing services are not subject to sales tax.</p>

  {% if tc_summary_bullets %}
  <h3>Terms &amp; Conditions — plain-language summary</h3>
  <ul>{% for b in tc_summary_bullets %}<li>{{ b }}</li>{% endfor %}</ul>
  {% endif %}
  {% if marketing_appendix %}<div style="margin-top:24px">{{ marketing_appendix }}</div>{% endif %}
</body></html>
"""
