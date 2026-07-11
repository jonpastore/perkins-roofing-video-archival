"""JB4 milestone-schedule engine — pure, no I/O.

Load-bearing invariant (plan HIGH-2 / Principle 1): a job's milestone/draw schedule
is snapshotted from the ISSUED proposal's FROZEN quote_snapshot — never the live
ProposalTemplate and never a draft. A template edit or a later proposal revision must
NOT retro-change the draws of an already-scheduled job. So the schedule is frozen a
second time onto the MilestoneSchedule row at creation, with its own hash.
"""
from __future__ import annotations

import copy
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from core.pricing_config import compute_snapshot_hash

_Q2 = Decimal("0.01")


def schedule_from_quote_snapshot(quote_snapshot: dict[str, Any]) -> list[dict]:
    """Extract the ordered draw schedule from an ISSUED proposal's frozen snapshot.

    Reads quote_snapshot["payment_schedule"]["draws"] — the payment block that was
    frozen at proposal send-time. Returns [{sequence, label, pct, amount}] where a
    balance draw has pct=None. Raises KeyError if the snapshot has no payment block
    (a proposal must be issued with a schedule before a job can be scheduled).
    """
    sched = quote_snapshot["payment_schedule"]
    draws = sched["draws"]
    return [
        {
            "sequence": d["sequence"],
            "label": d.get("label", ""),
            "pct": d.get("pct"),          # int percent (e.g. 30) or None for balance
            "amount": d.get("amount"),    # str dollars, precomputed at issue time
        }
        for d in draws
    ]


def draw_amounts_from_total(schedule: list[dict], contract_total: Decimal | str | float) -> list[dict]:
    """Recompute draw dollar amounts from a contract total (validation / re-derivation).

    Each non-balance draw = total * pct/100; the final pct=None draw is the net
    balance so the draws always sum EXACTLY to the contract total (no rounding drift).
    """
    total = (contract_total if isinstance(contract_total, Decimal)
             else Decimal(str(contract_total))).quantize(_Q2, rounding=ROUND_HALF_UP)
    out: list[dict] = []
    running = Decimal("0.00")
    for d in schedule:
        if d.get("pct") is not None:
            amt = (total * Decimal(str(d["pct"])) / Decimal("100")).quantize(_Q2, rounding=ROUND_HALF_UP)
            running += amt
        else:
            amt = (total - running).quantize(_Q2, rounding=ROUND_HALF_UP)
        out.append({"sequence": d["sequence"], "label": d.get("label", ""),
                    "pct": d.get("pct"), "amount": str(amt)})
    return out


def freeze_schedule(schedule: list[dict]) -> tuple[list[dict], str]:
    """Freeze a milestone schedule onto a MilestoneSchedule row with a content hash.

    The returned snapshot is what MilestoneSchedule.milestones_snapshot stores; the
    hash pins it so a later proposal revision / template edit can't mutate this job's
    draws (they'd produce a different hash → tamper-evident).
    """
    frozen = copy.deepcopy(schedule)
    return frozen, compute_snapshot_hash({"draws": frozen})


def verify_schedule_hash(frozen: list[dict], expected_hash: str) -> bool:
    """Recompute a frozen schedule's hash and confirm it matches the stored value.

    The frozen snapshot is only tamper-EVIDENT if a reader actually re-checks it
    (R2 M3). Callers that drive a draw invoice off a MilestoneSchedule row should
    call this on read and refuse to bill if it returns False — a mutated
    milestones_snapshot (direct DB edit or a writer bug) then fails loudly instead
    of silently changing a scheduled job's draws.
    """
    return compute_snapshot_hash({"draws": frozen}) == expected_hash
