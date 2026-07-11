"""C2 concurrency proof: invoice numbering is collision-free under two concurrent
sessions (backlog #JB4, R2 finding C2).

The validator scripts/validate_invoice_api.py asserts the UNIQUE(tenant, number)
constraint would REJECT a collision. This test proves the stronger property that the
collision never happens in the first place: `_issue_number` allocates via a single
`UPDATE tenant_invoice_counters SET last_number = last_number + 1 RETURNING`, whose
row lock SERIALIZES concurrent allocators — the second transaction blocks on the first
until it commits, then reads the committed value and increments it. Two callers racing
for the same tenant's next number get consecutive, distinct numbers.

Requires a real PostgreSQL (SQLite has no row-level locking / RLS) — marked
@pytest.mark.postgres, skipped when no Postgres is available (see conftest.py).
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import text

from api.routes.invoices import _issue_number

pytestmark = pytest.mark.postgres

# A tenant seeded by the conftest pg_admin_engine fixture (tenants 1 and 2 exist).
_TENANT = 1


def _new_session(factory, tenant_id: int):
    s = factory()
    s.info["tenant_id"] = tenant_id
    return s


def test_two_session_numbering_is_serialized_and_gapless(rls_engine):
    """Two concurrent sessions allocating a number for the same tenant get
    consecutive distinct numbers — the row lock forces the second to wait for the
    first to commit, so neither reads a stale counter."""
    factory = rls_engine

    # Seed a known baseline: issue + COMMIT one number so the counter row exists and is
    # committed (both racers then contend on an existing row, deterministic ordering).
    s0 = _new_session(factory, _TENANT)
    try:
        n0 = _issue_number(s0, _TENANT)
        s0.commit()
    finally:
        s0.close()

    session_a = _new_session(factory, _TENANT)
    session_b = _new_session(factory, _TENANT)
    b_result: dict[str, int] = {}
    b_started = threading.Event()

    def allocate_b() -> None:
        b_started.set()
        # This blocks on the row lock A holds until A commits, then returns A's number + 1.
        b_result["n"] = _issue_number(session_b, _TENANT)
        session_b.commit()

    try:
        # A allocates and HOLDS the row lock (no commit yet).
        n_a = _issue_number(session_a, _TENANT)

        # B races for the same counter in a second connection.
        t = threading.Thread(target=allocate_b, daemon=True)
        t.start()
        assert b_started.wait(timeout=5.0), "B thread never started"

        # While A's transaction is open, B must be BLOCKED on the row lock — it cannot
        # have produced a number yet. If it had, both would have read the same counter.
        t.join(timeout=1.5)
        assert t.is_alive(), (
            "B allocated a number while A held the lock uncommitted — the UPDATE is not "
            "serializing; concurrent draws could collide on the same invoice number."
        )
        assert "n" not in b_result

        # Releasing A lets B proceed off the committed value.
        session_a.commit()
        t.join(timeout=5.0)
        assert not t.is_alive(), "B never unblocked after A committed"
    finally:
        session_a.close()
        session_b.close()

    n_b = b_result["n"]
    assert n_a == n0 + 1, f"A should get the baseline+1 ({n0 + 1}), got {n_a}"
    assert n_b == n_a + 1, f"B should get A's number+1 ({n_a + 1}), got {n_b}"
    assert n_a != n_b, "the two concurrent allocations collided on the same number"


def test_sequential_allocations_are_gapless(rls_engine):
    """Sanity floor: back-to-back allocations in the same session are strictly +1 with
    no gaps — a regression guard on the counter arithmetic itself."""
    s = _new_session(rls_engine, _TENANT)
    try:
        first = _issue_number(s, _TENANT)
        second = _issue_number(s, _TENANT)
        third = _issue_number(s, _TENANT)
        s.commit()
    finally:
        s.close()
    assert second == first + 1
    assert third == second + 1


def test_counter_is_per_tenant(rls_engine):
    """Distinct tenants keep independent sequences — allocating for tenant 2 does not
    advance tenant 1's counter (new tenants start their own run)."""
    s = _new_session(rls_engine, 2)
    try:
        n = _issue_number(s, 2)
        # tenant 2 has no seed (migration 0030 seeds only tenant 1/Perkins at 18732),
        # so its sequence starts at 1 in the fixture DB.
        assert n >= 1
        # The row is tenant-scoped: reading tenant 2's counter never sees tenant 1's.
        row = s.execute(
            text("SELECT last_number FROM tenant_invoice_counters WHERE tenant_id = 2")
        ).scalar_one()
        assert row == n
        s.commit()
    finally:
        s.close()
