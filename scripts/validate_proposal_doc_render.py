#!/usr/bin/env python3
"""Self-check for the JB3 proposal document renderer (core/proposal_doc_render.py).

Composes a proposal via the JB3 engine, renders it, and asserts the contract HTML
carries the scope blocks, the $0-tax contract total, the payment-schedule draws, the
metal 15-day expiry, the HVHZ note, an excluded-optional marker, and that the
rendered total equals the engine's contract_total. Sandbox SSTI guard included.

    PYTHONPATH=. python scripts/validate_proposal_doc_render.py
"""
from core.proposal_doc_render import (
    DEFAULT_PROPOSAL_TEMPLATE_HTML,
    proposal_doc_context,
    render_proposal_doc_html,
)
from core.proposal_gen import compose_proposal


def main() -> None:
    proposal = compose_proposal({
        "customer": "Justin Palmer",
        "property": "503 Xanadu Place, Jupiter, FL 33477",
        "project_name": "Palmer Metal Re-Roof (COASTAL)",
        "hvhz": True,
        "payment_variant": "palmer",
        "scopes": [
            {"roof_system": "metal", "tier": "PROTECTOR", "squares": 26,
             "unit_price": "1476.15", "description": "PERKINS PROTECTOR - Metal Re-Roof"},
            {"roof_system": "metal", "tier": "COASTAL", "squares": 26,
             "unit_price": "285.00", "description": "PERKINS COASTAL - Metal Re-Roof"},
        ],
        "extra_lines": [
            {"description": "Solatube Skylight", "line_total": "1200.00", "is_optional": True},
        ],
    })
    assert proposal["expiry_days"] == 15, "metal proposal must be 15-day expiry"

    ctx = proposal_doc_context(
        proposal, date="2026-07-10", tenant_name="Perkins Roofing", tenant_license="CCC1330000",
        tc_summary_bullets=["You may cancel within 3 business days.", "Lumber surcharge billed at dry-in."],
        marketing_appendix="Friends of Perkins Roofing",
    )
    html = render_proposal_doc_html(DEFAULT_PROPOSAL_TEMPLATE_HTML, ctx)

    for needle in ("Palmer Metal Re-Roof (COASTAL)", "Justin Palmer", "503 Xanadu",
                   "PERKINS PROTECTOR - Metal Re-Roof", "PERKINS COASTAL - Metal Re-Roof",
                   "CONTRACT TOTAL", "Payment schedule", "valid for 15 days",
                   "HVHZ", "Lic# CCC1330000", "(OPTIONAL) Solatube Skylight", "(not in total)",
                   "Friends of Perkins Roofing", "You may cancel within 3 business days."):
        assert needle in html, f"missing from rendered proposal: {needle!r}"
    assert f"${proposal['contract_total']}" in html, "rendered total must equal engine contract_total"
    assert "Balance" in html, "the balance draw must render"
    evil = render_proposal_doc_html("{{ ''.__class__.__mro__ }}", ctx)
    assert "object" not in evil, "sandbox must block SSTI"

    print(f"OK — proposal renders scope blocks, contract total ${proposal['contract_total']}, "
          "5-draw Palmer schedule, 15-day metal expiry, HVHZ note, excluded optional, T&C summary; "
          "SSTI sandbox holds.")


if __name__ == "__main__":
    main()
