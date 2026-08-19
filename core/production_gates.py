"""Production-readiness gates — pure evaluation, no I/O.

WHY: go-live readiness (email restricted to test allowlist, RLS bypassable,
DMARC not enforced, missing secrets, broken integrations, OAuth self-service
reconnect off) was scattered across health checks, env vars, and tribal
knowledge. This module is the single, testable source of truth for "are we
actually ready to go live" — callers gather the facts (env, DB, DNS, Secret
Manager) and this module turns them into a gate list the UI renders.
WordPress is not a prod target (public site is leaving WP); it is not a gate.
Complements (does not replace) the live connectivity probes in
``api/routes/config.py`` (``GET /config/health-checks``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

GateState = Literal["ok", "warn", "blocker", "unknown"]


@dataclass(frozen=True)
class Gate:
    id: str
    label: str
    category: str
    state: GateState
    detail: str
    remediation: str


def _email_mode_gate(facts: dict[str, Any]) -> Gate:
    mode = facts.get("email_send_mode")
    if mode == "live":
        return Gate(
            id="email_mode",
            label="Outbound email mode",
            category="email",
            state="ok",
            detail="Email send mode is 'live'; real recipients receive mail.",
            remediation="",
        )
    return Gate(
        id="email_mode",
        label="Outbound email mode",
        category="email",
        state="warn",
        detail=(
            "all outbound email is restricted to the test allowlist; real "
            "recipients will NOT receive mail"
        ),
        remediation="set EMAIL_SEND_MODE=live once a verified sending domain is ready.",
    )


def _counts_for_prod(s: dict[str, Any]) -> bool:
    name = str(s.get("integration") or "")
    return bool(name) and not name.startswith("ops_") and name != "wordpress"


def _rls_security_gate(facts: dict[str, Any]) -> Gate:
    if not facts.get("rls_enforceable"):
        return Gate(
            id="rls_security",
            label="Row-level security enforcement",
            category="security",
            state="blocker",
            detail=(
                "the app DB role can bypass RLS — multi-tenant isolation is NOT "
                "enforced"
            ),
            remediation=(
                "apply migration 0018 step 7: ALTER ROLE <app> NOSUPERUSER NOBYPASSRLS"
            ),
        )
    return Gate(
        id="rls_security",
        label="Row-level security enforcement",
        category="security",
        state="ok",
        detail="The app DB role cannot bypass RLS; tenant isolation is enforced.",
        remediation="",
    )


def _dmarc_gate(facts: dict[str, Any]) -> Gate:
    policy = facts.get("dmarc_policy")
    if policy == "reject":
        return Gate(
            id="dmarc",
            label="DMARC policy",
            category="email",
            state="ok",
            detail="DMARC policy is p=reject.",
            remediation="",
        )
    if policy == "quarantine":
        return Gate(
            id="dmarc",
            label="DMARC policy",
            category="email",
            state="warn",
            detail="DMARC policy is p=quarantine; spoofed mail is not fully rejected.",
            remediation="move DMARC to p=reject once monitoring confirms no legitimate senders fail.",
        )
    return Gate(
        id="dmarc",
        label="DMARC policy",
        category="email",
        state="warn",
        detail=f"DMARC policy is {policy!r}; domain spoofing protection is weak or absent.",
        remediation="publish a DMARC TXT record with at least p=quarantine, ideally p=reject.",
    )


def _secrets_present_gate(facts: dict[str, Any]) -> Gate:
    missing = facts.get("missing_secrets") or []
    if missing:
        return Gate(
            id="secrets_present",
            label="Required secrets",
            category="security",
            state="blocker",
            detail=f"missing required secrets: {', '.join(missing)}",
            remediation="set each missing secret's value in Admin Config → Platform Settings.",
        )
    return Gate(
        id="secrets_present",
        label="Required secrets",
        category="security",
        state="ok",
        detail="All required secrets have an enabled version.",
        remediation="",
    )


def _integrations_gate(facts: dict[str, Any]) -> Gate:
    statuses = facts.get("integration_statuses") or []
    broken = [s["integration"] for s in statuses
              if s.get("status") == "broken" and _counts_for_prod(s)]
    unconfigured = [s["integration"] for s in statuses
                    if s.get("status") == "unconfigured" and _counts_for_prod(s)]
    if broken:
        return Gate(
            id="integrations",
            label="Third-party integrations",
            category="integrations",
            state="blocker",
            detail=f"broken integrations: {', '.join(broken)}",
            remediation="reconnect the broken integration(s) from the Connections page.",
        )
    if unconfigured:
        return Gate(
            id="integrations",
            label="Third-party integrations",
            category="integrations",
            state="warn",
            detail=f"unconfigured integrations: {', '.join(unconfigured)}",
            remediation="configure or connect the remaining integration(s) from the Connections page.",
        )
    return Gate(
        id="integrations",
        label="Third-party integrations",
        category="integrations",
        state="ok",
        detail="All integrations are healthy.",
        remediation="",
    )


def _oauth_capture_gate(facts: dict[str, Any]) -> Gate:
    if not facts.get("capture_configured"):
        return Gate(
            id="oauth_capture",
            label="OAuth self-service reconnect",
            category="integrations",
            state="warn",
            detail=(
                "self-service reconnect UI is off until the OAuth state key + "
                "redirect base are configured"
            ),
            remediation="set OAUTH_STATE_HMAC_KEY and OAUTH_REDIRECT_BASE.",
        )
    return Gate(
        id="oauth_capture",
        label="OAuth self-service reconnect",
        category="integrations",
        state="ok",
        detail="OAuth state key and redirect base are configured.",
        remediation="",
    )


def _search_indexing_gate(facts: dict[str, Any]) -> Gate:
    if not facts.get("search_indexing_enabled"):
        return Gate(
            id="search_indexing",
            label="Search-engine indexing",
            category="seo",
            state="warn",
            detail=(
                "search-engine indexing (IndexNow + Google Indexing API) is turned "
                "off — new articles will NOT be auto-submitted for indexing"
            ),
            remediation="set SEARCH_INDEXING_ENABLED=true in Admin Config → Platform Settings.",
        )
    indexnow_ok = facts.get("indexnow_key_set")
    google_ok = facts.get("google_indexing_creds_set")
    if not indexnow_ok and not google_ok:
        return Gate(
            id="search_indexing",
            label="Search-engine indexing",
            category="seo",
            state="warn",
            detail=(
                "enabled but not configured — missing both INDEXNOW_KEY and "
                "GOOGLE_INDEXING_CREDENTIALS; no submissions will fire"
            ),
            remediation=(
                "provision an IndexNow key (+ host the key file at the site root) and a "
                "Google Indexing API service-account (added as a Search Console owner)."
            ),
        )
    if not indexnow_ok:
        return Gate(
            id="search_indexing",
            label="Search-engine indexing",
            category="seo",
            state="warn",
            detail="Google Indexing API configured; IndexNow (Bing/Yandex) is not — INDEXNOW_KEY missing.",
            remediation="set INDEXNOW_KEY and host https://<site>/<key>.txt containing the key.",
        )
    if not google_ok:
        return Gate(
            id="search_indexing",
            label="Search-engine indexing",
            category="seo",
            state="warn",
            detail="IndexNow configured; Google Indexing API is not — GOOGLE_INDEXING_CREDENTIALS missing.",
            remediation="set GOOGLE_INDEXING_CREDENTIALS (service-account JSON, added as a Search Console owner).",
        )
    return Gate(
        id="search_indexing",
        label="Search-engine indexing",
        category="seo",
        state="ok",
        detail="Enabled; IndexNow and the Google Indexing API are both configured.",
        remediation="",
    )


def _billing_export_gate(facts: dict[str, Any]) -> Gate:
    if facts.get("billing_bq_table_set"):
        return Gate(
            id="billing_export",
            label="GCP billing export",
            category="ops",
            state="ok",
            detail="BILLING_BQ_TABLE is set; the dashboard spend widget can query BigQuery.",
            remediation="",
        )
    return Gate(
        id="billing_export",
        label="GCP billing export",
        category="ops",
        state="warn",
        detail="BILLING_BQ_TABLE is unset; the dashboard GCP Spend panel has no data.",
        remediation=(
            "enable Standard usage cost export to dataset billing_export, then set "
            "BILLING_BQ_TABLE=project.billing_export.gcp_billing_export_v1_<ACCOUNT>."
        ),
    )


_GATE_FNS = (
    _email_mode_gate,
    _rls_security_gate,
    _dmarc_gate,
    _secrets_present_gate,
    _integrations_gate,
    _oauth_capture_gate,
    _search_indexing_gate,
    _billing_export_gate,
)


def evaluate_gates(facts: dict[str, Any]) -> list[Gate]:
    """Evaluate every gate from an already-gathered facts dict. Pure, no I/O."""
    return [fn(facts) for fn in _GATE_FNS]


def summary(gates: list[Gate]) -> dict[str, Any]:
    """Roll gates up into counts + a ready flag (no blockers)."""
    ok = sum(1 for g in gates if g.state == "ok")
    warn = sum(1 for g in gates if g.state == "warn")
    blocker = sum(1 for g in gates if g.state == "blocker")
    return {
        "ok": ok,
        "warn": warn,
        "blocker": blocker,
        "total": len(gates),
        "ready": blocker == 0,
    }
