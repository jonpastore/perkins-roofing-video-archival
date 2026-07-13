"""JB4 invoicing engine — pure money math, no I/O.

The money core of the Knowify-replacement billing lane. All math is Decimal,
quantized to cents with ROUND_HALF_UP. No DB calls, no side effects — the ORM/API
layer persists what these functions compute.

Invariants (validated against the 7 golden Knowify invoices #413–#652):
- A draw invoice bills ONE milestone %; every scope line on it carries that same %.
- Per-scope line draws are ALLOCATED (largest-remainder) so they sum EXACTLY to the
  contract-level draw = round(sum(scope_values) * pct) — no per-scope rounding drift
  (R2 C1). The line total the customer sees reconciles to the penny with the draw.
- Discounts are NEGATIVE lines at the SAME milestone %.
- Tax is $0 (FL roofing services exempt) — the field exists for out-of-state tenants.
- Invoice numbers are a per-tenant monotonic sequence continuing the live Knowify max
  (Perkins next = 18733). `next_invoice_number` is ARITHMETIC ONLY; atomic issuance is
  the API layer's job (see its docstring for the required UPDATE ... RETURNING).
- Invoice/payment status is DERIVED from the append-only ledger, never overwritten;
  duplicate payment events (same idempotency_key) are counted once.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from core.discounts import resolve_discounts

_Q2 = Decimal("0.01")


def _dec(v: Any) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _money(v: Any) -> Decimal:
    return _dec(v).quantize(_Q2, rounding=ROUND_HALF_UP)


def _check_pct(pct: Decimal) -> Decimal:
    """Guard against the fraction-vs-int-percent mixup (R2 M2): pct must be a fraction
    in (0, 1]. Feeding a schedule's int percent (e.g. 30) would 100x the draw."""
    if not (Decimal("0") < pct <= Decimal("1")):
        raise ValueError(f"milestone pct must be a fraction in (0, 1], got {pct} "
                         f"(did you pass an int percent like 30 instead of 0.30?)")
    return pct


def draw_amount(scope_value: Decimal | str | float, pct: Decimal | str | float) -> Decimal:
    """Dollar amount drawn on one scope at a milestone percentage (fraction in (0,1])."""
    return (_dec(scope_value) * _check_pct(_dec(pct))).quantize(_Q2, rounding=ROUND_HALF_UP)


def allocate_draw(scope_values: list[Decimal | str | float], pct: Decimal | str | float) -> list[Decimal]:
    """Largest-remainder (Hamilton) allocation of a milestone draw across scopes.

    Returns per-scope cent amounts that sum EXACTLY to the contract-level draw
    round(sum(values) * pct), so invoice lines never diverge from the draw total by
    rounding (R2 C1). Each scope gets floor(value*pct); the leftover cents go to the
    scopes with the largest fractional remainders.
    """
    p = _check_pct(_dec(pct))
    vals = [_dec(v) for v in scope_values]
    target = (sum(vals) * p).quantize(_Q2, rounding=ROUND_HALF_UP)
    raw = [v * p for v in vals]
    floored = [r.quantize(_Q2, rounding=ROUND_DOWN) for r in raw]
    base = sum(floored, Decimal("0"))
    # leftover cents (>=0: HALF_UP target >= floor sum); at most len(vals)
    cents = int(((target - base) / _Q2).to_integral_value(rounding=ROUND_HALF_UP))
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floored[i], i), reverse=True)
    alloc = list(floored)
    for k in range(min(cents, len(alloc))):
        alloc[order[k]] += _Q2
    return alloc


def build_invoice_lines(
    scopes: list[dict],
    pct: Decimal | str | float,
    discounts: list[dict] | None = None,
) -> list[dict]:
    """Build the line items for a single milestone-draw invoice.

    scopes:    [{description, scope_value, scope_id?}] — the per-scope CONTRACT value.
    pct:       the milestone fraction being billed (e.g. 0.30).
    discounts: [{description, amount}] — amount POSITIVE; billed as a negative line at
               the same pct (Knowify's "Discount / 30% completed / -$X").

    Scope draws are largest-remainder allocated so the scope lines sum EXACTLY to
    round(sum(scope_values) * pct). unit_price == subtotal (qty is always 1).
    """
    p = _check_pct(_dec(pct))
    lines: list[dict] = []
    order = 0
    scope_amounts = allocate_draw([s["scope_value"] for s in scopes], p) if scopes else []
    for s, amt in zip(scopes, scope_amounts):
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
    discount_base = sum((_dec(s["scope_value"]) for s in scopes), Decimal("0.00"))
    for d in resolve_discounts(discounts or [], discount_base):
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
    """ARITHMETIC ONLY: last + 1. NOT safe to call read-modify-write under concurrency.

    The API layer MUST issue numbers atomically with a single statement:
        UPDATE tenant_invoice_counters SET last_number = last_number + 1
        WHERE tenant_id = :t RETURNING last_number
    (or SELECT ... FOR UPDATE), so two concurrent draws can't both read 18732 and
    collide on the UNIQUE (tenant_id, invoice_number) constraint (R2 C2).
    """
    return int(last_number) + 1


# ---------------------------------------------------------------------------
# Ledger-derived status (append-only events are the source of truth)
# ---------------------------------------------------------------------------

def derive_invoice_status(events: list[dict], total: Decimal | str | float) -> str:
    """Derive an invoice's status from its append-only billing events — never stored
    mutably. events: [{event_type, payload, idempotency_key?}]; payment_recorded
    payloads carry {"amount": "..."}. Duplicate payment events (same non-null
    idempotency_key) count ONCE. Precedence: a void with money already paid surfaces
    as 'voided_after_payment' (refund owed) so paid dollars aren't hidden (R2 M1).
    """
    tot = _money(total)
    types = {e.get("event_type") for e in events}

    seen: set = set()
    paid = Decimal("0")
    for e in events:
        if e.get("event_type") != "payment_recorded":
            continue
        key = e.get("idempotency_key")
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        paid += _money(e.get("payload", {}).get("amount", "0"))

    if "invoice_voided" in types:
        return "voided_after_payment" if paid > 0 else "voided"
    if paid >= tot and tot > 0:
        return "paid"
    if paid > 0:
        return "partially_paid"
    if "invoice_sent" in types or "invoice_issued" in types:
        return "sent"
    return "draft"
