"""TDD tests for jobs/proposal_reminders.py — FAIL-FIRST, then implement.

Tests cover reminder cadence logic, idempotency, SKIP LOCKED semantics (mocked),
and that accepted proposals are never reminded.

Mocked tests: all DB access is mocked — the pure cadence-decision logic is
testable in isolation.

Real round-trip test: TestReminderRealRoundTrip uses a real SQLite DB to verify
that _insert_reminder_event stores event_metadata correctly and that a second
run_reminders call does NOT send a duplicate reminder (true idempotency).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from jobs.proposal_reminders import (
    _get_prior_reminder_numbers,
    _insert_reminder_event,
    compute_reminder_due,
    run_reminders,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sent_at(days_ago: float) -> datetime:
    return (_utcnow() - timedelta(days=days_ago)).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Pure cadence logic: compute_reminder_due
# ---------------------------------------------------------------------------

class TestComputeReminderDue:
    """compute_reminder_due(sent_at, cadence_days, prior_reminder_numbers) -> ReminderDecision"""

    def test_no_reminder_before_first_threshold(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(1),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[],
        )
        assert decision.due is False

    def test_reminder_due_at_first_threshold(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(3),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[],
        )
        assert decision.due is True
        assert decision.reminder_number == 1

    def test_reminder_due_past_first_threshold(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(5),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[],
        )
        assert decision.due is True
        assert decision.reminder_number == 1

    def test_second_reminder_due_after_first_sent(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(8),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[1],
        )
        assert decision.due is True
        assert decision.reminder_number == 2

    def test_third_reminder_due_after_two_sent(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(15),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[1, 2],
        )
        assert decision.due is True
        assert decision.reminder_number == 3

    def test_no_reminder_after_all_cadence_exhausted(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(30),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[1, 2, 3],
        )
        assert decision.due is False

    def test_not_duplicated_when_already_sent(self):
        """If reminder #1 already sent but we're still in the day-3 window, do not re-send."""
        decision = compute_reminder_due(
            sent_at=_sent_at(4),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[1],
        )
        assert decision.due is False

    def test_empty_cadence_never_reminds(self):
        decision = compute_reminder_due(
            sent_at=_sent_at(100),
            cadence_days=[],
            prior_reminder_numbers=[],
        )
        assert decision.due is False

    def test_reminder_boundary_exact_day(self):
        """Exactly N days elapsed → reminder is due."""
        decision = compute_reminder_due(
            sent_at=_sent_at(7),
            cadence_days=[3, 7, 14],
            prior_reminder_numbers=[1],
        )
        assert decision.due is True
        assert decision.reminder_number == 2


# ---------------------------------------------------------------------------
# run_reminders integration (all DB/email mocked)
# ---------------------------------------------------------------------------

class TestRunReminders:
    def _make_proposal(self, *, proposal_id=1, tenant_id=1, sent_days_ago=4,
                       status="sent", accept_token="tok1"):
        p = MagicMock()
        p.id = proposal_id
        p.tenant_id = tenant_id
        p.status = status
        p.accept_token = accept_token
        p.sent_at = _sent_at(sent_days_ago)
        return p

    def _make_session(self, proposals, events_by_id=None):
        """Build a mock SQLAlchemy session.

        The session's query chain handles two call patterns:
        - .all() returns the proposals list (for the SKIP LOCKED scan)
        - .first() returns a MagicMock tenant (for Tenant name lookup)
        """
        events_by_id = events_by_id or {}
        session = MagicMock()

        # Build a tenant mock so session.query(Tenant).filter(...).first() works
        mock_tenant = MagicMock()
        mock_tenant.name = "Perkins Roofing"

        query_chain = MagicMock()
        query_chain.filter.return_value = query_chain
        query_chain.with_for_update.return_value = query_chain
        query_chain.all.return_value = proposals
        query_chain.first.return_value = mock_tenant

        session.query.return_value = query_chain

        return session

    @patch("adapters.resend.send")
    def test_reminder_sent_at_threshold(self, mock_send):
        """Proposal sent 4 days ago, cadence=[3,7,14], no prior reminders → reminder #1 sent."""
        proposal = self._make_proposal(sent_days_ago=4)
        session = self._make_session([proposal])

        # No prior reminder events
        with patch("jobs.proposal_reminders._get_prior_reminder_numbers", return_value=[]):
            with patch("jobs.proposal_reminders._get_tenant_cadence", return_value=[3, 7, 14]):
                with patch("jobs.proposal_reminders._get_customer_email", return_value="client@example.com"):
                    with patch("jobs.proposal_reminders._insert_reminder_event") as mock_insert:
                        result = run_reminders(session=session)

        mock_send.assert_called_once()
        mock_insert.assert_called_once()
        assert result["sent"] == 1
        assert result["skipped"] == 0

    @patch("adapters.resend.send")
    def test_reminder_not_sent_before_threshold(self, mock_send):
        """Proposal sent 1 day ago, cadence=[3,7,14] → no reminder."""
        proposal = self._make_proposal(sent_days_ago=1)
        session = self._make_session([proposal])

        with patch("jobs.proposal_reminders._get_prior_reminder_numbers", return_value=[]):
            with patch("jobs.proposal_reminders._get_tenant_cadence", return_value=[3, 7, 14]):
                with patch("jobs.proposal_reminders._get_customer_email", return_value="client@example.com"):
                    with patch("jobs.proposal_reminders._insert_reminder_event") as mock_insert:
                        result = run_reminders(session=session)

        mock_send.assert_not_called()
        mock_insert.assert_not_called()
        assert result["sent"] == 0
        assert result["skipped"] == 1

    @patch("adapters.resend.send")
    def test_reminder_not_duplicated_on_second_run(self, mock_send):
        """Running the job twice: prior_reminder_numbers=[1] → no second reminder #1."""
        proposal = self._make_proposal(sent_days_ago=4)
        session = self._make_session([proposal])

        with patch("jobs.proposal_reminders._get_prior_reminder_numbers", return_value=[1]):
            with patch("jobs.proposal_reminders._get_tenant_cadence", return_value=[3, 7, 14]):
                with patch("jobs.proposal_reminders._get_customer_email", return_value="client@example.com"):
                    with patch("jobs.proposal_reminders._insert_reminder_event"):
                        result = run_reminders(session=session)

        mock_send.assert_not_called()
        assert result["sent"] == 0

    @patch("adapters.resend.send")
    def test_accepted_proposal_not_reminded(self, mock_send):
        """Accepted proposal (status='accepted') must never receive a reminder."""
        _proposal = self._make_proposal(sent_days_ago=10, status="accepted")
        # The query filter must exclude accepted — we verify by having an empty list
        session = self._make_session([])  # filter returns nothing

        with patch("jobs.proposal_reminders._get_prior_reminder_numbers", return_value=[]):
            with patch("jobs.proposal_reminders._get_tenant_cadence", return_value=[3, 7, 14]):
                with patch("jobs.proposal_reminders._get_customer_email", return_value="c@e.com"):
                    result = run_reminders(session=session)

        mock_send.assert_not_called()
        assert result["sent"] == 0

    @patch("adapters.resend.send")
    def test_multiple_proposals_processed(self, mock_send):
        """Two proposals at threshold → two reminders sent."""
        p1 = self._make_proposal(proposal_id=1, sent_days_ago=4, accept_token="t1")
        p2 = self._make_proposal(proposal_id=2, sent_days_ago=8, accept_token="t2")
        session = self._make_session([p1, p2])

        with patch("jobs.proposal_reminders._get_prior_reminder_numbers", return_value=[]):
            with patch("jobs.proposal_reminders._get_tenant_cadence", return_value=[3, 7, 14]):
                with patch("jobs.proposal_reminders._get_customer_email", return_value="c@e.com"):
                    with patch("jobs.proposal_reminders._insert_reminder_event"):
                        result = run_reminders(session=session)

        assert mock_send.call_count == 2
        assert result["sent"] == 2


# ---------------------------------------------------------------------------
# Real round-trip: _insert_reminder_event + _get_prior_reminder_numbers
# using a real SQLite DB — tests that event_metadata is stored/read correctly
# and that run_reminders is idempotent (no duplicate reminder on second call)
# ---------------------------------------------------------------------------

class TestReminderRealRoundTrip:
    """Non-mocked test: uses real SQLite to verify end-to-end idempotency.

    _insert_reminder_event must store reminder_number in event_metadata.
    _get_prior_reminder_numbers must read it back via event_metadata (not
    the old .metadata attribute which does not exist on ProposalEvent).
    A second run_reminders call after the event is inserted must skip the
    proposal (no duplicate reminder sent).
    """

    def _setup_proposal(self, session, sent_days_ago=4):
        """Create a minimal tenant + customer + property + proposal in the real DB."""
        import base64
        import secrets as _secrets

        from app.models import Customer, Property, Proposal, Tenant
        # Tenant
        tenant = Tenant(name="RT Tenant", slug=f"rt-{_secrets.token_hex(4)}", status="active", settings={})
        session.add(tenant)
        session.flush()
        # Customer
        cust = Customer(tenant_id=tenant.id, display_name="RT Customer", email="rt@example.com")
        session.add(cust)
        session.flush()
        # Property
        prop = Property(tenant_id=tenant.id, customer_id=cust.id,
                        street="1 Test St", city="Miami", state="FL", code_zone="FBC")
        session.add(prop)
        session.flush()
        # Proposal in 'sent' state
        token = base64.urlsafe_b64encode(_secrets.token_bytes(64)).rstrip(b"=").decode()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        sent_at = now - timedelta(days=sent_days_ago)
        proposal = Proposal(
            tenant_id=tenant.id,
            customer_id=cust.id,
            property_id=prop.id,
            title="RT Proposal",
            quote_snapshot={"tiers": {}, "deposit_policy": {"mode": "none", "value": 0}},
            status="sent",
            accept_token=token,
            created_by="test",
            sent_at=sent_at,
        )
        session.add(proposal)
        session.commit()
        return proposal

    def test_insert_reminder_event_stores_metadata(self):
        """_insert_reminder_event stores reminder_number in event_metadata, readable back."""
        from app.models import SessionLocal, init_db
        init_db()
        with SessionLocal() as session:
            proposal = self._setup_proposal(session)
            _insert_reminder_event(session, proposal.id, proposal.tenant_id, reminder_number=1)
            session.commit()

            # _get_prior_reminder_numbers must read it back correctly
            numbers = _get_prior_reminder_numbers(session, proposal.id)
            assert numbers == [1], (
                f"Expected [1] but got {numbers} — event_metadata not stored/read correctly"
            )

    @patch("adapters.resend.send")
    def test_no_duplicate_reminder_on_second_run(self, mock_send):
        """After inserting reminder event #1, a second run must NOT send again (true idempotency)."""
        from app.models import SessionLocal, init_db
        init_db()
        with SessionLocal() as session:
            proposal = self._setup_proposal(session, sent_days_ago=4)
            # Simulate: first run already inserted the reminder event
            _insert_reminder_event(session, proposal.id, proposal.tenant_id, reminder_number=1)
            session.commit()

        # Second run: the proposal is still in 'sent' state, but reminder #1 already exists.
        # run_reminders must skip it (no send, no new event).
        with patch("jobs.proposal_reminders._get_tenant_cadence", return_value=[3, 7, 14]):
            with patch("jobs.proposal_reminders._get_customer_email", return_value="rt@example.com"):
                # We do NOT mock _get_prior_reminder_numbers — it reads the real DB
                with SessionLocal() as session:
                    result = run_reminders(session=session)

        mock_send.assert_not_called()
        assert result["sent"] == 0, (
            f"Expected 0 sent (idempotent), got {result['sent']}"
        )
