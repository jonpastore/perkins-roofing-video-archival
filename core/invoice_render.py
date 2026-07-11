"""Invoice HTML renderer (core — pure, no I/O).

Renders a Jinja2 HTML invoice against an InvoiceRenderContext, mirroring
core/proposal_render.py (sandboxed env, silent-undefined, autoescape). The
adapters/gotenberg.html_to_pdf() call that turns this HTML into a PDF — and the
"Friends of Perkins" marketing-appendix concat — happen at the API layer.

Layout follows the reverse-engineered Knowify invoice anatomy
(docs/superpowers/specs/tim-docs/invoices.md): BILL TO + JOB, a 3-column
INVOICE DATE / PLEASE PAY / DUE DATE block, line items each with a
"X% completed" sub-label, and a Subtotal / Taxes ($0) / Total footer.

    render_invoice_html(template_html, ctx) -> str
    invoice_context(...) -> InvoiceRenderContext   # from the JB4 engine output
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import jinja2

from core.proposal_render import _SilentUndefined  # reuse the hardened undefined


@dataclass
class InvoiceRenderContext:
    invoice_number: str
    invoice_date: str
    due_date: str
    please_pay: str            # bolded current draw amount (== total)
    customer_name: str
    bill_to_address: str
    job_name: str
    lines: list[dict[str, Any]]  # [{description, pct_label, amount}]
    subtotal: str
    taxes: str
    credit: str
    total: str
    tenant_name: str
    tenant_license: str | None = None
    comments: str | None = None
    footer_text: str | None = field(default=None)


def _build_jinja_env() -> jinja2.Environment:
    from jinja2.sandbox import SandboxedEnvironment
    return SandboxedEnvironment(autoescape=True, undefined=_SilentUndefined, keep_trailing_newline=True)


_ENV = _build_jinja_env()


def _ctx_to_dict(ctx: InvoiceRenderContext) -> dict[str, Any]:
    return {
        "invoice": {
            "number": ctx.invoice_number,
            "date": ctx.invoice_date,
            "due_date": ctx.due_date,
            "please_pay": ctx.please_pay,
            "subtotal": ctx.subtotal,
            "taxes": ctx.taxes,
            "credit": ctx.credit,
            "total": ctx.total,
            "comments": ctx.comments or "",
        },
        "customer": {"name": ctx.customer_name, "bill_to": ctx.bill_to_address},
        "job": {"name": ctx.job_name},
        "lines": ctx.lines,
        "tenant": {"name": ctx.tenant_name, "license": ctx.tenant_license or ""},
        "footer_text": ctx.footer_text or "",
    }


def render_invoice_html(template_html: str, ctx: InvoiceRenderContext) -> str:
    """Render a (tenant-editable, so SANDBOXED) invoice template against the context."""
    return _ENV.from_string(template_html).render(**_ctx_to_dict(ctx))


def _pct_label(milestone_pct: str) -> str:
    """'0.30' -> '30% completed' (Knowify's per-line sub-label)."""
    pct = (Decimal(milestone_pct) * 100).quantize(Decimal("1"))
    return f"{pct}% completed"


def invoice_context(
    *,
    invoice_number: int | str,
    invoice_date: str,
    due_date: str,
    customer_name: str,
    bill_to_address: str,
    job_name: str,
    engine_lines: list[dict],
    totals: dict,
    tenant_name: str,
    tenant_license: str | None = None,
    comments: str | None = None,
    footer_text: str | None = None,
) -> InvoiceRenderContext:
    """Build an InvoiceRenderContext from the JB4 invoicing engine output.

    engine_lines: core.invoicing.build_invoice_lines(...) output.
    totals:       core.invoicing.aggregate_invoice(...) output.
    """
    lines = [
        {
            "description": ln["description"],
            "pct_label": _pct_label(ln["milestone_pct"]) if ln.get("milestone_pct") else "",
            "amount": ln["subtotal"],
        }
        for ln in engine_lines
    ]
    return InvoiceRenderContext(
        invoice_number=f"#{invoice_number}",
        invoice_date=invoice_date,
        due_date=due_date,
        please_pay=totals["total"],
        customer_name=customer_name,
        bill_to_address=bill_to_address,
        job_name=job_name,
        lines=lines,
        subtotal=totals["subtotal"],
        taxes=totals["tax_amount"],
        credit=totals["credit_amount"],
        total=totals["total"],
        tenant_name=tenant_name,
        tenant_license=tenant_license,
        comments=comments,
        footer_text=footer_text,
    )


DEFAULT_INVOICE_TEMPLATE_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body { font-family: Arial, Helvetica, sans-serif; color:#222; font-size:12px; margin:36px; }
  .head { display:flex; justify-content:space-between; align-items:flex-start; }
  .tenant { font-size:16px; font-weight:bold; }
  h1 { font-size:22px; margin:0 0 4px; }
  table { width:100%; border-collapse:collapse; margin-top:16px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #ddd; }
  td.amt, th.amt { text-align:right; }
  .datebox td { border:1px solid #ccc; text-align:center; }
  .pay { font-weight:bold; }
  .sub { color:#666; font-size:11px; }
  tfoot td { border:none; }
  tfoot .total { font-weight:bold; font-size:14px; border-top:2px solid #222; }
</style></head><body>
  <div class="head">
    <div>
      <div class="tenant">{{ tenant.name }}</div>
      {% if tenant.license %}<div class="sub">Lic# {{ tenant.license }}</div>{% endif %}
    </div>
    <div style="text-align:right"><h1>Invoice {{ invoice.number }}</h1></div>
  </div>

  <div style="display:flex; justify-content:space-between; margin-top:16px;">
    <div><b>BILL TO</b><br>{{ customer.name }}<br>{{ customer.bill_to }}</div>
    <div><b>JOB</b><br>{{ job.name }}</div>
  </div>

  <table class="datebox" style="width:60%; margin-top:16px;">
    <tr><th>INVOICE DATE</th><th>PLEASE PAY</th><th>DUE DATE</th></tr>
    <tr><td>{{ invoice.date }}</td><td class="pay">${{ invoice.please_pay }}</td><td>{{ invoice.due_date }}</td></tr>
  </table>

  <table>
    <thead><tr><th>Description</th><th>Hrs/Qty</th>
      <th class="amt">Rate/Price</th><th class="amt">Subtotal</th></tr></thead>
    <tbody>
      {% for ln in lines %}
      <tr>
        <td>{{ ln.description }}{% if ln.pct_label %}<div class="sub">{{ ln.pct_label }}</div>{% endif %}</td>
        <td>1</td>
        <td class="amt">${{ ln.amount }}</td>
        <td class="amt">${{ ln.amount }}</td>
      </tr>
      {% endfor %}
    </tbody>
    <tfoot>
      <tr><td colspan="3" class="amt">Subtotal</td><td class="amt">${{ invoice.subtotal }}</td></tr>
      <tr><td colspan="3" class="amt">Taxes</td><td class="amt">${{ invoice.taxes }}</td></tr>
      {% if invoice.credit and invoice.credit != "0.00" %}
      <tr><td colspan="3" class="amt">Credit</td><td class="amt">-${{ invoice.credit }}</td></tr>{% endif %}
      <tr><td colspan="3" class="amt total">TOTAL</td><td class="amt total">${{ invoice.total }}</td></tr>
    </tfoot>
  </table>

  {% if invoice.comments %}<p class="sub">{{ invoice.comments }}</p>{% endif %}
  {% if footer_text %}<p class="sub" style="margin-top:24px">{{ footer_text }}</p>{% endif %}
</body></html>
"""

