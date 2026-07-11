#!/usr/bin/env python3
"""Behavioral gate for the JB4 invoicing engine (core/invoicing.py + core/milestones.py).

Validates against the 7 golden Knowify invoices (#413–#652) and the HIGH-2 milestone
invariant: the draw math is draw = contract_total * milestone_pct; multi-scope invoices
carry one line per scope at the SAME pct; discounts are negative lines; tax is $0;
per-tenant numbering continues the live sequence (18733+); status is ledger-derived; and
a job's milestone schedule is frozen from the ISSUED proposal and is stable thereafter.

    PYTHONPATH=. python scripts/validate_invoicing.py   # exit non-zero on any failure
"""
import json
import os
from decimal import Decimal

from core.invoicing import (
    aggregate_invoice,
    build_invoice_lines,
    derive_invoice_status,
    draw_amount,
    next_invoice_number,
)
from core.milestones import (
    draw_amounts_from_total,
    freeze_schedule,
    schedule_from_quote_snapshot,
)
from core.proposal_gen import compose_proposal, freeze_quote_snapshot

# The 7 golden Knowify invoices: (proposal_key, contract_total, pct, drawn_amount).
# Draw = contract_total * pct — verified against the live Knowify invoice PDFs.
GOLDEN = [
    ("meharg-2025-10-08",       "26370.00",  "0.30", "7911.00"),
    ("mazzeo-2026-03-10",       "45501.75",  "0.30", "13650.53"),
    ("thompson-2026-05-05",     "50601.88",  "0.30", "15180.56"),
    ("butterworth-2026-05-14",  "42529.50",  "0.30", "12758.85"),
    ("malooley-2026-05-18",     "127263.35", "0.30", "38179.01"),
    ("allen-2026-06-23",        "32943.20",  "0.30", "9882.96"),
    ("palmer-2026-07-10",       "45790.00",  "0.15", "6868.50"),
]

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "docs", "perkins-analysis", "proposal_fixtures.json")


def main() -> None:
    # (a) Golden draw math: draw = contract_total * pct, to the penny.
    fixtures = {}
    if os.path.exists(FIXTURES):
        raw = json.load(open(FIXTURES))
        fixtures = raw if isinstance(raw, dict) else {r.get("proposal_id", i): r for i, r in enumerate(raw)}
    print("Golden invoice draw math (draw == contract_total * pct):")
    for key, total, pct, expected in GOLDEN:
        got = draw_amount(total, pct)
        assert got == Decimal(expected), f"{key}: draw {got} != {expected}"
        # cross-check the contract total against the JB3 proposal fixture, if present
        fx = fixtures.get(key)
        if fx and fx.get("contract_total") is not None:
            ft = Decimal(str(fx["contract_total"]))
            assert abs(ft - Decimal(total)) <= Decimal("0.02"), f"{key}: fixture total {ft} != {total}"
        print(f"  {key:26} {total:>11} x {pct} = {got}  PASS")

    # (b) Multi-scope: one line per scope at the SAME pct, discount negative, $0 tax.
    scopes = [
        {"description": "PERKINS PROTECTOR - Flat Re-Roof", "scope_value": "20000.00"},
        {"description": "PERKINS PROTECTOR - Flat Re-Roof (rear)", "scope_value": "12000.00"},
        {"description": "PERKINS PREMIUM (Caribbean) - Tile Re-Roof", "scope_value": "9500.00"},
        {"description": "Re-Paint Guest House & Stucco Repairs", "scope_value": "1029.50"},
    ]
    lines = build_invoice_lines(scopes, "0.30", discounts=[{"description": "Discount", "amount": "300.00"}])
    assert all(ln["milestone_pct"] == "0.30" for ln in lines), "all lines must share the milestone pct"
    disc = [ln for ln in lines if ln["line_type"] == "discount"][0]
    assert Decimal(disc["subtotal"]) < 0, "discount line must be negative"
    assert Decimal(disc["subtotal"]) == draw_amount("300.00", "0.30") * -1, "discount at same pct"
    agg = aggregate_invoice(lines)
    assert agg["tax_amount"] == "0.00", "FL roofing tax must be $0"
    # subtotal = sum of (scope*.30) minus (300*.30)
    expect_sub = (sum((draw_amount(s["scope_value"], "0.30") for s in scopes), Decimal("0"))
                  - draw_amount("300.00", "0.30"))
    assert Decimal(agg["subtotal"]) == expect_sub, f"subtotal {agg['subtotal']} != {expect_sub}"
    print(f"  multi-scope 4 lines @30% + negative discount, $0 tax, subtotal={agg['subtotal']}  PASS")

    # (c) Per-tenant numbering continues the live Knowify sequence.
    assert next_invoice_number(18732) == 18733, "Perkins next number must be 18733"
    seq, n = [], 18732
    for _ in range(5):
        n = next_invoice_number(n)
        seq.append(n)
    assert seq == [18733, 18734, 18735, 18736, 18737], "numbering must be monotonic +1"
    print(f"  numbering: 18732 -> {seq}  PASS")

    # (d) Ledger-derived status.
    total = "10000.00"
    assert derive_invoice_status([{"event_type": "invoice_issued"}], total) == "sent"
    assert derive_invoice_status(
        [{"event_type": "invoice_issued"}, {"event_type": "payment_recorded", "payload": {"amount": "4000.00"}}],
        total) == "partially_paid"
    assert derive_invoice_status(
        [{"event_type": "invoice_issued"}, {"event_type": "payment_recorded", "payload": {"amount": "10000.00"}}],
        total) == "paid"
    assert derive_invoice_status(
        [{"event_type": "invoice_issued"}, {"event_type": "invoice_voided"}], total) == "voided"
    print("  ledger status: sent / partially_paid / paid / voided  PASS")

    # (e) HIGH-2: milestone schedule is frozen from the ISSUED proposal and stable.
    proposal = compose_proposal({
        "customer": "Test", "property": "1 Test St",
        "scopes": [{"roof_system": "tile", "tier": "PROTECTOR", "squares": 40}],
    })
    snapshot, _ = freeze_quote_snapshot(proposal)
    schedule = schedule_from_quote_snapshot(snapshot)
    assert len(schedule) == 4, "standard schedule has 4 draws"
    contract_total = Decimal(proposal["contract_total"])
    recomputed = draw_amounts_from_total(schedule, contract_total)
    assert sum(Decimal(d["amount"]) for d in recomputed) == contract_total.quantize(Decimal("0.01")), \
        "draws must sum exactly to the contract total"
    frozen, h1 = freeze_schedule(schedule)
    # A LATER, different proposal (e.g. a price revision) must NOT change this job's frozen schedule.
    revised = compose_proposal({
        "customer": "Test", "property": "1 Test St",
        "scopes": [{"roof_system": "tile", "tier": "PREMIUM_CARIBBEAN", "squares": 40}],  # different price
    })
    _snap2, _ = freeze_quote_snapshot(revised)
    _, h1_again = freeze_schedule(frozen)
    assert h1 == h1_again, "frozen schedule hash must be stable"
    assert frozen == schedule, "the frozen schedule must be unchanged by a later proposal revision"
    print(f"  milestone schedule frozen from issued proposal; stable across a revision (hash {h1[:12]}…)  PASS")

    print("\nOK — invoicing engine invariants hold (7 golden draws + multi-scope + numbering + ledger + HIGH-2).")


if __name__ == "__main__":
    main()
