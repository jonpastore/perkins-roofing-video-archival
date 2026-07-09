"""TDD tests for scripts/knowify_import.py — golden-file XLS import tests.

Fixture: tests/fixtures/knowify_sample.xlsx — synthetic 3-row XLS created by
the test module itself (via openpyxl) so no binary blob is committed.

Tests:
- Import creates correct customers
- County → code_zone mapping (Miami-Dade → HVHZ; Palm Beach → FBC)
- Upsert idempotency on re-run
- Dry-run flag writes nothing
- Rows missing display_name are skipped and counted
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl required for Knowify import tests")


# ---------------------------------------------------------------------------
# Fixture factory — builds the XLSX in memory for each test
# ---------------------------------------------------------------------------

def _make_xlsx(tmp_path: Path) -> Path:
    """Create a minimal 3-row knowify customers XLSX with columns matching the import script."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"

    # Header row matching COLUMN_MAP in knowify_import.py
    ws.append(["Name", "Company", "Email", "Phone", "Knowify ID", "County"])
    # Row 1: Miami-Dade → HVHZ
    ws.append(["Alice Johnson", "Johnson Roofing LLC", "alice@example.com", "555-0001", "KN-001", "Miami-Dade"])
    # Row 2: Palm Beach → FBC
    ws.append(["Bob Smith", "Smith Contracting", "bob@example.com", "555-0002", "KN-002", "Palm Beach"])
    # Row 3: Broward → HVHZ
    ws.append(["Carol Davis", None, "carol@example.com", "555-0003", "KN-003", "Broward"])

    path = tmp_path / "knowify_sample.xlsx"
    wb.save(str(path))
    return path


def _make_xlsx_with_missing_name(tmp_path: Path) -> Path:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Company", "Email", "Phone", "Knowify ID", "County"])
    ws.append([None, "No Name Corp", "noname@example.com", "555-0099", "KN-099", "Broward"])
    ws.append(["Valid Person", "VP Corp", "vp@example.com", "555-0100", "KN-100", "Miami-Dade"])
    path = tmp_path / "missing_name.xlsx"
    wb.save(str(path))
    return path


# ---------------------------------------------------------------------------
# SQLite in-memory DB fixture (simulates app DB schema for customers table)
# ---------------------------------------------------------------------------

@pytest.fixture()
def sqlite_db(tmp_path):
    """In-memory SQLite DB with the customers and properties schema from F3 §1."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            company_name TEXT,
            email TEXT,
            phone TEXT,
            knowify_customer_id TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            street TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'FL',
            zip TEXT,
            county TEXT,
            code_zone TEXT NOT NULL DEFAULT 'FBC',
            knowify_customer_id TEXT,
            gcs_pdf_prefix TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    yield conn, str(db_path)
    conn.close()


# ---------------------------------------------------------------------------
# Import helper: runs knowify_import.main() with args
# ---------------------------------------------------------------------------

def _run_import(xlsx_path: str, db_path: str, tenant_id: int = 1,
                dry_run: bool = False) -> dict:
    """Import knowify_import and call its run() function directly."""
    import importlib
    import knowify_import as ki
    importlib.reload(ki)  # ensure clean state between tests

    return ki.run(
        customers_xls=xlsx_path,
        db_url=f"sqlite:///{db_path}",
        tenant_id=tenant_id,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKnowifyImportCreatesCustomers:
    def test_import_creates_three_customers(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)
        result = _run_import(str(xlsx), db_path)

        rows = conn.execute("SELECT display_name, knowify_customer_id FROM customers ORDER BY id").fetchall()
        assert len(rows) == 3
        assert result["customers_imported"] == 3

    def test_import_correct_display_names(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)
        _run_import(str(xlsx), db_path)

        names = {r[0] for r in conn.execute("SELECT display_name FROM customers").fetchall()}
        assert "Alice Johnson" in names
        assert "Bob Smith" in names
        assert "Carol Davis" in names

    def test_import_correct_knowify_ids(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)
        _run_import(str(xlsx), db_path)

        ids = {r[0] for r in conn.execute("SELECT knowify_customer_id FROM customers").fetchall()}
        assert "KN-001" in ids
        assert "KN-002" in ids
        assert "KN-003" in ids


class TestCountyToCodeZoneMapping:
    def test_miami_dade_maps_to_hvhz(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)
        _run_import(str(xlsx), db_path)

        # Alice Johnson → Miami-Dade → HVHZ
        row = conn.execute(
            "SELECT p.code_zone FROM properties p "
            "JOIN customers c ON c.id = p.customer_id "
            "WHERE c.knowify_customer_id = 'KN-001'"
        ).fetchone()
        assert row is not None
        assert row[0] == "HVHZ"

    def test_palm_beach_maps_to_fbc(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)
        _run_import(str(xlsx), db_path)

        row = conn.execute(
            "SELECT p.code_zone FROM properties p "
            "JOIN customers c ON c.id = p.customer_id "
            "WHERE c.knowify_customer_id = 'KN-002'"
        ).fetchone()
        assert row is not None
        assert row[0] == "FBC"

    def test_broward_maps_to_hvhz(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)
        _run_import(str(xlsx), db_path)

        row = conn.execute(
            "SELECT p.code_zone FROM properties p "
            "JOIN customers c ON c.id = p.customer_id "
            "WHERE c.knowify_customer_id = 'KN-003'"
        ).fetchone()
        assert row is not None
        assert row[0] == "HVHZ"


class TestUpsertIdempotency:
    def test_import_twice_does_not_duplicate(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)

        _run_import(str(xlsx), db_path)
        _run_import(str(xlsx), db_path)

        count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        assert count == 3  # not 6

    def test_import_twice_preserves_data(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)

        _run_import(str(xlsx), db_path)
        r2 = _run_import(str(xlsx), db_path)

        # Second run: all rows upserted (not errored)
        assert r2["customers_imported"] == 3


class TestDryRun:
    def test_dry_run_writes_no_rows(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)

        result = _run_import(str(xlsx), db_path, dry_run=True)

        count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        assert count == 0
        assert result["dry_run"] is True

    def test_dry_run_still_reports_plan(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx(tmp_path)

        result = _run_import(str(xlsx), db_path, dry_run=True)
        assert result["customers_would_import"] == 3


class TestSkipMissingName:
    def test_rows_missing_name_are_skipped(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx_with_missing_name(tmp_path)

        result = _run_import(str(xlsx), db_path)

        count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        assert count == 1  # only Valid Person
        assert result["customers_skipped"] >= 1

    def test_summary_counts_skipped(self, tmp_path, sqlite_db):
        conn, db_path = sqlite_db
        xlsx = _make_xlsx_with_missing_name(tmp_path)
        result = _run_import(str(xlsx), db_path)
        assert result["customers_skipped"] == 1
