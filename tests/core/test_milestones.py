"""Unit tests for the pure JB4 milestone-schedule engine."""
from decimal import Decimal

import pytest

from core.milestones import (
    draw_amounts_from_total,
    freeze_schedule,
    schedule_from_quote_snapshot,
    verify_schedule_hash,
)


def _snapshot():
    return {
        "payment_schedule": {
            "variant": "standard",
            "draws": [
                {"sequence": 1, "label": "Deposit", "pct": 30, "amount": "300.00"},
                {"sequence": 2, "label": "Dry-in", "pct": 30, "amount": "300.00"},
                {"sequence": 3, "label": "Balance", "pct": None, "amount": "400.00"},
            ],
        }
    }


def test_schedule_from_quote_snapshot_extracts_draws_only():
    got = schedule_from_quote_snapshot(_snapshot())
    assert got == [
        {"sequence": 1, "label": "Deposit", "pct": 30, "amount": "300.00"},
        {"sequence": 2, "label": "Dry-in", "pct": 30, "amount": "300.00"},
        {"sequence": 3, "label": "Balance", "pct": None, "amount": "400.00"},
    ]


def test_schedule_from_quote_snapshot_requires_payment_block():
    with pytest.raises(KeyError):
        schedule_from_quote_snapshot({})


def test_draw_amounts_from_total_recomputes_balance_exactly():
    schedule = schedule_from_quote_snapshot(_snapshot())
    got = draw_amounts_from_total(schedule, Decimal("1000.01"))
    assert got == [
        {"sequence": 1, "label": "Deposit", "pct": 30, "amount": "300.00"},
        {"sequence": 2, "label": "Dry-in", "pct": 30, "amount": "300.00"},
        {"sequence": 3, "label": "Balance", "pct": None, "amount": "400.01"},
    ]
    assert sum(Decimal(d["amount"]) for d in got) == Decimal("1000.01")


def test_draw_amounts_rounds_half_up():
    schedule = [{"sequence": 1, "label": "Half", "pct": 50}, {"sequence": 2, "label": "Balance", "pct": None}]
    got = draw_amounts_from_total(schedule, "0.05")
    assert got[0]["amount"] == "0.03"
    assert got[1]["amount"] == "0.02"


def test_freeze_schedule_deep_copies_and_hash_verifies():
    schedule = schedule_from_quote_snapshot(_snapshot())
    frozen, h = freeze_schedule(schedule)
    assert frozen == schedule
    assert frozen is not schedule
    schedule[0]["amount"] = "999.99"
    assert frozen[0]["amount"] == "300.00"
    assert verify_schedule_hash(frozen, h)


def test_verify_schedule_hash_detects_tamper():
    frozen, h = freeze_schedule(schedule_from_quote_snapshot(_snapshot()))
    frozen[0]["amount"] = "999.99"
    assert not verify_schedule_hash(frozen, h)
