"""Production-readiness gates — pure evaluation, no I/O.

WHY: go-live readiness (email restricted to test allowlist, WordPress still on
staging, RLS bypassable, DMARC not enforced, missing secrets, broken
integrations, OAuth self-service reconnect off) was scattered across health
checks, env vars, and tribal knowledge. This module is the single, testable
source of truth for "are we actually ready to go live" — callers gather the
facts (env, DB, DNS, Secret Manager) and this module turns them into a gate
list the UI renders. Complements (does not replace) the live connectivity
probes in ``api/routes/config.py`` (``GET /config/health-checks``).
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


def _wordpress_gate(facts: dict[str, Any]) -> Gate:
    if not facts.get("wp_user_set") or not facts.get("wp_app_pwd_set"):
        return Gate(
            id="wordpress",
            label="WordPress credentials",
            category="wordpress",
            state="blocker",
            detail="WordPress username and/or application password are not configured.",
            remediation="set WP_USER and the wordpress-app-password secret in Admin Config.",
        )
    if facts.get("wp_is_staging"):
        return Gate(
            id="wordpress",
            label="WordPress target",
            category="wordpress",
            state="warn",
            detail=(
                "publishing to a staging site; production cutover pending #317, "
                "noindex still on"
            ),
            remediation="complete the production cutover (#317) and point WP_URL at the live site.",
        )
    return Gate(
        id="wordpress",
        label="WordPress target",
        category="wordpress",
        state="ok",
        detail="Publishing to the production WordPress site with valid credentials.",
        remediation="",
    )


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
    broken = [s["integration"] for s in statuses if s.get("status") == "broken"]
    unconfigured = [s["integration"] for s in statuses if s.get("status") == "unconfigured"]
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


_GATE_FNS = (
    _email_mode_gate,
    _wordpress_gate,
    _rls_security_gate,
    _dmarc_gate,
    _secrets_present_gate,
    _integrations_gate,
    _oauth_capture_gate,
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
