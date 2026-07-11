#!/usr/bin/env python3
"""Self-check for the invoice HTML renderer (core/invoice_render.py).

Renders a golden-shaped draw invoice from the JB4 engine output and asserts the
Knowify-anatomy fields are present: invoice number, BILL TO, JOB, the
INVOICE DATE/PLEASE PAY/DUE DATE block, per-line "X% completed" sub-labels, a
negative discount line, $0 taxes, and a TOTAL that equals the engine aggregate.

    PYTHONPATH=. python scripts/validate_invoice_render.py
"""
from decimal import Decimal

from core.invoice_render import (
    DEFAULT_INVOICE_TEMPLATE_HTML,
    invoice_context,
    render_invoice_html,
)
from core.invoicing import aggregate_invoice, build_invoice_lines


def main() -> None:
    scopes = [
        {"description": "PERKINS PROTECTOR - Metal Re-Roof", "scope_value": "38601.88"},
        {"description": "PERKINS PROTECTOR - Flat Re-Roof", "scope_value": "12000.00"},
    ]
    lines = build_invoice_lines(scopes, "0.30", discounts=[{"description": "Discount", "amount": "1000.00"}])
    totals = aggregate_invoice(lines)
    ctx = invoice_context(
        invoice_number=601, invoice_date="2026-05-05", due_date="2026-05-05",
        customer_name="Fred Thompson", bill_to_address="3699 NE 6th Dr, Boca Raton, FL",
        job_name="Thompson Metal Re-Roof", engine_lines=lines, totals=totals,
        tenant_name="Perkins Roofing", tenant_license="CCC1330000",
        footer_text="Friends of Perkins Roofing",
    )
    html = render_invoice_html(DEFAULT_INVOICE_TEMPLATE_HTML, ctx)

    for needle in ("Invoice #601", "BILL TO", "Fred Thompson", "JOB", "Thompson Metal Re-Roof",
                   "INVOICE DATE", "PLEASE PAY", "DUE DATE", "30% completed",
                   "Lic# CCC1330000", "Friends of Perkins Roofing", "Taxes"):
        assert needle in html, f"missing from rendered invoice: {needle!r}"
    assert f"${totals['total']}" in html, "rendered total must equal the engine aggregate"
    assert "$0.00" in html, "FL roofing taxes render as $0.00"
    # discount renders as a negative line
    disc = next(ln for ln in lines if ln["line_type"] == "discount")
    assert Decimal(disc["subtotal"]) < 0 and f"${disc['subtotal']}" in html, "negative discount line renders"
    # SSTI guard: sandbox is active (a template exploit attempt renders empty, doesn't execute)
    evil = render_invoice_html("{{ ''.__class__.__mro__ }}", ctx)
    assert "object" not in evil, "sandboxed env must not expose __class__/__mro__"

    print("OK — invoice renders Knowify anatomy: "
          f"#601, total ${totals['total']}, $0 tax, per-line %-labels, negative discount, license+appendix; "
          "SSTI sandbox holds.")


if __name__ == "__main__":
    main()
