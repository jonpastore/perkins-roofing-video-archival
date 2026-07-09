"""Positive + negative RLS validation for the proposals accept-token policy (0022).

The public proposal-accept page resolves the owning tenant from an opaque 512-bit
accept_token BEFORE any tenant context exists, so it reads the RLS-FORCED proposals
table with app.tenant_id UNSET, gating the read on a transaction-local
app.accept_token GUC (see api/routes/proposals.py _token_scoped_session +
infra/migrations/0022_proposals_accept_token_policy.sql).

These tests prove, against real Postgres with the policy applied and connecting as a
NON-BYPASSRLS role (see conftest), that:
  - the token grants exactly its own proposal (positive match), and
  - the grant never leaks another tenant's rows (token is a scoped capability, not
    a blanket read), and
  - an unstamped read returns empty instead of raising (the pre-0022 1-arg policy
    raised "unrecognized configuration parameter app.tenant_id").

Requires real Postgres — RLS policies do not exist on SQLite (would false-green).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.tenancy.test_rls_denial import _seed_customer, _seed_property, _set_guc

pytestmark = pytest.mark.postgres

_T1_TOKEN = "tok-t1-" + "a" * 70  # 77 chars (accept_token is varchar(86))
_T2_TOKEN = "tok-t2-" + "b" * 70


def _seed_proposal_with_token(conn, customer_id, property_id, tenant_id, token):
    return conn.execute(
        text(
            "INSERT INTO proposals "
            "(customer_id, property_id, title, quote_snapshot, status, accept_token, "
            "created_by, version_number, tenant_id, created_at, updated_at) "
            "VALUES (:cid, :pid, 'P', '{}', 'sent', :tok, 't@t.com', 1, :tid, NOW(), NOW()) "
            "RETURNING id"
        ),
        {"cid": customer_id, "pid": property_id, "tok": token, "tid": tenant_id},
    ).scalar()


def _set_token(conn, token):
    conn.execute(
        text("SELECT set_config('app.accept_token', :t, true)"), {"t": token}
    )


@pytest.fixture(scope="module")
def two_tenant_proposals(pg_engine):
    """Seed one proposal for tenant 1 and one for tenant 2, each with a known
    accept_token. Committed (the policy read happens in a separate transaction);
    cleaned up on teardown so the shared session DB is left as found."""
    ids = {}
    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        c1 = _seed_customer(conn, 1)
        p1 = _seed_property(conn, c1, 1)
        ids["t1"] = _seed_proposal_with_token(conn, c1, p1, 1, _T1_TOKEN)
        ids["c1"], ids["p1"] = c1, p1
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        c2 = _seed_customer(conn, 2)
        p2 = _seed_property(conn, c2, 2)
        ids["t2"] = _seed_proposal_with_token(conn, c2, p2, 2, _T2_TOKEN)
        ids["c2"], ids["p2"] = c2, p2

    yield ids

    for tid, pkey, ckey, prkey in ((1, "t1", "c1", "p1"), (2, "t2", "c2", "p2")):
        with pg_engine.begin() as conn:
            _set_guc(conn, tid)
            conn.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": ids[pkey]})
            conn.execute(text("DELETE FROM properties WHERE id = :i"), {"i": ids[prkey]})
            conn.execute(text("DELETE FROM customers WHERE id = :i"), {"i": ids[ckey]})


def test_token_reads_exactly_its_own_proposal(pg_engine, two_tenant_proposals):
    """app.accept_token set, NO app.tenant_id → the resolver reads exactly the
    matching proposal (the positive path the accept page depends on)."""
    with pg_engine.begin() as conn:
        _set_token(conn, _T1_TOKEN)
        rows = conn.execute(
            text("SELECT id, tenant_id FROM proposals WHERE accept_token = :t"),
            {"t": _T1_TOKEN},
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == two_tenant_proposals["t1"]
    assert rows[0][1] == 1


def test_token_grant_does_not_leak_other_tenants(pg_engine, two_tenant_proposals):
    """A set app.accept_token grants ONLY its row: an unfiltered SELECT (no tenant
    GUC) returns just that one proposal, never another tenant's."""
    with pg_engine.begin() as conn:
        _set_token(conn, _T1_TOKEN)
        rows = conn.execute(text("SELECT id, tenant_id FROM proposals")).fetchall()
    ids = {r[0] for r in rows}
    assert two_tenant_proposals["t1"] in ids
    assert two_tenant_proposals["t2"] not in ids
    assert all(r[1] == 1 for r in rows)


def test_unstamped_no_token_returns_empty_not_error(pg_engine, two_tenant_proposals):
    """No app.tenant_id and no app.accept_token → 2-arg policy returns zero rows
    WITHOUT raising (the pre-0022 1-arg policy raised on the unset GUC → 500)."""
    with pg_engine.begin() as conn:
        rows = conn.execute(text("SELECT id FROM proposals")).fetchall()
    assert rows == []


def test_wrong_token_returns_empty(pg_engine, two_tenant_proposals):
    """A non-matching app.accept_token grants nothing."""
    with pg_engine.begin() as conn:
        _set_token(conn, "does-not-exist")
        rows = conn.execute(
            text("SELECT id FROM proposals WHERE accept_token = :t"),
            {"t": "does-not-exist"},
        ).fetchall()
    assert rows == []


def test_tenant2_session_cannot_read_tenant1_by_token(pg_engine, two_tenant_proposals):
    """A tenant-2-stamped session (no accept_token GUC) cannot read tenant 1's
    proposal even by its exact token — the token OR-clause requires the
    app.accept_token GUC, which a normal tenant session never sets."""
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        rows = conn.execute(
            text("SELECT id FROM proposals WHERE accept_token = :t"),
            {"t": _T1_TOKEN},
        ).fetchall()
    assert rows == []
