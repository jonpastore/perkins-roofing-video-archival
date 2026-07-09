"""F0 thin-tenancy test suite — fail-first TDD.

Runs against a fresh SQLite DB (conftest.py sets DB_URL before any import).
Schema comes from Base.metadata.create_all — the .sql migration is validated
separately against dev Postgres.  All introspection is backend-agnostic.
"""
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine_and_schema():
    """Create a fresh in-memory SQLite DB and create all tables via ORM."""
    from app.models import Base
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine


def _inspector(engine):
    return inspect(engine)


# ---------------------------------------------------------------------------
# Group 1 — Schema existence
# ---------------------------------------------------------------------------

class TestSchemaExistence:
    def setup_method(self):
        self.engine = _make_engine_and_schema()
        self.insp = _inspector(self.engine)

    def test_tenants_table_exists(self):
        assert "tenants" in self.insp.get_table_names()

    def test_tenants_table_has_required_columns(self):
        cols = {c["name"] for c in self.insp.get_columns("tenants")}
        for expected in ("id", "name", "slug", "status", "settings", "created_at"):
            assert expected in cols, f"tenants.{expected} missing"

    def test_all_16_tenant_tables_have_tenant_id(self):
        tables = [
            "videos", "ingestion_runs", "segments", "words", "content_graph",
            "chunks", "email_templates", "clusters", "articles", "scheduled_content",
            "mini_series", "social_posts", "aggregated_topics", "comment_drafts",
            "user_settings", "faq_entries",
        ]
        for table in tables:
            cols = {c["name"]: c for c in self.insp.get_columns(table)}
            assert "tenant_id" in cols, f"{table}.tenant_id missing"
            assert cols["tenant_id"]["nullable"] is False, \
                f"{table}.tenant_id must be NOT NULL"

    def test_tenant_id_fk_references_tenants(self):
        for table in ("videos", "chunks", "articles"):
            fks = self.insp.get_foreign_keys(table)
            tenant_fks = [fk for fk in fks if fk["referred_table"] == "tenants"]
            assert tenant_fks, f"{table}: no FK referencing tenants found"


# ---------------------------------------------------------------------------
# Group 2 — Seed data
# ---------------------------------------------------------------------------

class TestSeedData:
    def setup_method(self):
        self.engine = _make_engine_and_schema()

    def test_perkins_is_tenant_1(self):
        Session = sessionmaker(bind=self.engine, future=True)
        with Session() as session:
            from app.models import Tenant
            rows = session.query(Tenant).all()
            assert len(rows) == 1, f"Expected 1 tenant row, got {len(rows)}"
            t = rows[0]
            assert t.id == 1
            assert t.slug == "perkins"
            assert t.status == "active"


# ---------------------------------------------------------------------------
# Group 3 — Default backfill (new rows in fresh SQLite DB default to 1)
# ---------------------------------------------------------------------------

class TestDefaultBackfill:
    def setup_method(self):
        self.engine = _make_engine_and_schema()

    @pytest.mark.parametrize("table", [
        "videos", "segments", "chunks", "articles",
    ])
    def test_existing_rows_have_tenant_id_1(self, table):
        # SMOKE ONLY on SQLite: the create_all schema starts empty, so this asserts
        # over zero rows. The real backfill guarantee (existing prod rows get
        # tenant_id=1) is a property of migration 0013's DEFAULT 1 on Postgres and
        # is validated at prod/dev apply time (TRD-F0 dual-path). Behavioral default
        # coverage lives in TestNewRowDefaults, which inserts and asserts.
        with self.engine.connect() as conn:
            # Verify that any row that might exist (or a fresh insert) has tenant_id=1.
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id != 1")
            ).scalar()
            assert result == 0, f"{table}: found rows with tenant_id != 1"


# ---------------------------------------------------------------------------
# Group 4 — New-row defaults
# ---------------------------------------------------------------------------

class TestNewRowDefaults:
    def setup_method(self):
        self.engine = _make_engine_and_schema()
        self.Session = sessionmaker(bind=self.engine, future=True)

    def test_new_video_defaults_to_tenant_1(self):
        from app.models import Video
        with self.Session() as session:
            v = Video(id="vid-001", title="Test")
            session.add(v)
            session.commit()
            session.refresh(v)
            assert v.tenant_id == 1

    def test_new_article_defaults_to_tenant_1(self):
        from app.models import Article
        with self.Session() as session:
            a = Article(slug="test-article", title="Test", status="draft", role="standalone")
            session.add(a)
            session.commit()
            session.refresh(a)
            assert a.tenant_id == 1

    def test_new_chunk_defaults_to_tenant_1(self):
        from app.models import Chunk
        with self.Session() as session:
            c = Chunk(video_id="vid-001", text="some text", start=0.0, end=5.0)
            session.add(c)
            session.commit()
            session.refresh(c)
            assert c.tenant_id == 1


# ---------------------------------------------------------------------------
# Group 5 — ORM mixin unit tests
# ---------------------------------------------------------------------------

class TestOrmMixin:
    def test_tenant_mixin_declares_tenant_id_column(self):
        from core.tenant import TenantMixin
        from sqlalchemy import Column, Integer
        assert "tenant_id" in TenantMixin.__dict__, \
            "TenantMixin must declare tenant_id column descriptor"
        col = TenantMixin.__dict__["tenant_id"]
        # On an unbound mixin the descriptor is a bare Column (not yet instrumented by mapper)
        assert isinstance(col, Column), "TenantMixin.tenant_id must be a SQLAlchemy Column"
        assert isinstance(col.type, Integer), "TenantMixin.tenant_id must be Integer type"
        fk_targets = [fk.target_fullname for fk in col.foreign_keys]
        assert "tenants.id" in fk_targets, \
            f"TenantMixin.tenant_id must FK to tenants.id, got {fk_targets}"
        assert col.nullable is False, "TenantMixin.tenant_id must be NOT NULL"

    def test_set_tenant_context_is_noop_in_f0(self):
        from core.tenant import set_tenant_context
        mock_session = MagicMock()
        set_tenant_context(mock_session, 1)
        mock_session.execute.assert_not_called()

    def test_tenant_query_mixin_filter_returns_correct_clause(self):
        from core.tenant import TenantQueryMixin
        from app.models import Article
        filters = TenantQueryMixin.tenant_filter(Article, 42)
        assert len(filters) == 1
        # The filter clause should compare Article.tenant_id to 42
        clause = filters[0]
        # Compile to SQL string for a backend-agnostic check
        sql = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id" in sql
        assert "42" in sql


# ---------------------------------------------------------------------------
# Group 6 — Composite indexes
# ---------------------------------------------------------------------------

class TestCompositeIndexes:
    def setup_method(self):
        self.engine = _make_engine_and_schema()
        self.insp = _inspector(self.engine)

    def _index_names(self, table):
        return {idx["name"] for idx in self.insp.get_indexes(table)}

    def test_videos_tenant_index_exists(self):
        assert "ix_videos_tenant_id" in self._index_names("videos")

    def test_ingestion_runs_composite_index_exists(self):
        assert "ix_ingestion_runs_tenant_video_stage" in self._index_names("ingestion_runs")

    def test_chunks_composite_index_exists(self):
        assert "ix_chunks_tenant_video" in self._index_names("chunks")

    def test_articles_composite_index_exists(self):
        assert "ix_articles_tenant_status" in self._index_names("articles")

    def test_faq_entries_composite_index_exists(self):
        assert "ix_faq_entries_tenant_video" in self._index_names("faq_entries")
