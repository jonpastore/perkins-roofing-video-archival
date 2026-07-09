"""TDD tests for scripts/apply_migrations_connector.py _statements() — RED FIRST.

Verifies dollar-quote-aware SQL splitting so DO $$ ... $$; blocks are never
fragmented into invalid SQL. All tests run without DB access.
"""
import os
import sys

# _statements lives in a script, not a package — import via path manipulation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from apply_migrations_connector import _statements

# ---------------------------------------------------------------------------
# Basic sanity
# ---------------------------------------------------------------------------

class TestBasicSplitting:
    def test_single_statement_no_semicolon(self):
        sql = "SELECT 1"
        stmts = list(_statements(sql))
        assert stmts == ["SELECT 1"]

    def test_single_statement_with_trailing_semicolon(self):
        sql = "SELECT 1;"
        stmts = list(_statements(sql))
        assert stmts == ["SELECT 1"]

    def test_two_statements(self):
        sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT);"
        stmts = list(_statements(sql))
        assert len(stmts) == 2

    def test_comment_stripped(self):
        sql = "-- this is a comment\nSELECT 1;"
        stmts = list(_statements(sql))
        assert stmts == ["SELECT 1"]

    def test_inline_comment_stripped(self):
        sql = "SELECT 1; -- inline\nSELECT 2;"
        stmts = list(_statements(sql))
        assert len(stmts) == 2

    def test_blank_lines_ignored(self):
        sql = "\n\n SELECT 1 ;\n\n"
        stmts = list(_statements(sql))
        assert stmts == ["SELECT 1"]


# ---------------------------------------------------------------------------
# Dollar-quote: DO $$ block with internal semicolons must yield exactly 1 stmt
# ---------------------------------------------------------------------------

class TestDollarQuote:
    def test_do_block_yields_one_statement(self):
        """DO $$ ... $$; with internal semicolons must NOT be fragmented."""
        sql = """\
DO $$ BEGIN
    CREATE TYPE proposal_status AS ENUM (
        'draft',
        'sent'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;"""
        stmts = list(_statements(sql))
        assert len(stmts) == 1, (
            f"Expected 1 statement from DO $$ block, got {len(stmts)}: {stmts}"
        )

    def test_do_block_fragment_not_exception(self):
        """No fragment starting with 'EXCEPTION' — that means mid-block split."""
        sql = """\
DO $$ BEGIN
    CREATE TYPE foo AS ENUM ('a', 'b');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;"""
        stmts = list(_statements(sql))
        for s in stmts:
            assert not s.strip().upper().startswith("EXCEPTION"), (
                f"Got EXCEPTION fragment — dollar-quote splitting is broken: {s!r}"
            )

    def test_do_block_no_end_fragment(self):
        """No fragment that is just 'END $$' — that means mid-block split."""
        sql = """\
DO $$ BEGIN
    CREATE TYPE bar AS ENUM ('x');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;"""
        stmts = list(_statements(sql))
        for s in stmts:
            assert "END $$" not in s or s.strip().startswith("DO"), (
                f"Got bare END $$ fragment: {s!r}"
            )

    def test_multiple_do_blocks_counted_correctly(self):
        """Three DO $$ blocks → exactly 3 statements (no extra fragments)."""
        sql = """\
DO $$ BEGIN
    CREATE TYPE t1 AS ENUM ('a');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE t2 AS ENUM ('b');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE t3 AS ENUM ('c');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;"""
        stmts = list(_statements(sql))
        assert len(stmts) == 3, (
            f"Expected 3 DO $$ blocks, got {len(stmts)}: {stmts}"
        )

    def test_mixed_file_normal_and_do_blocks(self):
        """Mix of normal statements + DO $$ blocks: count and no EXCEPTION/END $$ fragments."""
        sql = """\
-- comment
CREATE TABLE IF NOT EXISTS customers (id SERIAL PRIMARY KEY);

DO $$ BEGIN
    CREATE TYPE proposal_status AS ENUM ('draft', 'sent');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_foo ON customers(id);

DO $$ BEGIN
    CREATE TYPE lead_status AS ENUM ('new', 'lost');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
        stmts = list(_statements(sql))
        # Expect: CREATE TABLE, DO block 1, CREATE INDEX, DO block 2 → 4
        assert len(stmts) == 4, (
            f"Expected 4 statements, got {len(stmts)}: {stmts}"
        )
        for s in stmts:
            upper = s.strip().upper()
            assert not upper.startswith("EXCEPTION"), f"EXCEPTION fragment: {s!r}"
            assert not upper.startswith("END $$"), f"END $$ fragment: {s!r}"


# ---------------------------------------------------------------------------
# Real 0017_quoting.sql — assert no fragments
# ---------------------------------------------------------------------------

class TestRealMigration0017:
    def _load_0017(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "infra", "migrations", "0017_quoting.sql"
        )
        with open(path) as f:
            return f.read()

    def test_0017_no_exception_fragments(self):
        """Running _statements over 0017_quoting.sql produces no EXCEPTION-start fragments."""
        sql = self._load_0017()
        stmts = list(_statements(sql))
        for s in stmts:
            assert not s.strip().upper().startswith("EXCEPTION"), (
                f"EXCEPTION fragment from 0017: {s!r}"
            )

    def test_0017_no_bare_end_dollar_dollar(self):
        """No statement is just 'END $$' — which would indicate a split inside a DO block."""
        sql = self._load_0017()
        stmts = list(_statements(sql))
        for s in stmts:
            stripped = s.strip()
            # A bare "END $$" or "END $$" alone (possibly with whitespace) is a split artifact
            if stripped.upper().startswith("END $$"):
                assert stripped.upper().startswith("DO"), (
                    f"Bare END $$ fragment from 0017: {s!r}"
                )

    def test_0017_statement_count_reasonable(self):
        """0017 should parse into at least 10 statements (tables + indexes + DO blocks)."""
        sql = self._load_0017()
        stmts = list(_statements(sql))
        assert len(stmts) >= 10, f"Only {len(stmts)} statements parsed from 0017"
