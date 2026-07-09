"""One-time Knowify historical PDF archive script (Wave F3).

Uploads a directory of historical proposal PDFs to GCS under per-property
prefixes. Safe to re-run — skips files already present in GCS.

Usage:
    python scripts/archive_knowify_pdfs.py \\
        --pdf-dir path/to/pdfs/ \\
        --bucket perkins-media \\
        --tenant-id 1 \\
        [--mapping-csv knowify_id,filename.csv] \\
        [--default-prefix tenants/1/properties/0/archive/] \\
        [--dry-run]

Column map constants at the top are flagged PENDING-JOSH.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path  # noqa: F401 — used in type hints via string literals

# PENDING-JOSH: verify these column names match the mapping CSV Tim provides.
MAPPING_CSV_COLUMNS = {
    "knowify_id_col": "knowify_id",
    "filename_col": "filename",
}

# GCS prefix template — tenants/{tenant_id}/properties/{property_id}/archive/
GCS_PREFIX_TEMPLATE = "tenants/{tenant_id}/properties/{property_id}/archive/"


def _load_mapping(mapping_csv: str) -> dict[str, str]:
    """Load {knowify_id → filename} mapping from CSV."""
    mapping: dict[str, str] = {}
    id_col = MAPPING_CSV_COLUMNS["knowify_id_col"]
    fn_col = MAPPING_CSV_COLUMNS["filename_col"]
    with open(mapping_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kid = row.get(id_col, "").strip()
            fname = row.get(fn_col, "").strip()
            if kid and fname:
                mapping[fname] = kid
    return mapping


def _gcs_blob_exists(bucket, blob_name: str) -> bool:
    blob = bucket.blob(blob_name)
    return blob.exists()


def run(
    pdf_dir: str,
    gcs_bucket: str,
    tenant_id: int = 1,
    mapping_csv: str | None = None,
    default_prefix: str | None = None,
    db_url: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Archive historical PDFs to GCS.

    Args:
        pdf_dir: Local directory containing historical PDF files.
        gcs_bucket: GCS bucket name (without gs:// prefix).
        tenant_id: Target tenant ID.
        mapping_csv: Optional CSV mapping knowify_id to filename.
        default_prefix: GCS prefix to use when property lookup fails.
            Defaults to tenants/{tenant_id}/properties/0/archive/.
        db_url: SQLAlchemy DB URL for property lookup. If None, uses
            the default_prefix for all files.
        dry_run: If True, print what would be uploaded without uploading.

    Returns:
        Summary dict with keys: uploaded, skipped, errors, dry_run.
    """
    from google.cloud import storage  # noqa: PLC0415

    pdf_path = Path(pdf_dir)
    if not pdf_path.is_dir():
        raise ValueError(f"pdf_dir does not exist or is not a directory: {pdf_dir}")

    pdf_files = sorted(pdf_path.glob("*.pdf"))
    if not pdf_files:
        return {"uploaded": 0, "skipped": 0, "errors": 0, "dry_run": dry_run}

    # Load optional mapping CSV
    fname_to_knowify: dict[str, str] = {}
    if mapping_csv:
        fname_to_knowify = _load_mapping(mapping_csv)

    # Build property lookup from DB if db_url provided
    prop_lookup: dict[str, str] = {}  # knowify_id → gcs_prefix
    if db_url:
        try:
            import sqlite3  # noqa: PLC0415
            if db_url.startswith("sqlite:///"):
                conn = sqlite3.connect(db_url[len("sqlite:///"):])
                rows = conn.execute(
                    "SELECT p.knowify_customer_id, p.gcs_pdf_prefix "
                    "FROM properties p WHERE p.tenant_id = ?",
                    (tenant_id,),
                ).fetchall()
                conn.close()
                for kid, prefix in rows:
                    if kid and prefix:
                        prop_lookup[kid] = prefix
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: DB lookup failed, using default prefix: {exc}", file=sys.stderr)

    _fallback_prefix = (
        default_prefix
        or GCS_PREFIX_TEMPLATE.format(tenant_id=tenant_id, property_id=0)
    )

    if not dry_run:
        client = storage.Client()
        bucket = client.bucket(gcs_bucket)
    else:
        bucket = None

    uploaded = skipped = errors = 0
    log_lines: list[str] = []

    for pdf_file in pdf_files:
        fname = pdf_file.name
        knowify_id = fname_to_knowify.get(fname)
        prefix = prop_lookup.get(knowify_id, _fallback_prefix) if knowify_id else _fallback_prefix
        blob_name = f"{prefix.rstrip('/')}/{fname}"

        if dry_run:
            log_lines.append(f"DRY RUN: would upload {fname} → gs://{gcs_bucket}/{blob_name}")
            uploaded += 1
            continue

        try:
            if _gcs_blob_exists(bucket, blob_name):
                log_lines.append(f"SKIP (exists): gs://{gcs_bucket}/{blob_name}")
                skipped += 1
                continue

            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(pdf_file), content_type="application/pdf")
            log_lines.append(f"UPLOADED: {fname} → gs://{gcs_bucket}/{blob_name} (knowify={knowify_id})")
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            log_lines.append(f"ERROR: {fname}: {exc}")
            errors += 1

    for line in log_lines:
        print(line)

    return {"uploaded": uploaded, "skipped": skipped, "errors": errors, "dry_run": dry_run}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Archive Knowify historical PDFs to GCS")
    p.add_argument("--pdf-dir", required=True, help="Directory containing historical PDF files")
    p.add_argument("--bucket", required=True, help="GCS bucket name")
    p.add_argument("--tenant-id", type=int, default=1)
    p.add_argument("--mapping-csv", help="CSV: knowify_id,filename")
    p.add_argument("--default-prefix", help="GCS prefix for unmatched files")
    p.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    result = run(
        pdf_dir=args.pdf_dir,
        gcs_bucket=args.bucket,
        tenant_id=args.tenant_id,
        mapping_csv=args.mapping_csv,
        default_prefix=args.default_prefix,
        db_url=args.db_url or None,
        dry_run=args.dry_run,
    )
    print(
        f"{'DRY RUN: ' if args.dry_run else ''}Uploaded: {result['uploaded']}, "
        f"Skipped: {result['skipped']}, Errors: {result['errors']}"
    )
