"""Knowify XLS customer/catalog import script (Wave F3).

Re-runnable/idempotent — safe to run multiple times against the same DB.
Upserts on (tenant_id, knowify_customer_id) so duplicate runs do not
create duplicate rows.

COLUMN_MAP constants at the top are flagged PENDING-JOSH — update them to
match the actual column headers in Tim's Knowify export before first run.

Usage:
    python scripts/knowify_import.py \\
        --customers-xls path/to/customers.xlsx \\
        --tenant-id 1 \\
        [--dry-run]

Direct API (used by tests):
    from knowify_import import run
    result = run(customers_xls="...", db_url="sqlite:///...", tenant_id=1)
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Column map constants — PENDING-JOSH: verify against real Knowify XLS export.
# Update these string values to match the actual header row before first run.
# ---------------------------------------------------------------------------
CUSTOMERS_COLUMN_MAP: dict[str, str] = {
    "name_col": "Name",                # → customers.display_name  (REQUIRED)
    "company_col": "Company",          # → customers.company_name
    "email_col": "Email",              # → customers.email
    "phone_col": "Phone",              # → customers.phone
    "knowify_id_col": "Knowify ID",    # → customers.knowify_customer_id
    "county_col": "County",            # → properties.county → code_zone
    "street_col": "Street",            # → properties.street
    "city_col": "City",                # → properties.city
    "zip_col": "Zip",                  # → properties.zip
}

# County → code_zone mapping (per TRD §3.9 and Florida Building Code zones).
COUNTY_TO_CODE_ZONE: dict[str, str] = {
    "miami-dade": "HVHZ",
    "broward": "HVHZ",
    "palm beach": "FBC",
    "lee": "FBC",
    "st. lucie": "FBC",
    "saint lucie": "FBC",
}


def _county_to_code_zone(county: str | None) -> str:
    if not county:
        return "FBC"
    return COUNTY_TO_CODE_ZONE.get(county.strip().lower(), "FBC")


# ---------------------------------------------------------------------------
# SQLite/SQLAlchemy upsert helpers
# ---------------------------------------------------------------------------

def _upsert_customer(
    conn: Any,
    tenant_id: int,
    display_name: str,
    company_name: str | None,
    email: str | None,
    phone: str | None,
    knowify_id: str | None,
    dry_run: bool,
) -> int | None:
    """Insert or update a customer row. Returns the customer id (or None on dry-run)."""
    if dry_run:
        return None

    # Check if customer already exists by knowify_id
    if knowify_id:
        row = conn.execute(
            "SELECT id FROM customers WHERE tenant_id = ? AND knowify_customer_id = ?",
            (tenant_id, knowify_id),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE customers SET display_name=?, company_name=?, email=?, phone=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE tenant_id=? AND knowify_customer_id=?",
                (display_name, company_name, email, phone, tenant_id, knowify_id),
            )
            return row[0]

    # Insert new
    cursor = conn.execute(
        "INSERT INTO customers (tenant_id, display_name, company_name, email, phone, knowify_customer_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, display_name, company_name, email, phone, knowify_id),
    )
    return cursor.lastrowid


def _upsert_property(
    conn: Any,
    tenant_id: int,
    customer_id: int,
    street: str,
    city: str,
    county: str | None,
    zip_code: str | None,
    knowify_id: str | None,
    dry_run: bool,
) -> None:
    if dry_run:
        return

    code_zone = _county_to_code_zone(county)

    # Check existing property for this customer (by knowify_id or customer_id)
    row = conn.execute(
        "SELECT id FROM properties WHERE tenant_id = ? AND customer_id = ? LIMIT 1",
        (tenant_id, customer_id),
    ).fetchone()

    if row:
        conn.execute(
            "UPDATE properties SET street=?, city=?, county=?, zip=?, code_zone=?, "
            "knowify_customer_id=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (street, city, county, zip_code, code_zone, knowify_id, row[0]),
        )
    else:
        conn.execute(
            "INSERT INTO properties (tenant_id, customer_id, street, city, state, zip, county, "
            "code_zone, knowify_customer_id) VALUES (?, ?, ?, ?, 'FL', ?, ?, ?, ?)",
            (tenant_id, customer_id, street, city, zip_code, county, code_zone, knowify_id),
        )


# ---------------------------------------------------------------------------
# SQLAlchemy-aware upsert (for use with real app DB URL via SQLAlchemy)
# ---------------------------------------------------------------------------

def _get_sqlalchemy_conn(db_url: str):
    """Return a sqlite3 or SQLAlchemy raw connection depending on db_url."""
    if db_url.startswith("sqlite:///"):
        import sqlite3  # noqa: PLC0415
        path = db_url[len("sqlite:///"):]
        return sqlite3.connect(path), "sqlite3"
    # PostgreSQL via SQLAlchemy
    from sqlalchemy import create_engine  # noqa: PLC0415
    engine = create_engine(db_url)
    return engine.connect(), "sqlalchemy"


# ---------------------------------------------------------------------------
# Core import logic
# ---------------------------------------------------------------------------

def run(
    customers_xls: str,
    db_url: str,
    tenant_id: int = 1,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the Knowify XLS import.

    Args:
        customers_xls: Path to the Knowify customers XLSX file.
        db_url: SQLAlchemy-style database URL (sqlite:/// or postgresql://...).
        tenant_id: Target tenant ID for imported records.
        dry_run: If True, read the XLS and report what would be imported
                 but write nothing to the database.

    Returns:
        Summary dict with keys:
            customers_imported, customers_skipped, customers_would_import (dry_run),
            dry_run.
    """
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.load_workbook(str(customers_xls), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {"customers_imported": 0, "customers_skipped": 0, "dry_run": dry_run}

    # Detect header row
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col = CUSTOMERS_COLUMN_MAP

    def _col_idx(col_name: str) -> int | None:
        try:
            return header.index(col_name)
        except ValueError:
            return None

    name_idx = _col_idx(col["name_col"])
    company_idx = _col_idx(col["company_col"])
    email_idx = _col_idx(col["email_col"])
    phone_idx = _col_idx(col["phone_col"])
    knowify_idx = _col_idx(col["knowify_id_col"])
    county_idx = _col_idx(col["county_col"])
    street_idx = _col_idx(col["street_col"])
    city_idx = _col_idx(col["city_col"])
    zip_idx = _col_idx(col["zip_col"])

    def _cell(row: tuple, idx: int | None) -> str | None:
        if idx is None or idx >= len(row):
            return None
        v = row[idx]
        return str(v).strip() if v is not None else None

    conn, conn_type = _get_sqlalchemy_conn(db_url)

    imported = 0
    skipped = 0
    would_import = 0

    try:
        for row in rows[1:]:
            display_name = _cell(row, name_idx)
            if not display_name:
                skipped += 1
                continue

            company = _cell(row, company_idx)
            email = _cell(row, email_idx)
            phone = _cell(row, phone_idx)
            knowify_id = _cell(row, knowify_idx)
            county = _cell(row, county_idx)
            street = _cell(row, street_idx) or ""
            city = _cell(row, city_idx) or ""
            zip_code = _cell(row, zip_idx)

            if dry_run:
                would_import += 1
                continue

            customer_id = _upsert_customer(
                conn=conn,
                tenant_id=tenant_id,
                display_name=display_name,
                company_name=company,
                email=email,
                phone=phone,
                knowify_id=knowify_id,
                dry_run=False,
            )

            if customer_id and county:
                _upsert_property(
                    conn=conn,
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    street=street,
                    city=city,
                    county=county,
                    zip_code=zip_code,
                    knowify_id=knowify_id,
                    dry_run=False,
                )

            imported += 1

        if not dry_run and conn_type == "sqlite3":
            conn.commit()
        elif not dry_run and conn_type == "sqlalchemy":
            conn.commit()

    finally:
        conn.close()

    return {
        "customers_imported": imported,
        "customers_skipped": skipped,
        "customers_would_import": would_import,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import Knowify XLS customers into the platform DB")
    p.add_argument("--customers-xls", required=True, help="Path to Knowify customers XLSX file")
    p.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""), help="SQLAlchemy DB URL")
    p.add_argument("--tenant-id", type=int, default=1, help="Target tenant ID")
    p.add_argument("--dry-run", action="store_true", help="Print plan without writing to DB")
    return p.parse_args(argv)


if __name__ == "__main__":
    import os  # noqa: PLC0415 — only needed in __main__
    args = _parse_args()
    if not args.db_url:
        print("ERROR: --db-url or DATABASE_URL env var required", file=sys.stderr)
        sys.exit(1)
    result = run(
        customers_xls=args.customers_xls,
        db_url=args.db_url,
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"DRY RUN: would import {result['customers_would_import']} customers")
    else:
        print(
            f"Imported: {result['customers_imported']} customers, "
            f"skipped: {result['customers_skipped']}"
        )
