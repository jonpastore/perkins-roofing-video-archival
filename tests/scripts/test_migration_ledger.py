"""The migration runner must skip files it has already applied, and must not
default the target to production."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import migration_ledger as ML  # noqa: E402


def test_require_project_refuses_an_empty_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(SystemExit, match="refusing to default to prod"):
        ML.require_project()


def test_require_project_honours_the_explicit_target(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-other-project")
    assert ML.require_project() == "some-other-project"


def test_decide_applies_new_skips_recorded_and_refuses_a_changed_file():
    applied = {"0013_thin_tenancy.sql": "abc"}
    assert ML.decide("0014_new.sql", "fff", applied) == "apply"
    assert ML.decide("0013_thin_tenancy.sql", "abc", applied) == "skip"
    with pytest.raises(SystemExit, match="different checksum"):
        ML.decide("0013_thin_tenancy.sql", "CHANGED", applied)


def test_second_pass_skips_already_applied_files(tmp_path):
    """The defect: every run re-executed every file. After the first apply,
    a second pass against the same tree must execute nothing."""
    mig = tmp_path / "infra" / "migrations"
    mig.mkdir(parents=True)
    (mig / "0013_a.sql").write_text("CREATE TABLE t (id INT);")
    (mig / "0014_b.sql").write_text("INSERT INTO t VALUES (1);")

    db = tmp_path / "db.sqlite"

    def run_once() -> list[str]:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        ML.ensure_ledger(cur.execute, sqlite=True)
        conn.commit()
        cur.execute("SELECT filename, checksum FROM schema_migrations")
        applied = {row[0]: row[1] for row in cur.fetchall()}
        this_pass = []
        for path in sorted(mig.glob("*.sql")):
            name = path.name
            checksum = ML.file_checksum(path)
            if ML.decide(name, checksum, applied) == "skip":
                continue
            for stmt in path.read_text().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            ML.record_applied_sqlite(cur.execute, name, checksum)
            this_pass.append(name)
        conn.commit()
        conn.close()
        return this_pass

    first = run_once()
    second = run_once()
    assert first == ["0013_a.sql", "0014_b.sql"]
    assert second == []
    # And the INSERT ran once: t has one row, not two.
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    conn.close()
