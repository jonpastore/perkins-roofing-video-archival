"""Proposal reminder nudge job (Wave F3).

Selects proposals in 'sent' or 'viewed' status past their reminder threshold
and sends a nudge email via Resend. Uses SELECT FOR UPDATE SKIP LOCKED for
idempotent, concurrent-safe operation (same pattern as publish_job.py).

Cadence config in tenants.settings.reminder_cadence_days (JSONB array).
Default cadence if not configured: [3, 7, 14] days.

Tenancy: run() iterates active tenants via for_each_tenant() so the SKIP LOCKED
scan runs inside each tenant's RLS context (strict-safe). run_reminders(session)
remains the single-tenant body, also used directly by tests.

Run: POST /jobs/reminders (Cloud Scheduler) or directly:
    python -m jobs.proposal_reminders
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import adapters.resend as resend
from app.models import SessionLocal

# Default reminder cadence (days after send) when tenant has no config.
_DEFAULT_CADENCE: list[int] = [3, 7, 14]


# ---------------------------------------------------------------------------
# Pure cadence logic — fully unit-testable, no I/O
# ---------------------------------------------------------------------------

@dataclass
class ReminderDecision:
    due: bool
    reminder_number: int = 0


def compute_reminder_due(
    sent_at: datetime,
    cadence_days: list[int],
    prior_reminder_numbers: list[int],
) -> ReminderDecision:
    """Determine whether a reminder is due for a proposal.

    Args:
        sent_at: When the proposal was sent (naive UTC).
        cadence_days: Sorted list of day offsets at which reminders are sent
            (e.g. [3, 7, 14]).
        prior_reminder_numbers: List of reminder_number values from existing
            proposal_events of type 'reminder_sent'.

    Returns:
        ReminderDecision(due=True, reminder_number=N) when a new reminder
        is due, or ReminderDecision(due=False) when none is needed.
    """
    if not cadence_days:
        return ReminderDecision(due=False)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed_days = (now - sent_at).total_seconds() / 86400.0

    sent_set = set(prior_reminder_numbers)
    sorted_cadence = sorted(cadence_days)

    for i, threshold_day in enumerate(sorted_cadence):
        reminder_number = i + 1
        if elapsed_days >= threshold_day and reminder_number not in sent_set:
            return ReminderDecision(due=True, reminder_number=reminder_number)

    return ReminderDecision(due=False)


# ---------------------------------------------------------------------------
# DB helpers (thin wrappers — mockable in tests)
# ---------------------------------------------------------------------------

def _get_tenant_cadence(session: Any, tenant_id: int) -> list[int]:
    """Read reminder_cadence_days from tenants.settings for the given tenant."""
    from app.models import Tenant  # noqa: PLC0415
    tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return _DEFAULT_CADENCE
    settings: dict = tenant.settings or {}
    cadence = settings.get("reminder_cadence_days")
    if isinstance(cadence, list) and all(isinstance(d, int) for d in cadence):
        return cadence
    return _DEFAULT_CADENCE


def _get_prior_reminder_numbers(session: Any, proposal_id: int) -> list[int]:
    """Return reminder_number values from existing reminder_sent events."""
    from app.models import ProposalEvent  # noqa: PLC0415
    events = (
        session.query(ProposalEvent)
        .filter(
            ProposalEvent.proposal_id == proposal_id,
            ProposalEvent.event_type == "reminder_sent",
        )
        .all()
    )
    numbers = []
    for ev in events:
        meta = (ev.event_metadata or {})
        n = meta.get("reminder_number")
        if isinstance(n, int):
            numbers.append(n)
    return numbers


def _get_customer_email(session: Any, proposal_id: int) -> str | None:
    """Return the customer email for a proposal."""
    from app.models import Customer, Proposal  # noqa: PLC0415
    proposal = session.query(Proposal).filter(Proposal.id == proposal_id).first()
    if proposal is None:
        return None
    customer = session.query(Customer).filter(Customer.id == proposal.customer_id).first()
    if customer is None:
        return None
    return customer.email


def _insert_reminder_event(
    session: Any,
    proposal_id: int,
    tenant_id: int,
    reminder_number: int,
) -> None:
    """Insert a proposal_events row for a reminder_sent event."""
    from app.models import ProposalEvent  # noqa: PLC0415
    event = ProposalEvent(
        tenant_id=tenant_id,
        proposal_id=proposal_id,
        event_type="reminder_sent",
        event_metadata={"reminder_number": reminder_number},
    )
    session.add(event)
    session.flush()


def _build_reminder_email_html(
    proposal_id: int,
    accept_url: str,
    tenant_name: str,
    reminder_number: int,
) -> str:
    """Build simple reminder email HTML body."""
    return f"""
<html><body>
<p>Hello,</p>
<p>This is a friendly reminder that your proposal from <strong>{tenant_name}</strong>
is still awaiting your review.</p>
<p><a href="{accept_url}" style="background:#C0392B;color:#fff;padding:12px 24px;
text-decoration:none;border-radius:4px;display:inline-block;">
Review &amp; Accept Proposal</a></p>
<p>Or copy this link: {accept_url}</p>
<p>If you have any questions, please reply to this email.</p>
<p>Best regards,<br>{tenant_name}</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# Main job entrypoint
# ---------------------------------------------------------------------------

def run_reminders(session: Any = None) -> dict[str, int]:
    """Run the proposal reminder job.

    Selects all proposals in 'sent' or 'viewed' status using SELECT FOR UPDATE
    SKIP LOCKED, evaluates the reminder cadence for each, and sends nudge emails
    via Resend for proposals that are past a threshold without a prior reminder.

    Returns:
        Dict with keys: sent, skipped, errored.
    """
    from app.models import Proposal, Tenant  # noqa: PLC0415

    own_session = session is None
    if own_session:
        session = SessionLocal()

    sent_count = skipped = errored = 0

    try:
        proposals = (
            session.query(Proposal)
            .filter(Proposal.status.in_(["sent", "viewed"]))
            .with_for_update(skip_locked=True)
            .all()
        )

        for proposal in proposals:
            try:
                cadence = _get_tenant_cadence(session, proposal.tenant_id)
                prior = _get_prior_reminder_numbers(session, proposal.id)

                decision = compute_reminder_due(
                    sent_at=proposal.sent_at,
                    cadence_days=cadence,
                    prior_reminder_numbers=prior,
                )

                if not decision.due:
                    skipped += 1
                    continue

                email = _get_customer_email(session, proposal.id)
                if not email:
                    skipped += 1
                    continue

                # Fetch tenant name for the email
                tenant = session.query(Tenant).filter(
                    Tenant.id == proposal.tenant_id
                ).first()
                tenant_name = tenant.name if tenant else "Your roofing contractor"

                app_base = os.getenv("APP_BASE_URL", "https://app.perkinsroofing.net")
                accept_url = f"{app_base}/p/{proposal.accept_token}"

                html_body = _build_reminder_email_html(
                    proposal_id=proposal.id,
                    accept_url=accept_url,
                    tenant_name=tenant_name,
                    reminder_number=decision.reminder_number,
                )

                resend.send(
                    from_name=tenant_name,
                    reply_to=os.getenv("REMINDER_REPLY_TO", "info@perkinsroofing.net"),
                    to=email,
                    subject=f"Reminder: Your proposal is waiting — {tenant_name}",
                    html=html_body,
                )

                _insert_reminder_event(
                    session=session,
                    proposal_id=proposal.id,
                    tenant_id=proposal.tenant_id,
                    reminder_number=decision.reminder_number,
                )
                session.commit()
                sent_count += 1

            except Exception as exc:  # noqa: BLE001
                session.rollback()
                errored += 1
                import logging  # noqa: PLC0415
                logging.getLogger(__name__).error(
                    "Reminder error for proposal %s: %s", proposal.id, exc
                )

    finally:
        if own_session:
            session.close()

    return {"sent": sent_count, "skipped": skipped, "errored": errored}


def run() -> dict[str, int]:
    """Iterate active tenants; run the SKIP LOCKED reminder scan inside each
    tenant's RLS context (the F5 for_each_tenant refactor — strict-safe)."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict[str, int] = {"sent": 0, "skipped": 0, "errored": 0}

    def _fn(db, tenant_id: int) -> None:
        r = run_reminders(session=db)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    result = run()
    print(f"Reminders: {result}")
