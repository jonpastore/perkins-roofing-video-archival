"""Pure discount resolution helpers.

UI/API may accept reusable discount presets as either a fixed amount or a percent.
Money paths should not carry live percentages into snapshots/invoices; resolve every
percent into an explicit dollar amount at composition time, then existing negative-line
paths can stay deterministic.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_Q2 = Decimal("0.01")


def _dec(value: Any) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid discount value: {value!r}") from exc


def _fmt(value: Decimal) -> str:
    return str(value.quantize(_Q2, rounding=ROUND_HALF_UP))


def resolve_discounts(discounts: list[dict] | None, base_amount: Decimal | str | float) -> list[dict]:
    """Return discount rows with explicit positive dollar ``amount`` strings.

    Input forms:
    - legacy amount: ``{description, amount}``
    - typed amount: ``{description, discount_type: "amount", value}``
    - percent: ``{description, discount_type: "percent", value}`` or ``{percent}``

    Percent values are 0..100 and are applied to ``base_amount``. Returned rows keep
    ``discount_type``/``value`` for audit/preset UX while normalizing ``amount`` for
    existing proposal/invoice negative-line math.
    """
    base = _dec(base_amount)
    if base < 0:
        raise ValueError("discount base_amount cannot be negative")

    result: list[dict] = []
    for raw in discounts or []:
        description = (raw.get("description") or "Discount").strip() or "Discount"
        dtype = (raw.get("discount_type") or ("percent" if raw.get("percent") is not None else "amount")).lower()
        value = raw.get("value")
        if value is None:
            value = raw.get("percent") if dtype == "percent" else raw.get("amount")
        if value is None:
            continue

        dec_value = _dec(value)
        if dtype == "percent":
            if not (Decimal("0") <= dec_value <= Decimal("100")):
                raise ValueError("percent discount must be between 0 and 100")
            amount = (base * dec_value / Decimal("100")).quantize(_Q2, rounding=ROUND_HALF_UP)
        elif dtype == "amount":
            if dec_value < 0:
                raise ValueError("amount discount cannot be negative")
            amount = dec_value.quantize(_Q2, rounding=ROUND_HALF_UP)
        else:
            raise ValueError("discount_type must be 'amount' or 'percent'")

        result.append({
            "description": description,
            "amount": _fmt(amount),
            "discount_type": dtype,
            "value": str(value),
        })
    return result
