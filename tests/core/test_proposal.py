"""TDD tests for core/proposal.py — 100% coverage target.

Covers:
  - generate_accept_token: length, charset, uniqueness
  - new_version: field computation, root_id logic, forbidden prev statuses
  - supersede: delegates to transition correctly
  - transition: legal/illegal transitions, terminal states
  - validate_snapshot: required keys, hash, floors, deposit_policy, tiers
  - compute_deposit: percent / fixed / none modes, pre-frozen amount
  - capture_selection: tier validation, options shape, status guard
"""
import pytest

from core.proposal import (
    TERMINAL_STATUSES,
    VALID_STATUSES,
    InvalidTransitionError,
    SnapshotError,
    capture_selection,
    compute_deposit,
    generate_accept_token,
    new_version,
    supersede,
    transition,
    validate_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_snapshot(**overrides) -> dict:
    base = {
        "pricing_config_hash": "abc123",
        "sent_at_iso": "2026-07-09T00:00:00Z",
        "roof_type": "dimensional_shingle",
        "num_squares": 28.0,
        "tiers": {
            "good":   {"label": "Good",   "total": 18400.00, "line_items": []},
            "better": {"label": "Better", "total": 21200.00, "line_items": []},
            "best":   {"label": "Best",   "total": 24800.00, "line_items": []},
        },
        "deposit_policy": {"mode": "percent", "value": 50, "instructions": "Check payable to PR"},
        "floors": {"min_profit_pct": 13, "min_profit_plus_oh_pct": 33},
        "estimator_version": "1.0.0",
    }
    base.update(overrides)
    return base


def _proposal(status="draft", id=1, root_id=None, version_number=1) -> dict:
    return {
        "id": id,
        "root_id": root_id,
        "parent_id": None,
        "version_number": version_number,
        "status": status,
    }


# ---------------------------------------------------------------------------
# generate_accept_token
# ---------------------------------------------------------------------------

class TestGenerateAcceptToken:
    def test_length_is_86(self):
        token = generate_accept_token()
        assert len(token) == 86

    def test_url_safe_charset(self):
        """Token must contain only URL-safe base64 chars (A-Z a-z 0-9 - _)."""
        import re
        token = generate_accept_token()
        assert re.fullmatch(r"[A-Za-z0-9\-_]+", token), f"Unexpected chars in token: {token}"

    def test_no_padding(self):
        token = generate_accept_token()
        assert "=" not in token

    def test_uniqueness_1000(self):
        tokens = {generate_accept_token() for _ in range(1000)}
        assert len(tokens) == 1000, "Collision detected among 1000 tokens"

    def test_entropy_bytes(self):
        """Verify 86 chars of URL-safe base64 encode 64 bytes (512 bits)."""
        import base64
        token = generate_accept_token()
        # re-pad to decode
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        assert len(raw) == 64


# ---------------------------------------------------------------------------
# transition (status machine)
# ---------------------------------------------------------------------------

class TestTransition:
    def test_draft_to_sent(self):
        p = _proposal("draft")
        result = transition(p, "sent")
        assert result == {"status": "sent"}

    def test_sent_to_viewed(self):
        p = _proposal("sent")
        result = transition(p, "viewed")
        assert result == {"status": "viewed"}

    def test_sent_to_accepted(self):
        p = _proposal("sent")
        assert transition(p, "accepted") == {"status": "accepted"}

    def test_sent_to_declined(self):
        p = _proposal("sent")
        assert transition(p, "declined") == {"status": "declined"}

    def test_sent_to_superseded(self):
        p = _proposal("sent")
        assert transition(p, "superseded") == {"status": "superseded"}

    def test_viewed_to_accepted(self):
        p = _proposal("viewed")
        assert transition(p, "accepted") == {"status": "accepted"}

    def test_viewed_to_revision_requested(self):
        p = _proposal("viewed")
        assert transition(p, "revision_requested") == {"status": "revision_requested"}

    def test_revision_requested_to_superseded(self):
        p = _proposal("revision_requested")
        assert transition(p, "superseded") == {"status": "superseded"}

    def test_illegal_draft_to_accepted(self):
        p = _proposal("draft")
        with pytest.raises(InvalidTransitionError, match="draft.*accepted"):
            transition(p, "accepted")

    def test_illegal_accepted_to_anything(self):
        p = _proposal("accepted")
        with pytest.raises(InvalidTransitionError):
            transition(p, "sent")

    def test_illegal_declined_to_anything(self):
        p = _proposal("declined")
        with pytest.raises(InvalidTransitionError):
            transition(p, "viewed")

    def test_illegal_superseded_to_anything(self):
        p = _proposal("superseded")
        with pytest.raises(InvalidTransitionError):
            transition(p, "sent")

    def test_invalid_target_status(self):
        p = _proposal("draft")
        with pytest.raises(InvalidTransitionError, match="not a valid"):
            transition(p, "flying")

    def test_unknown_current_status(self):
        p = _proposal("unknown_status")
        with pytest.raises(InvalidTransitionError, match="unknown current status"):
            transition(p, "sent")

    def test_terminal_statuses_set(self):
        assert TERMINAL_STATUSES == frozenset({"accepted", "declined", "superseded"})

    def test_valid_statuses_complete(self):
        expected = {"draft", "sent", "viewed", "accepted", "declined", "revision_requested", "superseded"}
        assert VALID_STATUSES == frozenset(expected)


# ---------------------------------------------------------------------------
# supersede
# ---------------------------------------------------------------------------

class TestSupersede:
    def test_sent_to_superseded(self):
        p = _proposal("sent")
        assert supersede(p) == {"status": "superseded"}

    def test_viewed_to_superseded(self):
        p = _proposal("viewed")
        assert supersede(p) == {"status": "superseded"}

    def test_revision_requested_to_superseded(self):
        p = _proposal("revision_requested")
        assert supersede(p) == {"status": "superseded"}

    def test_draft_cannot_be_superseded(self):
        p = _proposal("draft")
        with pytest.raises(InvalidTransitionError):
            supersede(p)


# ---------------------------------------------------------------------------
# new_version
# ---------------------------------------------------------------------------

class TestNewVersion:
    def test_version_number_increments(self):
        prev = _proposal("sent", id=10, root_id=10, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert result["version_number"] == 2

    def test_parent_id_points_to_prev(self):
        prev = _proposal("sent", id=10, root_id=10, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert result["parent_id"] == 10

    def test_root_id_from_prev_root_id(self):
        prev = _proposal("sent", id=10, root_id=5, version_number=2)
        result = new_version(prev, "staff@example.com")
        assert result["root_id"] == 5

    def test_root_id_falls_back_to_prev_id_when_none(self):
        """v1 has root_id=None; new version's root_id should be prev.id (the v1 root)."""
        prev = _proposal("sent", id=10, root_id=None, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert result["root_id"] == 10

    def test_new_version_status_is_draft(self):
        prev = _proposal("sent", id=10, root_id=10, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert result["status"] == "draft"

    def test_new_version_has_fresh_token(self):
        prev = _proposal("sent", id=10, root_id=10, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert len(result["accept_token"]) == 86

    def test_new_token_differs_each_call(self):
        prev = _proposal("sent", id=10, root_id=10, version_number=1)
        t1 = new_version(prev, "staff@example.com")["accept_token"]
        t2 = new_version(prev, "staff@example.com")["accept_token"]
        assert t1 != t2

    def test_created_by_set(self):
        prev = _proposal("sent", id=10, root_id=10, version_number=1)
        result = new_version(prev, "alice@example.com")
        assert result["created_by"] == "alice@example.com"

    def test_draft_prev_raises(self):
        prev = _proposal("draft", id=1)
        with pytest.raises(InvalidTransitionError, match="draft"):
            new_version(prev, "staff@example.com")

    def test_accepted_prev_raises(self):
        prev = _proposal("accepted", id=1)
        with pytest.raises(InvalidTransitionError):
            new_version(prev, "staff@example.com")

    def test_superseded_prev_raises(self):
        prev = _proposal("superseded", id=1)
        with pytest.raises(InvalidTransitionError):
            new_version(prev, "staff@example.com")

    def test_viewed_prev_allowed(self):
        prev = _proposal("viewed", id=5, root_id=5, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert result["version_number"] == 2

    def test_revision_requested_prev_allowed(self):
        prev = _proposal("revision_requested", id=5, root_id=5, version_number=1)
        result = new_version(prev, "staff@example.com")
        assert result["version_number"] == 2


# ---------------------------------------------------------------------------
# validate_snapshot
# ---------------------------------------------------------------------------

class TestValidateSnapshot:
    def test_valid_snapshot_passes(self):
        validate_snapshot(_minimal_snapshot())  # must not raise

    def test_missing_pricing_config_hash_raises(self):
        snap = _minimal_snapshot()
        del snap["pricing_config_hash"]
        with pytest.raises(SnapshotError, match="pricing_config_hash"):
            validate_snapshot(snap)

    def test_empty_pricing_config_hash_raises(self):
        snap = _minimal_snapshot(pricing_config_hash="")
        with pytest.raises(SnapshotError, match="pricing_config_hash"):
            validate_snapshot(snap)

    def test_missing_sent_at_iso_raises(self):
        snap = _minimal_snapshot()
        del snap["sent_at_iso"]
        with pytest.raises(SnapshotError, match="sent_at_iso"):
            validate_snapshot(snap)

    def test_missing_floors_raises(self):
        snap = _minimal_snapshot()
        del snap["floors"]
        with pytest.raises(SnapshotError, match="floors"):
            validate_snapshot(snap)

    def test_missing_floor_key_min_profit_pct(self):
        snap = _minimal_snapshot()
        snap["floors"] = {"min_profit_plus_oh_pct": 33}
        with pytest.raises(SnapshotError, match="min_profit_pct"):
            validate_snapshot(snap)

    def test_missing_floor_key_min_profit_plus_oh_pct(self):
        snap = _minimal_snapshot()
        snap["floors"] = {"min_profit_pct": 13}
        with pytest.raises(SnapshotError, match="min_profit_plus_oh_pct"):
            validate_snapshot(snap)

    def test_missing_deposit_policy_raises(self):
        snap = _minimal_snapshot()
        del snap["deposit_policy"]
        with pytest.raises(SnapshotError, match="deposit_policy"):
            validate_snapshot(snap)

    def test_deposit_policy_missing_mode_raises(self):
        snap = _minimal_snapshot()
        snap["deposit_policy"] = {"value": 50}
        with pytest.raises(SnapshotError, match="mode"):
            validate_snapshot(snap)

    def test_deposit_policy_missing_value_raises(self):
        snap = _minimal_snapshot()
        snap["deposit_policy"] = {"mode": "percent"}
        with pytest.raises(SnapshotError, match="value"):
            validate_snapshot(snap)

    def test_empty_tiers_raises(self):
        snap = _minimal_snapshot(tiers={})
        with pytest.raises(SnapshotError, match="tiers"):
            validate_snapshot(snap)

    def test_missing_tiers_key_raises(self):
        snap = _minimal_snapshot()
        del snap["tiers"]
        with pytest.raises(SnapshotError, match="tiers"):
            validate_snapshot(snap)

    def test_missing_roof_type_raises(self):
        snap = _minimal_snapshot()
        del snap["roof_type"]
        with pytest.raises(SnapshotError, match="roof_type"):
            validate_snapshot(snap)

    def test_missing_estimator_version_raises(self):
        snap = _minimal_snapshot()
        del snap["estimator_version"]
        with pytest.raises(SnapshotError, match="estimator_version"):
            validate_snapshot(snap)


# ---------------------------------------------------------------------------
# compute_deposit
# ---------------------------------------------------------------------------

class TestComputeDeposit:
    def test_percent_mode_computes_from_good_tier(self):
        snap = _minimal_snapshot()
        # 50% of 18400 (good tier baseline) = 9200
        result = compute_deposit(snap)
        assert result["mode"] == "percent"
        assert result["amount"] == 9200.0

    def test_fixed_mode(self):
        snap = _minimal_snapshot(deposit_policy={"mode": "fixed", "value": 2500, "instructions": "Wire"})
        result = compute_deposit(snap)
        assert result["amount"] == 2500.0
        assert result["mode"] == "fixed"

    def test_none_mode_returns_zero(self):
        snap = _minimal_snapshot(deposit_policy={"mode": "none", "value": 0})
        result = compute_deposit(snap)
        assert result["amount"] == 0.0

    def test_pre_frozen_amount_trusted(self):
        """If snapshot already has deposit_policy.amount, return it as-is."""
        snap = _minimal_snapshot(
            deposit_policy={"mode": "percent", "value": 50, "amount": 9200.0, "instructions": ""}
        )
        result = compute_deposit(snap)
        assert result["amount"] == 9200.0

    def test_instructions_returned(self):
        snap = _minimal_snapshot()
        result = compute_deposit(snap)
        assert result["instructions"] == "Check payable to PR"

    def test_no_tiers_gives_zero_for_percent(self):
        snap = _minimal_snapshot(
            tiers={"good": {"label": "Good", "line_items": []}},  # no 'total' key
            deposit_policy={"mode": "percent", "value": 50},
        )
        result = compute_deposit(snap)
        assert result["amount"] == 0.0

    def test_percent_25_of_21200(self):
        snap = _minimal_snapshot(
            deposit_policy={"mode": "percent", "value": 25, "instructions": ""},
        )
        result = compute_deposit(snap)
        assert result["amount"] == 4600.0  # 25% of 18400


# ---------------------------------------------------------------------------
# capture_selection
# ---------------------------------------------------------------------------

class TestCaptureSelection:
    def test_valid_sent_proposal(self):
        p = _proposal("sent")
        result = capture_selection(p, "good")
        assert result["selected_tier"] == "good"
        assert result["selected_options"] == []

    def test_valid_viewed_proposal(self):
        p = _proposal("viewed")
        result = capture_selection(p, "better")
        assert result["selected_tier"] == "better"

    def test_best_tier(self):
        p = _proposal("viewed")
        result = capture_selection(p, "best")
        assert result["selected_tier"] == "best"

    def test_legacy_snapshot_tier(self):
        p = _proposal("viewed")
        p["quote_snapshot"] = _minimal_snapshot(
            tiers={"legacy": {"label": "Knowify Quote", "total": 42905.0}},
        )
        result = capture_selection(p, "legacy")
        assert result["selected_tier"] == "legacy"

    def test_rejects_tier_absent_from_snapshot(self):
        p = _proposal("viewed")
        p["quote_snapshot"] = _minimal_snapshot(
            tiers={"legacy": {"label": "Knowify Quote", "total": 42905.0}},
        )
        with pytest.raises(ValueError, match="not a valid tier"):
            capture_selection(p, "good")

    def test_invalid_tier(self):
        p = _proposal("sent")
        with pytest.raises(ValueError, match="not a valid tier"):
            capture_selection(p, "premium")

    def test_draft_proposal_raises(self):
        p = _proposal("draft")
        with pytest.raises(InvalidTransitionError):
            capture_selection(p, "good")

    def test_accepted_proposal_raises(self):
        p = _proposal("accepted")
        with pytest.raises(InvalidTransitionError):
            capture_selection(p, "good")

    def test_options_with_id_and_qty(self):
        p = _proposal("sent")
        opts = [{"id": "ridge_vent", "qty": 42}, {"id": "drip_edge", "qty": 10}]
        result = capture_selection(p, "good", opts)
        assert len(result["selected_options"]) == 2
        assert result["selected_options"][0]["id"] == "ridge_vent"

    def test_string_options_from_spa_are_normalized(self):
        p = _proposal("sent")
        p["quote_snapshot"] = _minimal_snapshot(
            optional_items=[{"id": "ridge_vent", "label": "Ridge Vent", "qty": 42}]
        )
        result = capture_selection(p, "good", ["ridge_vent"])
        assert result["selected_options"] == [{"id": "ridge_vent", "qty": 42}]

    def test_option_missing_id_raises(self):
        p = _proposal("sent")
        with pytest.raises(ValueError, match="'id'"):
            capture_selection(p, "good", [{"qty": 5}])

    def test_option_missing_qty_raises(self):
        p = _proposal("sent")
        with pytest.raises(ValueError, match="'qty'"):
            capture_selection(p, "good", [{"id": "ridge_vent"}])

    def test_none_options_treated_as_empty_list(self):
        p = _proposal("sent")
        result = capture_selection(p, "good", None)
        assert result["selected_options"] == []
