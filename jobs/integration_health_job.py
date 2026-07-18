"""Cloud Scheduler target (via /internal/integration-health, or run directly): probe every
shared platform integration once, persist health status onto `integration_status`, and email
an admin alert on transition-to-broken (plan Phase 1.4).

Shared integrations (tenant_id NULL rows — see app/models.py IntegrationStatus / migration
0039): wordpress, resend, knowify, youtube_reply. All four are treated as platform-level for
now because their credentials live in env/Secret Manager, not the per-tenant
SecretManagerOAuthStore (that migration is Phase 1.7). Uses PlatformSessionLocal +
platform_scope=True — integration_status has no RLS, so no tenant GUC is needed.

Also sweeps expired `oauth_state_nonces` rows (cheap housekeeping per migration 0039's
comment — nonces are single-use and short-lived; this just reclaims dead rows).

Run: .venv/bin/python -m jobs.integration_health_job
"""
from __future__ import annotations

from datetime import datetime, timezone

import adapters.integration_probes as probes
import adapters.resend as resend
from app.config import settings
from app.models import IntegrationStatus, OAuthStateNonce, PlatformSessionLocal
from core.integration_health import ProbeResult, next_status, should_alert

_PROBES = {
    "wordpress": probes.probe_wordpress,
    "resend": probes.probe_resend,
    "knowify": probes.probe_knowify,
    "youtube_reply": probes.probe_youtube_reply,
    "companycam": probes.probe_companycam,
}


def _load_row(db, integration: str) -> IntegrationStatus:
    row = (
        db.query(IntegrationStatus)
        .filter(IntegrationStatus.tenant_id.is_(None), IntegrationStatus.integration == integration)
        .first()
    )
    if row is None:
        row = IntegrationStatus(tenant_id=None, integration=integration, status="unconfigured",
                                 consecutive_failures=0)
        db.add(row)
        db.flush()
    return row


def _send_alert(integration: str, error: str | None) -> None:
    subject = f"Integration BROKEN: {integration}"
    html = (
        f"<p>Integration <b>{integration}</b> just transitioned to BROKEN.</p>"
        f"<p>Last error: {error or '(none captured)'}</p>"
        f"<p>Reconnect at the dashboard Connections page.</p>"
    )
    for admin in sorted(settings.DEFAULT_ADMINS):
        resend.send(
            reply_to=admin,
            to=admin,
            subject=subject,
            html=html,
            send_type="integration_health_alert",
        )


def _sweep_expired_nonces(db, now: datetime) -> int:
    return (
        db.query(OAuthStateNonce)
        .filter(OAuthStateNonce.expires_at < now)
        .delete(synchronize_session=False)
    )


def run(now=None) -> dict:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    db = PlatformSessionLocal()
    db.info["platform_scope"] = True
    statuses: dict[str, str] = {}
    try:
        for integration, probe_fn in _PROBES.items():
            row = _load_row(db, integration)
            try:
                probe = probe_fn()
            except Exception as exc:  # noqa: BLE001 — one probe must never kill the whole sweep
                probe = ProbeResult(ok=False, error=f"probe raised: {exc}")
            if probe is None:
                row.status = "unconfigured"
                row.last_checked = now
                db.add(row)
                statuses[integration] = "unconfigured"
                continue

            new_status, new_failures = next_status(probe, row.status, row.consecutive_failures)
            alert = should_alert(row.status, new_status)
            row.status = new_status
            row.consecutive_failures = new_failures
            row.last_checked = now
            row.last_error = probe.error
            if probe.ok:
                row.last_ok = now
            db.add(row)
            if alert:
                _send_alert(integration, probe.error)
            statuses[integration] = new_status

        nonces_swept = _sweep_expired_nonces(db, now)
        db.commit()
    finally:
        db.close()
    return {"statuses": statuses, "nonces_swept": nonces_swept}


if __name__ == "__main__":
    print(run())
