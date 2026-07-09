"""Proposal domain logic — pure functions, no I/O.

Public API:
  generate_accept_token() -> str
  new_version(prev, created_by) -> dict
  transition(proposal_dict, target_status) -> dict
  validate_snapshot(snapshot: dict) -> None
  compute_deposit(snapshot: dict) -> dict
  supersede(prev_proposal_dict) -> dict
  capture_selection(proposal_dict, selected_tier, selected_options) -> dict
"""
from __future__ import annotations

import base64
import secrets
from typing import Any

# ---------------------------------------------------------------------------
# Status machine
# ---------------------------------------------------------------------------

# Legal transitions: {from_status: set_of_allowed_to_statuses}
_TRANSITIONS: dict[str, set[str]] = {
    "draft":              {"sent"},
    "sent":               {"viewed", "accepted", "declined", "revision_requested", "superseded"},
    "viewed":             {"accepted", "declined", "revision_requested", "superseded"},
    "accepted":           set(),          # terminal
    "declined":           set(),          # terminal
    "revision_requested": {"superseded"}, # staff creates a revision → old → superseded
    "superseded":         set(),          # terminal
}

VALID_STATUSES: frozenset[str] = frozenset(_TRANSITIONS.keys())

TERMINAL_STATUSES: frozenset[str] = frozenset(
    s for s, nexts in _TRANSITIONS.items() if not nexts
)


class InvalidTransitionError(ValueError):
    """Raised when a status transition is not permitted by the state machine."""


class SnapshotError(ValueError):
    """Raised when a quote_snapshot violates its invariants."""


class DepositPolicyError(ValueError):
    """Raised when the deposit policy in a snapshot is malformed."""


# ---------------------------------------------------------------------------
# Token generation  (TRD §3.5)
# ---------------------------------------------------------------------------

def generate_accept_token() -> str:
    """Return a URL-safe base64 string of 64 random bytes (512 bits, 86 chars).

    Strips trailing '=' padding so the token is exactly 86 characters and
    contains no characters that require percent-encoding in a URL path.
    """
    raw = secrets.token_bytes(64)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Version chain (TRD §3.4)
# ---------------------------------------------------------------------------

def new_version(prev: dict[str, Any], created_by: str) -> dict[str, Any]:
    """Return a dict of fields for a new proposal version based on *prev*.

    The caller is responsible for persisting both the new row and the update
    to *prev* (status → superseded).  This function only computes the field
    values — no DB access.

    *prev* must be a dict with at least: id, root_id, version_number, status.
    status of prev must be in ('sent', 'viewed', 'revision_requested') — you
    cannot revise a draft (edit in-place) or a terminal proposal.
    """
    allowed_prev = {"sent", "viewed", "revision_requested"}
    if prev.get("status") not in allowed_prev:
        raise InvalidTransitionError(
            f"Cannot create a new version from a proposal with status '{prev.get('status')}'. "
            f"Allowed predecessor statuses: {sorted(allowed_prev)}"
        )

    prev_id = prev["id"]
    # root_id: v1 has root_id=None (set to self after insert), so use prev_id as fallback
    root_id = prev.get("root_id") or prev_id

    return {
        "root_id": root_id,
        "parent_id": prev_id,
        "version_number": prev["version_number"] + 1,
        "accept_token": generate_accept_token(),
        "status": "draft",
        "created_by": created_by,
    }


def supersede(prev: dict[str, Any]) -> dict[str, Any]:
    """Return update fields to apply to *prev* when it is superseded.

    The returned dict should be applied as an UPDATE to the existing row.
    """
    return transition(prev, "superseded")


# ---------------------------------------------------------------------------
# Status machine
# ---------------------------------------------------------------------------

def transition(proposal: dict[str, Any], target: str) -> dict[str, Any]:
    """Validate and return an update dict for a status transition.

    Raises InvalidTransitionError if the transition is illegal.
    Returns a dict suitable for applying to the proposal row: {'status': target}.
    """
    if target not in VALID_STATUSES:
        raise InvalidTransitionError(f"'{target}' is not a valid proposal status.")

    current = proposal.get("status")
    if current not in _TRANSITIONS:
        raise InvalidTransitionError(
            f"Proposal has unknown current status '{current}'."
        )

    allowed = _TRANSITIONS[current]
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition proposal from '{current}' to '{target}'. "
            f"Allowed transitions from '{current}': {sorted(allowed) or 'none (terminal)'}"
        )

    return {"status": target}


# ---------------------------------------------------------------------------
# Snapshot validation (TRD §3.3)
# ---------------------------------------------------------------------------

_REQUIRED_SNAPSHOT_KEYS = (
    "pricing_config_hash",
    "sent_at_iso",
    "roof_type",
    "num_squares",
    "tiers",
    "deposit_policy",
    "floors",
    "estimator_version",
)

_REQUIRED_FLOOR_KEYS = ("min_profit_pct", "min_profit_plus_oh_pct")


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    """Raise SnapshotError if the quote_snapshot dict is structurally invalid.

    Checks:
    - Required top-level keys present and non-empty where applicable.
    - pricing_config_hash is a non-empty string.
    - floors carries min_profit_pct and min_profit_plus_oh_pct.
    - deposit_policy has mode + value.
    - tiers dict contains at least one tier.
    """
    for key in _REQUIRED_SNAPSHOT_KEYS:
        if key not in snapshot:
            raise SnapshotError(f"quote_snapshot is missing required key '{key}'.")

    if not snapshot.get("pricing_config_hash"):
        raise SnapshotError("quote_snapshot.pricing_config_hash must be a non-empty string.")

    floors = snapshot.get("floors", {})
    for fk in _REQUIRED_FLOOR_KEYS:
        if fk not in floors:
            raise SnapshotError(f"quote_snapshot.floors is missing '{fk}'.")

    dp = snapshot.get("deposit_policy", {})
    if "mode" not in dp or "value" not in dp:
        raise SnapshotError(
            "quote_snapshot.deposit_policy must have 'mode' and 'value' keys."
        )

    tiers = snapshot.get("tiers", {})
    if not tiers:
        raise SnapshotError("quote_snapshot.tiers must contain at least one tier.")


# ---------------------------------------------------------------------------
# Deposit computation (TRD §3.8)
# ---------------------------------------------------------------------------

def compute_deposit(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute the deposit amount from a frozen quote_snapshot.

    Returns a dict: {mode, value, amount, instructions}.

    deposit_policy envelope keys (from TRD §3.8):
      mode: "percent" | "fixed" | "none"
      value: percent (0-100) or dollar amount
      instructions: optional string

    For "percent": amount = selected_tier_total * (value / 100).
    For "fixed": amount = value.
    For "none": amount = 0.

    If the snapshot carries a pre-computed deposit_policy.amount, that is
    returned as-is (snapshot is authoritative once frozen — no recomputation).
    """
    dp = snapshot.get("deposit_policy", {})
    mode = dp.get("mode", "none")
    value = dp.get("value", 0)
    instructions = dp.get("instructions", "")

    # If already computed and frozen in snapshot, trust it.
    if "amount" in dp:
        return {
            "mode": mode,
            "value": value,
            "amount": dp["amount"],
            "instructions": instructions,
        }

    # Compute from tiers (use the 'good' tier as baseline when not yet selected)
    tiers = snapshot.get("tiers", {})
    baseline_total = 0.0
    for tier_key in ("good", "better", "best"):
        tier = tiers.get(tier_key, {})
        if "total" in tier:
            baseline_total = float(tier["total"])
            break

    if mode == "percent":
        amount = round(baseline_total * value / 100, 2)
    elif mode == "fixed":
        amount = float(value)
    else:
        amount = 0.0

    return {
        "mode": mode,
        "value": value,
        "amount": amount,
        "instructions": instructions,
    }


# ---------------------------------------------------------------------------
# Selection capture (TRD §1.5 — captured at accept time)
# ---------------------------------------------------------------------------

_VALID_TIERS = frozenset({"good", "better", "best"})


def capture_selection(
    proposal: dict[str, Any],
    selected_tier: str,
    selected_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and return the selection fields to apply to a proposal on acceptance.

    *proposal* must have status in ('sent', 'viewed').
    *selected_tier* must be one of 'good', 'better', 'best'.
    *selected_options* is an optional list of optional-item dicts
      (each with at least 'id' and 'qty').

    Returns a dict with: {selected_tier, selected_options} to be merged into
    the proposal row at accept time.
    """
    if proposal.get("status") not in {"sent", "viewed"}:
        raise InvalidTransitionError(
            f"Cannot capture selection on a proposal with status '{proposal.get('status')}'."
        )

    if selected_tier not in _VALID_TIERS:
        raise ValueError(
            f"'{selected_tier}' is not a valid tier. Must be one of: {sorted(_VALID_TIERS)}"
        )

    opts = selected_options if selected_options is not None else []
    for i, item in enumerate(opts):
        if "id" not in item:
            raise ValueError(f"selected_options[{i}] is missing required key 'id'.")
        if "qty" not in item:
            raise ValueError(f"selected_options[{i}] is missing required key 'qty'.")

    return {
        "selected_tier": selected_tier,
        "selected_options": opts,
    }
