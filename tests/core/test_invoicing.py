"""Unit tests for the pure JB4 invoicing money engine."""
from decimal import Decimal

import pytest

from core.invoicing import (
    _money,
    aggregate_invoice,
    allocate_draw,
    build_invoice_lines,
    derive_invoice_status,
    draw_amount,
    next_invoice_number,
)


def test_money_rounds_half_up():
    assert _money("1.005") == Decimal("1.01")


def test_draw_amount_requires_fraction_pct():
    assert draw_amount("1000", "0.30") == Decimal("300.00")
    with pytest.raises(ValueError, match="int percent"):
        draw_amount("1000", "30")
    with pytest.raises(ValueError):
        draw_amount("1000", "0")


def test_allocate_draw_largest_remainder_sums_to_contract_level_target():
    # Each raw scope draw is 0.3333..., target rounds to $1.00. Largest-remainder
    # allocates the final cent to one line so customer-visible lines reconcile exactly.
    got = allocate_draw(["1", "1", "1"], Decimal("0.333333"))
    assert got == [Decimal("0.33"), Decimal("0.33"), Decimal("0.34")]
    assert sum(got) == Decimal("1.00")


def test_build_invoice_lines_allocates_scopes_and_discounts_at_same_pct():
    lines = build_invoice_lines(
        scopes=[
            {"description": "Roof A", "scope_value": "1000.00", "scope_id": 10},
            {"description": "Roof B", "scope_value": "500.00", "scope_id": 11},
        ],
        pct="0.30",
        discounts=[{"description": "Promo", "amount": "100.00"}],
    )
    assert [ln["sort_order"] for ln in lines] == [0, 1, 2]
    assert lines[0]["line_type"] == "scope"
    assert lines[0]["subtotal"] == "300.00"
    assert lines[1]["subtotal"] == "150.00"
    assert lines[2]["line_type"] == "discount"
    assert lines[2]["subtotal"] == "-30.00"
    assert all(ln["quantity"] == "1" for ln in lines)


def test_build_invoice_lines_allows_no_scopes_or_discounts():
    assert build_invoice_lines([], "0.30") == []


def test_aggregate_invoice_sums_subtotal_tax_credit_total():
    agg = aggregate_invoice(
        [{"subtotal": "300.00"}, {"subtotal": "-30.00"}],
        credit="10.005",
    )
    assert agg == {
        "subtotal": "270.00",
        "tax_amount": "0.00",
        "credit_amount": "10.01",
        "total": "259.99",
    }


def test_next_invoice_number_is_arithmetic_only():
    assert next_invoice_number(18732) == 18733
    assert next_invoice_number("18732") == 18733


def test_derive_status_draft_sent_partial_paid_paid_and_duplicate_idempotency():
    assert derive_invoice_status([], "100") == "draft"
    assert derive_invoice_status([{"event_type": "invoice_issued"}], "100") == "sent"
    events = [
        {"event_type": "invoice_issued"},
        {"event_type": "payment_recorded", "payload": {"amount": "40.00"}, "idempotency_key": "p1"},
        # duplicate key must not double-count
        {"event_type": "payment_recorded", "payload": {"amount": "40.00"}, "idempotency_key": "p1"},
    ]
    assert derive_invoice_status(events, "100") == "partially_paid"
    events.append({"event_type": "payment_recorded", "payload": {"amount": "60.00"}, "idempotency_key": "p2"})
    assert derive_invoice_status(events, "100") == "paid"


def test_derive_status_voided_precedence_and_refund_owed_case():
    assert derive_invoice_status([{"event_type": "invoice_voided"}], "100") == "voided"
    events = [
        {"event_type": "invoice_voided"},
        {"event_type": "payment_recorded", "payload": {"amount": "1.00"}},
    ]
    assert derive_invoice_status(events, "100") == "voided_after_payment"


def test_derive_status_zero_total_not_paid_without_payment():
    assert derive_invoice_status([{"event_type": "invoice_issued"}], "0") == "sent"
