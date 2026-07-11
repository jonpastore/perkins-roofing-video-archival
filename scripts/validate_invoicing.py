#!/usr/bin/env python3
"""Behavioral gate for the JB4 invoicing engine (core/invoicing.py + core/milestones.py).

Validates against the 7 golden Knowify invoices (#413–#652) AND the production path
the customer is billed on (per-scope `build_invoice_lines`, not just contract-level
`draw_amount` — R2 C1). Also: same-pct multi-scope, negative discounts, $0 tax,
per-tenant numbering, ledger status (incl. void-after-payment + dup-payment dedup),
the fraction-vs-int pct guard, and the HIGH-2 milestone snapshot immutability.

    PYTHONPATH=. python scripts/validate_invoicing.py   # exit non-zero on any failure
"""
from decimal import Decimal

from core.invoicing import (
    aggregate_invoice,
    allocate_draw,
    build_invoice_lines,
    derive_invoice_status,
    draw_amount,
    next_invoice_number,
)
from core.milestones import (
    draw_amounts_from_total,
    freeze_schedule,
    schedule_from_quote_snapshot,
    verify_schedule_hash,
)
from core.proposal_gen import compose_proposal, freeze_quote_snapshot

# The 7 golden Knowify invoices: (label, contract_total, pct, drawn_amount).
GOLDEN = [
    ("meharg #413",      "26370.00",  "0.30", "7911.00"),
    ("mazzeo #573",      "45501.75",  "0.30", "13650.53"),
    ("thompson #601",    "50601.88",  "0.30", "15180.56"),
    ("butterworth #608", "42529.50",  "0.30", "12758.85"),
    ("malooley #611",    "127263.35", "0.30", "38179.01"),
    ("allen #639",       "32943.20",  "0.30", "9882.96"),
    ("palmer #652",      "45790.00",  "0.15", "6868.50"),
]


def _split3(total: Decimal) -> list[str]:
    """Split a total into 3 awkward scope values (that individually round badly)."""
    a = (total / 3).quantize(Decimal("0.01"))
    b = (total / 7).quantize(Decimal("0.01"))
    return [str(a), str(b), str(total - a - b)]


def main() -> None:
    # (a) Golden draw math + (C1) the PER-SCOPE billed path reconciles to the golden.
    print("Golden invoices — contract-level draw AND per-scope line sum both == drawn:")
    for label, total, pct, expected in GOLDEN:
        assert draw_amount(total, pct) == Decimal(expected), f"{label}: contract-level draw"
        # C1: split into scopes, bill via build_invoice_lines, reconcile the SUBTOTAL.
        scopes = [{"description": f"scope {i}", "scope_value": v}
                  for i, v in enumerate(_split3(Decimal(total)))]
        agg = aggregate_invoice(build_invoice_lines(scopes, pct))
        assert Decimal(agg["subtotal"]) == Decimal(expected), \
            f"{label}: per-scope lines sum {agg['subtotal']} != drawn {expected}"
        print(f"  {label:20} {total:>11} x {pct}: contract & per-scope both = {expected}  PASS")

    # (C1) Largest-remainder prevents the classic drift (naive per-scope would give 90.06).
    alloc = allocate_draw(["100.05", "100.05", "100.05"], "0.30")
    assert sum(alloc) == draw_amount("300.15", "0.30") == Decimal("90.05"), f"alloc drift: {sum(alloc)}"
    print(f"  largest-remainder: 3 x (100.05 @30%) sums to {sum(alloc)} (not 90.06)  PASS")

    # (b) Multi-scope: same pct on every line, negative discount, $0 tax.
    scopes = [{"description": "Flat", "scope_value": "20000.00"},
              {"description": "Flat rear", "scope_value": "12000.00"},
              {"description": "Tile", "scope_value": "9500.00"},
              {"description": "Stucco", "scope_value": "1029.50"}]
    lines = build_invoice_lines(scopes, "0.30", discounts=[{"description": "Discount", "amount": "300.00"}])
    assert all(ln["milestone_pct"] == "0.30" for ln in lines), "all lines share the pct"
    disc = next(ln for ln in lines if ln["line_type"] == "discount")
    assert Decimal(disc["subtotal"]) == -draw_amount("300.00", "0.30"), "discount negative, same pct"
    agg = aggregate_invoice(lines)
    assert agg["tax_amount"] == "0.00", "FL roofing tax must be $0"
    scope_sum = draw_amount("42529.50", "0.30")  # sum of the 4 scope values @30%, allocated
    assert Decimal(agg["subtotal"]) == scope_sum - draw_amount("300.00", "0.30"), "subtotal reconciles"
    print(f"  multi-scope 4 lines @30% + negative discount, $0 tax, subtotal={agg['subtotal']}  PASS")

    # (M2) fraction-vs-int pct guard: passing an int percent (30) must RAISE.
    for bad in (30, "30", Decimal("1.5"), 0):
        try:
            draw_amount("100.00", bad)
            raise AssertionError(f"draw_amount accepted bad pct {bad!r}")
        except ValueError:
            pass
    print("  pct guard: int-percent / >1 / 0 raise ValueError  PASS")

    # (c) Per-tenant numbering continues the live sequence.
    n, seq = 18732, []
    for _ in range(5):
        n = next_invoice_number(n)
        seq.append(n)
    assert seq == [18733, 18734, 18735, 18736, 18737], "monotonic +1 from 18732"
    print(f"  numbering: 18732 -> {seq}  PASS")

    # (d) Ledger status incl. M1 void-after-payment + dup-payment dedup.
    T = "10000.00"
    assert derive_invoice_status([{"event_type": "invoice_issued"}], T) == "sent"
    assert derive_invoice_status(
        [{"event_type": "invoice_issued"}, {"event_type": "payment_recorded", "payload": {"amount": "4000.00"}}], T
    ) == "partially_paid"
    assert derive_invoice_status(
        [{"event_type": "invoice_issued"}, {"event_type": "payment_recorded", "payload": {"amount": "10000.00"}}], T
    ) == "paid"
    # dup payment (same idempotency_key) counted ONCE → still partially_paid, not paid
    dup = [{"event_type": "payment_recorded", "idempotency_key": "p1", "payload": {"amount": "6000.00"}},
           {"event_type": "payment_recorded", "idempotency_key": "p1", "payload": {"amount": "6000.00"}}]
    assert derive_invoice_status(dup, T) == "partially_paid", "duplicate payment must count once"
    # M1: void AFTER full payment must not hide the money
    assert derive_invoice_status(
        [{"event_type": "payment_recorded", "payload": {"amount": "10000.00"}}, {"event_type": "invoice_voided"}], T
    ) == "voided_after_payment"
    assert derive_invoice_status([{"event_type": "invoice_voided"}], T) == "voided"
    print("  ledger: sent/partial/paid, dup-dedup, void vs voided_after_payment  PASS")

    # (e) HIGH-2 + M3: schedule frozen from the ISSUED proposal; hash actually pins content.
    proposal = compose_proposal({"customer": "T", "property": "1 St",
                                 "scopes": [{"roof_system": "tile", "tier": "PROTECTOR", "squares": 40}]})
    snapshot, _ = freeze_quote_snapshot(proposal)
    schedule = schedule_from_quote_snapshot(snapshot)
    assert len(schedule) == 4, "standard schedule has 4 draws"
    total = Decimal(proposal["contract_total"])
    recomputed = draw_amounts_from_total(schedule, total)
    assert sum(Decimal(d["amount"]) for d in recomputed) == total.quantize(Decimal("0.01")), \
        "draws sum EXACTLY to the contract total"
    frozen, h = freeze_schedule(schedule)
    assert verify_schedule_hash(frozen, h), "unmutated frozen schedule verifies"
    # real tamper test (M3): mutate a draw amount → hash must FAIL to verify
    import copy
    tampered = copy.deepcopy(frozen)
    tampered[0]["amount"] = str(Decimal(tampered[0]["amount"]) + Decimal("1000.00"))
    assert not verify_schedule_hash(tampered, h), "tampered schedule must fail hash verification"
    print(f"  milestone schedule frozen + hash-pinned (verify passes, tamper fails; {h[:12]}…)  PASS")

    print("\nOK — invoicing invariants hold: 7 golden draws via the PER-SCOPE billed path, "
          "allocation (no drift), pct guard, numbering, ledger (M1 void/dedup), HIGH-2+M3.")


if __name__ == "__main__":
    main()
