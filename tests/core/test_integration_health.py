import pytest

from core.integration_health import (
    TRANSIENT_FAILURE_THRESHOLD,
    ProbeResult,
    next_status,
    should_alert,
)

# --- next_status: ok resets counter ---

def test_ok_probe_from_broken_resets_to_healthy():
    status, failures = next_status(ProbeResult(ok=True), "broken", 5)
    assert (status, failures) == ("healthy", 0)


def test_ok_probe_with_expiring_flag_reports_expiring():
    status, failures = next_status(ProbeResult(ok=True, expiring=True), "healthy", 0)
    assert (status, failures) == ("expiring", 0)


# --- hard auth failure: breaks on FIRST occurrence, from any prior status ---

def test_hard_auth_failure_breaks_immediately_from_healthy():
    status, failures = next_status(
        ProbeResult(ok=False, hard_auth_failure=True), "healthy", 0
    )
    assert (status, failures) == ("broken", 1)


def test_hard_auth_failure_breaks_immediately_from_unconfigured():
    status, failures = next_status(
        ProbeResult(ok=False, hard_auth_failure=True), "unconfigured", 0
    )
    assert (status, failures) == ("broken", 1)


def test_hard_auth_failure_increments_counter_when_already_broken():
    status, failures = next_status(
        ProbeResult(ok=False, hard_auth_failure=True), "broken", 2
    )
    assert (status, failures) == ("broken", 3)


# --- transient failure: stays at prev_status until Nth consecutive failure ---

def test_transient_failure_below_threshold_preserves_prev_status():
    status, failures = next_status(ProbeResult(ok=False, error="503"), "healthy", 0)
    assert (status, failures) == ("healthy", 1)

    status, failures = next_status(ProbeResult(ok=False, error="503"), "healthy", 1)
    assert (status, failures) == ("healthy", 2)


def test_transient_failure_reaches_threshold_breaks():
    status, failures = next_status(
        ProbeResult(ok=False, error="503"), "healthy", TRANSIENT_FAILURE_THRESHOLD - 1
    )
    assert (status, failures) == ("broken", TRANSIENT_FAILURE_THRESHOLD)


def test_transient_failure_past_threshold_stays_broken_without_realarm_state():
    # broken stays broken on continued failure — no special-casing needed, counter
    # keeps climbing but should_alert (below) is what prevents the re-alert.
    status, failures = next_status(ProbeResult(ok=False, error="timeout"), "broken", 5)
    assert (status, failures) == ("broken", 6)


# --- should_alert: transition-only truth table ---

@pytest.mark.parametrize(
    "prev_status,new_status,expected",
    [
        ("healthy", "broken", True),
        ("expiring", "broken", True),
        ("unconfigured", "broken", True),
        ("broken", "broken", False),
        ("healthy", "healthy", False),
        ("broken", "healthy", False),
        ("healthy", "expiring", False),
    ],
)
def test_should_alert_truth_table(prev_status, new_status, expected):
    assert should_alert(prev_status, new_status) is expected


# --- ValueError cases ---

def test_next_status_rejects_unknown_prev_status():
    with pytest.raises(ValueError):
        next_status(ProbeResult(ok=True), "not_a_status", 0)


def test_next_status_rejects_negative_failures():
    with pytest.raises(ValueError):
        next_status(ProbeResult(ok=True), "healthy", -1)


def test_should_alert_rejects_unknown_status():
    with pytest.raises(ValueError):
        should_alert("healthy", "not_a_status")
    with pytest.raises(ValueError):
        should_alert("not_a_status", "healthy")
