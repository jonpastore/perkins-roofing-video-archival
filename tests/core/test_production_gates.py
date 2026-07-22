"""Tests for core/production_gates.py — pure evaluation, 100% branch coverage."""
from core.production_gates import evaluate_gates, summary

BASE_FACTS = {
    "email_send_mode": "live",
    "wp_user_set": True,
    "wp_app_pwd_set": True,
    "wp_is_staging": False,
    "rls_enforceable": True,
    "dmarc_policy": "reject",
    "missing_secrets": [],
    "integration_statuses": [{"integration": "resend", "status": "healthy"}],
    "capture_configured": True,
    "search_indexing_enabled": True,
    "indexnow_key_set": True,
    "google_indexing_creds_set": True,
}


def _gate(facts, gate_id):
    gates = evaluate_gates(facts)
    matches = [g for g in gates if g.id == gate_id]
    assert len(matches) == 1
    return matches[0]


def test_all_ok_gives_ready_summary():
    gates = evaluate_gates(BASE_FACTS)
    assert len(gates) == 8
    assert all(g.state == "ok" for g in gates)
    s = summary(gates)
    assert s == {"ok": 8, "warn": 0, "blocker": 0, "total": 8, "ready": True}


# ── email_mode ──────────────────────────────────────────────────────────────

def test_email_mode_live_ok():
    g = _gate({**BASE_FACTS, "email_send_mode": "live"}, "email_mode")
    assert g.state == "ok"


def test_email_mode_test_warns():
    g = _gate({**BASE_FACTS, "email_send_mode": "test"}, "email_mode")
    assert g.state == "warn"
    assert "test allowlist" in g.detail
    assert "EMAIL_SEND_MODE=live" in g.remediation


# ── wordpress ───────────────────────────────────────────────────────────────

def test_wordpress_missing_user_blocks():
    g = _gate({**BASE_FACTS, "wp_user_set": False}, "wordpress")
    assert g.state == "blocker"


def test_wordpress_missing_pwd_blocks():
    g = _gate({**BASE_FACTS, "wp_app_pwd_set": False}, "wordpress")
    assert g.state == "blocker"


def test_wordpress_staging_warns():
    g = _gate({**BASE_FACTS, "wp_is_staging": True}, "wordpress")
    assert g.state == "warn"
    assert "#317" in g.detail


def test_wordpress_prod_ok():
    g = _gate(BASE_FACTS, "wordpress")
    assert g.state == "ok"


# ── rls_security ────────────────────────────────────────────────────────────

def test_rls_not_enforceable_blocks():
    g = _gate({**BASE_FACTS, "rls_enforceable": False}, "rls_security")
    assert g.state == "blocker"
    assert "migration 0018 step 7" in g.remediation


def test_rls_enforceable_ok():
    g = _gate(BASE_FACTS, "rls_security")
    assert g.state == "ok"


# ── dmarc ───────────────────────────────────────────────────────────────────

def test_dmarc_reject_ok():
    g = _gate({**BASE_FACTS, "dmarc_policy": "reject"}, "dmarc")
    assert g.state == "ok"


def test_dmarc_quarantine_warns():
    g = _gate({**BASE_FACTS, "dmarc_policy": "quarantine"}, "dmarc")
    assert g.state == "warn"


def test_dmarc_none_warns():
    g = _gate({**BASE_FACTS, "dmarc_policy": "none"}, "dmarc")
    assert g.state == "warn"


def test_dmarc_unknown_warns():
    g = _gate({**BASE_FACTS, "dmarc_policy": None}, "dmarc")
    assert g.state == "warn"


# ── secrets_present ─────────────────────────────────────────────────────────

def test_secrets_missing_blocks():
    g = _gate({**BASE_FACTS, "missing_secrets": ["resend-api-key", "db-password"]}, "secrets_present")
    assert g.state == "blocker"
    assert "resend-api-key" in g.detail
    assert "db-password" in g.detail


def test_secrets_none_missing_ok():
    g = _gate(BASE_FACTS, "secrets_present")
    assert g.state == "ok"


# ── integrations ────────────────────────────────────────────────────────────

def test_integrations_broken_blocks():
    facts = {**BASE_FACTS, "integration_statuses": [{"integration": "wordpress", "status": "broken"}]}
    g = _gate(facts, "integrations")
    assert g.state == "blocker"
    assert "wordpress" in g.detail


def test_integrations_unconfigured_warns():
    facts = {**BASE_FACTS, "integration_statuses": [{"integration": "tiktok", "status": "unconfigured"}]}
    g = _gate(facts, "integrations")
    assert g.state == "warn"
    assert "tiktok" in g.detail


def test_integrations_all_healthy_ok():
    facts = {**BASE_FACTS, "integration_statuses": [{"integration": "resend", "status": "healthy"}]}
    g = _gate(facts, "integrations")
    assert g.state == "ok"


def test_integrations_empty_list_ok():
    g = _gate({**BASE_FACTS, "integration_statuses": []}, "integrations")
    assert g.state == "ok"


# ── oauth_capture ───────────────────────────────────────────────────────────

def test_oauth_capture_not_configured_warns():
    g = _gate({**BASE_FACTS, "capture_configured": False}, "oauth_capture")
    assert g.state == "warn"


def test_oauth_capture_configured_ok():
    g = _gate(BASE_FACTS, "oauth_capture")
    assert g.state == "ok"


# ── search_indexing ─────────────────────────────────────────────────────────

def test_search_indexing_disabled_warns():
    g = _gate({**BASE_FACTS, "search_indexing_enabled": False}, "search_indexing")
    assert g.state == "warn"
    assert "turned off" in g.detail
    assert "SEARCH_INDEXING_ENABLED=true" in g.remediation


def test_search_indexing_enabled_but_unconfigured_warns():
    facts = {**BASE_FACTS, "indexnow_key_set": False, "google_indexing_creds_set": False}
    g = _gate(facts, "search_indexing")
    assert g.state == "warn"
    assert "not configured" in g.detail


def test_search_indexing_missing_indexnow_only_warns():
    g = _gate({**BASE_FACTS, "indexnow_key_set": False}, "search_indexing")
    assert g.state == "warn"
    assert "INDEXNOW_KEY missing" in g.detail


def test_search_indexing_missing_google_only_warns():
    g = _gate({**BASE_FACTS, "google_indexing_creds_set": False}, "search_indexing")
    assert g.state == "warn"
    assert "GOOGLE_INDEXING_CREDENTIALS missing" in g.detail


def test_search_indexing_fully_configured_ok():
    g = _gate(BASE_FACTS, "search_indexing")
    assert g.state == "ok"


# ── summary ─────────────────────────────────────────────────────────────────

def test_summary_counts_and_ready_false_on_blocker():
    facts = {**BASE_FACTS, "rls_enforceable": False, "dmarc_policy": "none"}
    gates = evaluate_gates(facts)
    s = summary(gates)
    assert s["blocker"] == 1
    assert s["warn"] == 1
    assert s["ok"] == 6
    assert s["total"] == 8
    assert s["ready"] is False
