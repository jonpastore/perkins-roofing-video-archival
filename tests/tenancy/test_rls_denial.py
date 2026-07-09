"""RLS denial matrix — ≥30 cross-tenant denial tests.

ALL tests in this file are marked @pytest.mark.postgres and require a real
PostgreSQL instance. They MUST NOT run on SQLite — RLS policies do not exist
on SQLite and would produce false-green results.

The test fixture seeds:
  - tenant 1 (Perkins) with one row in each tested table
  - tenant 2 (Acme) attempting to read/write/delete tenant 1's rows → must get 0 rows

Strategy: bypass the ORM layer and use raw SQL with the GUC set to the
cross-tenant value, verifying that RLS returns 0 rows (not an error).
This tests the suspenders (RLS) independently of the belt (ORM filter).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_guc(conn, tenant_id: int):
    # set_config(..., is_local => true) instead of `SET LOCAL app.tenant_id = :tid`:
    # Postgres SET rejects extended-protocol bind params (syntax error near "$1").
    conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def _seed_video(conn, tenant_id: int, vid_id: str = None):
    vid_id = vid_id or f"vid-t{tenant_id}"
    conn.execute(text(
        "INSERT INTO videos (id, title, tenant_id) "
        "VALUES (:id, :title, :tid) ON CONFLICT (id) DO NOTHING"
    ), {"id": vid_id, "title": f"Video T{tenant_id}", "tid": tenant_id})
    return vid_id


def _seed_article(conn, tenant_id: int, slug: str = None):
    slug = slug or f"article-t{tenant_id}"
    conn.execute(text(
        "INSERT INTO articles (slug, title, status, role, tenant_id) "
        "VALUES (:slug, :title, 'draft', 'standalone', :tid) "
        "ON CONFLICT (slug) DO NOTHING"
    ), {"slug": slug, "title": f"Article T{tenant_id}", "tid": tenant_id})
    return slug


def _seed_mini_series(conn, tenant_id: int) -> int:
    result = conn.execute(text(
        "INSERT INTO mini_series (video_id, title, parts_json, tenant_id) "
        "VALUES ('vid-seed', 'Series', '[]', :tid) RETURNING id"
    ), {"tid": tenant_id})
    return result.scalar()


def _seed_social_post(conn, tenant_id: int) -> int:
    result = conn.execute(text(
        "INSERT INTO social_posts (series_id, part, platform, status, tenant_id) "
        "VALUES (999, 1, 'instagram', 'pending', :tid) RETURNING id"
    ), {"tid": tenant_id})
    return result.scalar()


def _seed_comment_draft(conn, tenant_id: int) -> int:
    result = conn.execute(text(
        "INSERT INTO comment_drafts "
        "(video_id, comment_id, comment_text, needs_reply, status, tenant_id, created_at) "
        "VALUES ('vid-seed', :cid, 'Hello', false, 'pending', :tid, NOW()) RETURNING id"
    ), {"cid": f"cmt-t{tenant_id}", "tid": tenant_id})
    return result.scalar()


def _seed_faq_entry(conn, tenant_id: int) -> int:
    result = conn.execute(text(
        "INSERT INTO faq_entries "
        "(question, source_kind, source_node_id, video_id, start, status, tenant_id, created_at) "
        "VALUES ('How?', 'claim', :nid, 'vid-seed', 0.0, 'mined', :tid, NOW()) RETURNING id"
    ), {"nid": tenant_id * 1000, "tid": tenant_id})
    return result.scalar()


def _seed_customer(conn, tenant_id: int) -> int:
    result = conn.execute(text(
        "INSERT INTO customers (display_name, tenant_id, created_at, updated_at) "
        "VALUES (:name, :tid, NOW(), NOW()) RETURNING id"
    ), {"name": f"Customer T{tenant_id}", "tid": tenant_id})
    return result.scalar()


def _seed_proposal(conn, customer_id: int, property_id: int, tenant_id: int) -> int:
    import secrets
    token = secrets.token_urlsafe(64)[:86]
    result = conn.execute(text(
        "INSERT INTO proposals "
        "(customer_id, property_id, title, quote_snapshot, status, accept_token, created_by, "
        "version_number, tenant_id, created_at, updated_at) "
        "VALUES (:cid, :pid, 'Proposal', '{}', 'draft', :tok, 'test@test.com', 1, :tid, NOW(), NOW()) "
        "RETURNING id"
    ), {"cid": customer_id, "pid": property_id, "tok": token, "tid": tenant_id})
    return result.scalar()


def _seed_property(conn, customer_id: int, tenant_id: int) -> int:
    result = conn.execute(text(
        "INSERT INTO properties (customer_id, street, city, state, code_zone, tenant_id, "
        "created_at, updated_at) "
        "VALUES (:cid, '123 Main St', 'Tampa', 'FL', 'FBC', :tid, NOW(), NOW()) RETURNING id"
    ), {"cid": customer_id, "tid": tenant_id})
    return result.scalar()


# ---------------------------------------------------------------------------
# Session-scoped seed fixture (creates rows once per test session)
# ---------------------------------------------------------------------------

# The `seeded_rows` fixture is defined in conftest.py so both this file and
# test_rls_probe.py can request it (a fixture defined in a test module is not
# visible to sibling modules). It reuses the _seed_* helpers below.


# ---------------------------------------------------------------------------
# Denial matrix: 30+ parametrized cross-tenant read tests
# Each row: (label, SELECT COUNT query that tenant 2 should see 0 rows of)
# ---------------------------------------------------------------------------

DENIAL_READS = [
    # (label, table, count_query)
    ("videos_read",
     "SELECT COUNT(*) FROM videos WHERE tenant_id = 1"),
    ("ingestion_runs_read",
     "SELECT COUNT(*) FROM ingestion_runs WHERE tenant_id = 1"),
    ("segments_read",
     "SELECT COUNT(*) FROM segments WHERE tenant_id = 1"),
    ("words_read",
     "SELECT COUNT(*) FROM words WHERE tenant_id = 1"),
    ("content_graph_read",
     "SELECT COUNT(*) FROM content_graph WHERE tenant_id = 1"),
    ("chunks_read",
     "SELECT COUNT(*) FROM chunks WHERE tenant_id = 1"),
    ("email_templates_read",
     "SELECT COUNT(*) FROM email_templates WHERE tenant_id = 1"),
    ("clusters_read",
     "SELECT COUNT(*) FROM clusters WHERE tenant_id = 1"),
    ("articles_read",
     "SELECT COUNT(*) FROM articles WHERE tenant_id = 1"),
    ("scheduled_content_read",
     "SELECT COUNT(*) FROM scheduled_content WHERE tenant_id = 1"),
    ("mini_series_read",
     "SELECT COUNT(*) FROM mini_series WHERE tenant_id = 1"),
    ("social_posts_read",
     "SELECT COUNT(*) FROM social_posts WHERE tenant_id = 1"),
    ("aggregated_topics_read",
     "SELECT COUNT(*) FROM aggregated_topics WHERE tenant_id = 1"),
    ("comment_drafts_read",
     "SELECT COUNT(*) FROM comment_drafts WHERE tenant_id = 1"),
    ("user_settings_read",
     "SELECT COUNT(*) FROM user_settings WHERE tenant_id = 1"),
    ("faq_entries_read",
     "SELECT COUNT(*) FROM faq_entries WHERE tenant_id = 1"),
    ("pricing_configs_read",
     "SELECT COUNT(*) FROM pricing_configs WHERE tenant_id = 1"),
    ("estimates_read",
     "SELECT COUNT(*) FROM estimates WHERE tenant_id = 1"),
    ("measurements_read",
     "SELECT COUNT(*) FROM measurements WHERE tenant_id = 1"),
    ("customers_read",
     "SELECT COUNT(*) FROM customers WHERE tenant_id = 1"),
    ("contacts_read",
     "SELECT COUNT(*) FROM contacts WHERE tenant_id = 1"),
    ("properties_read",
     "SELECT COUNT(*) FROM properties WHERE tenant_id = 1"),
    ("proposal_templates_read",
     "SELECT COUNT(*) FROM proposal_templates WHERE tenant_id = 1"),
    ("proposals_read",
     "SELECT COUNT(*) FROM proposals WHERE tenant_id = 1"),
    ("proposal_events_read",
     "SELECT COUNT(*) FROM proposal_events WHERE tenant_id = 1"),
    ("leads_read",
     "SELECT COUNT(*) FROM leads WHERE tenant_id = 1"),
    ("jobs_read",
     "SELECT COUNT(*) FROM jobs WHERE tenant_id = 1"),
    ("catalog_items_read",
     "SELECT COUNT(*) FROM catalog_items WHERE tenant_id = 1"),
    ("tc_versions_read",
     "SELECT COUNT(*) FROM tc_versions WHERE tenant_id = 1"),
]


@pytest.mark.postgres
@pytest.mark.parametrize("label,query", DENIAL_READS, ids=[r[0] for r in DENIAL_READS])
def test_cross_tenant_read_denial(label, query, seeded_rows, pg_engine):
    """Tenant 2 GUC set → tenant 1 rows are invisible (RLS returns 0 rows)."""
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)  # pretend we are tenant 2
        count = conn.execute(text(query)).scalar()
    assert count == 0, (
        f"[{label}] RLS violation: tenant 2 can see {count} row(s) belonging to tenant 1"
    )


# ---------------------------------------------------------------------------
# Write-denial tests (INSERT with wrong tenant_id must be blocked by WITH CHECK)
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_cross_tenant_insert_denied_videos(pg_engine):
    """Inserting a row with tenant_id=1 while GUC is set to 2 must be blocked."""
    with pytest.raises(Exception, match="new row violates row-level security|policy"):
        with pg_engine.begin() as conn:
            _set_guc(conn, 2)
            conn.execute(text(
                "INSERT INTO videos (id, title, tenant_id) "
                "VALUES ('vid-rls-inject', 'Injected', 1)"
            ))


@pytest.mark.postgres
def test_cross_tenant_insert_denied_articles(pg_engine):
    """INSERT into articles with wrong tenant_id is denied by WITH CHECK."""
    with pytest.raises(Exception, match="new row violates row-level security|policy"):
        with pg_engine.begin() as conn:
            _set_guc(conn, 2)
            conn.execute(text(
                "INSERT INTO articles (slug, title, status, role, tenant_id) "
                "VALUES ('injected-article', 'Injected', 'draft', 'standalone', 1)"
            ))


@pytest.mark.postgres
def test_cross_tenant_insert_denied_customers(pg_engine):
    """INSERT into customers with wrong tenant_id is denied by WITH CHECK."""
    with pytest.raises(Exception, match="new row violates row-level security|policy"):
        with pg_engine.begin() as conn:
            _set_guc(conn, 2)
            conn.execute(text(
                "INSERT INTO customers (display_name, tenant_id) "
                "VALUES ('Injected', 1)"
            ))


# ---------------------------------------------------------------------------
# Delete-denial tests (DELETE on another tenant's rows returns 0 affected)
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_cross_tenant_delete_denied_videos(seeded_rows, pg_engine):
    """Tenant 2 attempting DELETE on tenant 1's video sees 0 affected rows."""
    vid_id = seeded_rows["video_id"]
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        result = conn.execute(text(
            "DELETE FROM videos WHERE id = :id"
        ), {"id": vid_id})
        assert result.rowcount == 0, (
            f"DELETE should affect 0 rows (RLS blocks it); got {result.rowcount}"
        )

    # Verify the row still exists from tenant 1's perspective
    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        count = conn.execute(text(
            "SELECT COUNT(*) FROM videos WHERE id = :id"
        ), {"id": vid_id}).scalar()
    assert count == 1, "Row should still exist after failed cross-tenant DELETE"


@pytest.mark.postgres
def test_cross_tenant_delete_denied_articles(seeded_rows, pg_engine):
    """Tenant 2 attempting DELETE on tenant 1's article sees 0 affected rows."""
    slug = seeded_rows["article_slug"]
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        result = conn.execute(text(
            "DELETE FROM articles WHERE slug = :slug"
        ), {"slug": slug})
        assert result.rowcount == 0

    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        count = conn.execute(text(
            "SELECT COUNT(*) FROM articles WHERE slug = :slug"
        ), {"slug": slug}).scalar()
    assert count == 1


@pytest.mark.postgres
def test_cross_tenant_delete_denied_customers(seeded_rows, pg_engine):
    """Tenant 2 attempting DELETE on tenant 1's customer sees 0 affected rows."""
    cid = seeded_rows["customer_id"]
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        result = conn.execute(text(
            "DELETE FROM customers WHERE id = :id"
        ), {"id": cid})
        assert result.rowcount == 0


@pytest.mark.postgres
def test_cross_tenant_delete_denied_proposals(seeded_rows, pg_engine):
    """Tenant 2 attempting DELETE on tenant 1's proposal sees 0 affected rows."""
    pid = seeded_rows["proposal_id"]
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        result = conn.execute(text(
            "DELETE FROM proposals WHERE id = :id"
        ), {"id": pid})
        assert result.rowcount == 0


# ---------------------------------------------------------------------------
# Correct-tenant positive-path (verifies RLS allows own-tenant reads)
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_own_tenant_can_read_videos(seeded_rows, pg_engine):
    """Tenant 1 with GUC=1 can read its own video."""
    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        count = conn.execute(text(
            "SELECT COUNT(*) FROM videos WHERE id = :id"
        ), {"id": seeded_rows["video_id"]}).scalar()
    assert count == 1


@pytest.mark.postgres
def test_own_tenant_can_read_articles(seeded_rows, pg_engine):
    """Tenant 1 with GUC=1 can read its own article."""
    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        count = conn.execute(text(
            "SELECT COUNT(*) FROM articles WHERE slug = :slug"
        ), {"slug": seeded_rows["article_slug"]}).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# GUC unset → current_setting raises (intentional — loud failure in prod)
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_unset_guc_raises_on_rls_table(pg_engine):
    """Querying a table with RLS when app.tenant_id is not set raises an error."""
    with pytest.raises(Exception):
        with pg_engine.begin() as conn:
            # Reset any GUC that may have been set in a prior subtransaction
            conn.execute(text("RESET app.tenant_id"))
            conn.execute(text("SELECT * FROM videos"))
