"""JB4 invoicing engine — pure, no I/O.

The money core of the Knowify-replacement billing lane. All math is Decimal,
quantized to cents with ROUND_HALF_UP. No DB calls, no side effects — the ORM
layer (Invoice/InvoiceLine/MilestoneDraw/JobBillingEvent) persists what these
functions compute.

Invariants (validated against the 7 golden Knowify invoices #413–#652):
- A draw invoice bills ONE milestone %; every scope line on it carries that same %.
- draw_amount(scope_value) = scope_value * milestone_pct  (per-scope).
- Discounts are NEGATIVE lines at the SAME milestone %.
- Tax is $0 (FL roofing services exempt) — the field exists for out-of-state tenants.
- Invoice numbers are a per-tenant monotonic sequence continuing the live Knowify
  max (Perkins next = 18733); issuance is last_number + 1.
- Invoice/payment status is DERIVED from the append-only ledger, never overwritten.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_Q2 = Decimal("0.01")


def _money(v: Any) -> Decimal:
    return (v if isinstance(v, Decimal) else Decimal(str(v))).quantize(_Q2, rounding=ROUND_HALF_UP)


def draw_amount(scope_value: Decimal | str | float, pct: Decimal | str | float) -> Decimal:
    """Dollar amount drawn on one scope at a milestone percentage."""
    sv = scope_value if isinstance(scope_value, Decimal) else Decimal(str(scope_value))
    p = pct if isinstance(pct, Decimal) else Decimal(str(pct))
    return (sv * p).quantize(_Q2, rounding=ROUND_HALF_UP)


def build_invoice_lines(
    scopes: list[dict],
    pct: Decimal | str | float,
    discounts: list[dict] | None = None,
) -> list[dict]:
    """Build the line items for a single milestone-draw invoice.

    scopes:    [{description, scope_value, scope_id?}] — the per-scope CONTRACT value.
    pct:       the milestone percentage being billed (e.g. 0.30).
    discounts: [{description, amount}] — amount POSITIVE; billed as a negative line
               at the same pct (matching Knowify's "Discount / 30% completed / -$X").

    Every returned line carries the same milestone_pct. unit_price == subtotal
    (qty is always 1 — lines are lump-sum scope packages, not unit-priced).
    """
    p = pct if isinstance(pct, Decimal) else Decimal(str(pct))
    lines: list[dict] = []
    order = 0
    for s in scopes:
        amt = draw_amount(s["scope_value"], p)
        lines.append({
            "line_type": "scope",
            "description": s.get("description", ""),
            "scope_id": s.get("scope_id"),
            "milestone_pct": str(p),
            "quantity": "1",
            "unit_price": str(amt),
            "subtotal": str(amt),
            "sort_order": order,
        })
        order += 1
    for d in (discounts or []):
        amt = -draw_amount(d["amount"], p)  # negative, same pct
        lines.append({
            "line_type": "discount",
            "description": d.get("description", "Discount"),
            "scope_id": None,
            "milestone_pct": str(p),
            "quantity": "1",
            "unit_price": str(amt),
            "subtotal": str(amt),
            "sort_order": order,
        })
        order += 1
    return lines


def aggregate_invoice(lines: list[dict], credit: Decimal | str | float = "0") -> dict:
    """Sum lines into subtotal / tax / credit / total. Tax is always $0 (FL roofing)."""
    subtotal = sum((Decimal(ln["subtotal"]) for ln in lines), Decimal("0"))
    tax = Decimal("0.00")
    cr = _money(credit)
    total = _money(subtotal + tax - cr)
    return {
        "subtotal": str(_money(subtotal)),
        "tax_amount": str(tax),
        "credit_amount": str(cr),
        "total": str(total),
    }


def next_invoice_number(last_number: int) -> int:
    """Next per-tenant invoice number. The caller holds the counter row FOR UPDATE
    and persists this back atomically. Perkins seeds last_number=18732 → 18733."""
    return int(last_number) + 1


# ---------------------------------------------------------------------------
# Ledger-derived status (append-only events are the source of truth)
# ---------------------------------------------------------------------------

def derive_invoice_status(events: list[dict], total: Decimal | str | float) -> str:
    """Derive an invoice's status from its append-only billing events — never stored
    mutably. events: [{event_type, payload}] where payment_recorded payloads carry
    {"amount": "..."}. Precedence: voided > paid > partially_paid > sent > draft.
    """
    tot = _money(total)
    types = {e.get("event_type") for e in events}
    if "invoice_voided" in types:
        return "voided"
    paid = sum(
        (_money(e.get("payload", {}).get("amount", "0"))
         for e in events if e.get("event_type") == "payment_recorded"),
        Decimal("0"),
    )
    if paid >= tot and tot > 0:
        return "paid"
    if paid > 0:
        return "partially_paid"
    if "invoice_sent" in types or "invoice_issued" in types:
        return "sent"
    return "draft"
