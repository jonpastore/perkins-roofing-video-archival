"""The migration statement splitter must not cut a statement in half.

A bad split does not fail loudly at the split — it sends Postgres a fragment, which aborts the
run and leaves every LATER migration unapplied while the earlier ones are already committed.
That is how 0046 silently blocked 0047-0052 from ever reaching prod.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from apply_migrations_connector import _statements  # noqa: E402


def test_semicolon_inside_string_literal_does_not_split():
    """0046's real column comment — the semicolon is inside the quoted string."""
    sql = (
        "COMMENT ON COLUMN measurements.flat_squares IS "
        "'RoofR flat_sqft / 100. NULL = split unknown; 0 = no flat section.';"
    )
    stmts = list(_statements(sql))
    assert len(stmts) == 1, stmts
    assert stmts[0].endswith("no flat section.'")


def test_escaped_quote_inside_string_literal():
    sql = "INSERT INTO t (a) VALUES ('it''s here; really');"
    stmts = list(_statements(sql))
    assert len(stmts) == 1, stmts
    assert "it''s here; really" in stmts[0]


def test_double_dash_inside_string_is_not_a_comment():
    """The old line-based pre-strip truncated the literal here."""
    sql = "INSERT INTO t (a) VALUES ('a -- not a comment');"
    stmts = list(_statements(sql))
    assert len(stmts) == 1, stmts
    assert "a -- not a comment" in stmts[0]


def test_dollar_quoted_block_keeps_its_semicolons():
    sql = (
        "DO $$\nBEGIN\n  IF NOT EXISTS (SELECT 1 FROM pg_constraint) THEN\n"
        "    ALTER TABLE t ADD CONSTRAINT c UNIQUE (a);\n  END IF;\nEND $$;\n"
        "CREATE INDEX IF NOT EXISTS i ON t (a);"
    )
    stmts = list(_statements(sql))
    assert len(stmts) == 2, stmts
    assert stmts[0].startswith("DO $$")
    assert stmts[1].startswith("CREATE INDEX")


def test_line_comment_is_stripped_and_its_semicolon_ignored():
    sql = "-- a comment; with a semicolon\nSELECT 1;\nSELECT 2;"
    stmts = list(_statements(sql))
    assert len(stmts) == 2, stmts
    assert stmts[0] == "SELECT 1"


def test_every_real_migration_splits_with_balanced_quotes():
    """No statement we would send to Postgres may carry an odd number of quotes."""
    for path in sorted((ROOT / "infra" / "migrations").glob("*.sql")):
        for stmt in _statements(path.read_text()):
            without_escapes = stmt.replace("''", "")
            assert without_escapes.count("'") % 2 == 0, f"{path.name}: {stmt[:120]}"
            assert stmt.count("$$") % 2 == 0, f"{path.name}: {stmt[:120]}"


def test_tagged_dollar_quote_keeps_its_semicolons():
    """`$func$ ... $func$` is as much a dollar-quote as `$$`. No migration uses one TODAY —
    which is exactly why this is a test and not a comment."""
    sql = (
        "CREATE FUNCTION f() RETURNS void AS $func$\n"
        "BEGIN\n  UPDATE t SET a = 1;\n  UPDATE t SET b = 2;\nEND\n$func$ LANGUAGE plpgsql;\n"
        "CREATE INDEX IF NOT EXISTS i ON t (a);"
    )
    stmts = list(_statements(sql))
    assert len(stmts) == 2, stmts
    assert "UPDATE t SET b = 2" in stmts[0]
    assert stmts[1].startswith("CREATE INDEX")


def test_a_different_tag_does_not_close_a_dollar_block():
    """Only the SAME tag closes. A `$$` inside a `$func$` body must not end it."""
    sql = "DO $func$ BEGIN PERFORM '$$'; END $func$;\nSELECT 1;"
    stmts = list(_statements(sql))
    assert len(stmts) == 2, stmts
    assert stmts[1] == "SELECT 1"


def test_a_bare_dollar_is_not_a_delimiter():
    """A lone `$` must fall through as text, not toggle the scanner into a block it never exits."""
    sql = "INSERT INTO t (a) VALUES ('cost is $5 total');\nSELECT 2;"
    stmts = list(_statements(sql))
    assert len(stmts) == 2, stmts
    assert stmts[1] == "SELECT 2"
