#!/usr/bin/env python3
"""Backfill measurements.pitched_sq / flat_sq where RoofR already recorded the split (#429a).

WHY THIS EXISTS. `measurements.total_sq` is AMBIGUOUS by provenance: on Tim's sheet it is the
SLOPED area only, on a RoofR transcription it is pitched + flat. `core/estimator.py` sums
`num_squares + flat_squares`, so a quote built off an ambiguous total either double-bills the flat
section or prices it at the sloped rate. The server-side guard in `api/routes/estimator.py` makes
the wrong quote IMPOSSIBLE (422, or a `split_unknown` stamp); this backfill makes it UNNECESSARY,
by recording the split where it is already known.

⚠️ WHAT THIS IS *NOT*. Jarvis #429 originally described inferring the split for 890 sold contracts
by matching Knowify scope lines to measurements by address. That is a DIFFERENT population and a
different task (#429b, analysis): the 890 live in `knowify_raw_records`, are inferred from scope-line
DESCRIPTIONS, and never touch a price. This script does not infer anything. It copies a number
RoofR already measured, and it refuses any row where that number does not reconcile.

THE SOURCE IS AUTHORITATIVE, NOT INFERRED. `raw_payload.pitched_sqft` / `.flat_sqft` come from the
RoofR report itself. Verified on prod 2026-08-02: all 7 candidate rows reconcile to the CENT
(`pitched + flat == total_sq`, delta 0.00). Any row that does not reconcile within
`--tolerance` squares is skipped and reported, never guessed at.

ROLLBACK. `git revert` does not undo an UPDATE, so the pre-image (`id, total_sq, pitched_sq,
flat_sq`) is written to a shadow table BEFORE anything changes. The table is created with
`CREATE TABLE IF NOT EXISTS` **inside this script — deliberately NOT a migration**, because the
migration runner has no ledger and replays every file from 0013 on each run.

IDEMPOTENT. Only rows with `pitched_sq IS NULL` are touched, so a second run is a no-op.

R10 — reports BOTH directions: what changed, and what was deliberately left alone and why.

    # read-only by default; --apply is required to write
    .venv/bin/python scripts/backfill_measurement_split.py
    .venv/bin/python scripts/backfill_measurement_split.py --apply
    .venv/bin/python scripts/backfill_measurement_split.py --rollback   # restore from the shadow
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SHADOW = "measurements_split_backfill_preimage"


def _connect():
    """Cloud SQL connector under ADC, same path scripts/apply_migrations_adc.py uses.

    DB_URL is honoured when set so this can be pointed at a non-prod database — unlike the
    migration runner, which ignores it (see its header).
    """
    if os.environ.get("DB_URL"):
        from sqlalchemy import create_engine
        return create_engine(os.environ["DB_URL"]).raw_connection()
    from google.cloud import secretmanager
    from google.cloud.sql.connector import Connector
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")
    pw = secretmanager.SecretManagerServiceClient().access_secret_version(
        name=f"projects/{project}/secrets/db-password/versions/latest"
    ).payload.data.decode().strip()
    return Connector().connect(f"{project}:us-central1:{project}-pg", "pg8000",
                               user="app", password=pw, db="perkins")


def _candidates(cur):
    cur.execute("""
        select id, provider, total_sq, raw_payload
        from measurements
        where pitched_sq is null
        order by id
    """)
    return cur.fetchall()


def _split_from(raw) -> tuple[float, float] | None:
    """The RoofR split in SQUARES, or None when the report carries no split.

    RoofR reports square FEET; measurements are in squares (100 sqft). A row whose payload has
    neither key is not a failure — it is a manual or Solar-API entry that never had a split.
    """
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        return None
    if "pitched_sqft" not in raw and "flat_sqft" not in raw:
        return None
    return float(raw.get("pitched_sqft") or 0) / 100.0, float(raw.get("flat_sqft") or 0) / 100.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default is a read-only report)")
    ap.add_argument("--rollback", action="store_true", help="restore every row from the shadow table")
    ap.add_argument("--tolerance", type=float, default=0.01,
                    help="squares of slack allowed between pitched+flat and total_sq")
    args = ap.parse_args()

    conn = _connect()
    cur = conn.cursor()
    cur.execute("set app.tenant_id='1'")

    if args.rollback:
        cur.execute(f"select count(*) from information_schema.tables where table_name='{SHADOW}'")
        if not cur.fetchone()[0]:
            sys.exit(f"no shadow table {SHADOW} — nothing to roll back")
        cur.execute(f"""
            update measurements m set pitched_sq = s.pitched_sq, flat_sq = s.flat_sq
            from {SHADOW} s where s.id = m.id
        """)
        print(f"rolled back {cur.rowcount} row(s) to their pre-backfill values")
        conn.commit()
        return

    rows = _candidates(cur)
    apply_rows: list[tuple] = []
    skipped: list[tuple[int, str, str]] = []

    for mid, provider, total_sq, raw in rows:
        split = _split_from(raw)
        if split is None:
            skipped.append((mid, provider, "no split in raw_payload — nothing to copy, not inferred"))
            continue
        pitched, flat = split
        total = float(total_sq or 0)
        if abs((pitched + flat) - total) > args.tolerance:
            skipped.append((mid, provider,
                            f"does NOT reconcile: {pitched:.2f}+{flat:.2f}={pitched + flat:.2f} "
                            f"vs total_sq {total:.2f}"))
            continue
        apply_rows.append((mid, provider, total, pitched, flat))

    print(f"{len(rows)} measurement(s) with an unrecorded split\n")
    print(f"  BACKFILL {len(apply_rows)}:")
    for mid, provider, total, pitched, flat in apply_rows:
        print(f"    #{mid:<4} {provider:<14} total {total:>7.2f} -> pitched {pitched:>7.2f} "
              f"flat {flat:>6.2f}")
    print(f"\n  LEAVE ALONE {len(skipped)} (R10 — what the rule did NOT change):")
    for mid, provider, why in skipped:
        print(f"    #{mid:<4} {provider:<14} {why}")

    if not args.apply:
        print("\nread-only. re-run with --apply to write.")
        return
    if not apply_rows:
        print("\nnothing to write.")
        return

    # Pre-image FIRST. git revert does not undo an UPDATE.
    cur.execute(f"""
        create table if not exists {SHADOW} (
            id integer primary key,
            total_sq double precision,
            pitched_sq double precision,
            flat_sq double precision,
            captured_at timestamptz not null default now()
        )
    """)
    ids = [r[0] for r in apply_rows]
    cur.execute(f"""
        insert into {SHADOW} (id, total_sq, pitched_sq, flat_sq)
        select id, total_sq, pitched_sq, flat_sq from measurements
        where id = any(%s) on conflict (id) do nothing
    """, (ids,))
    print(f"\npre-image: {cur.rowcount} row(s) captured to {SHADOW}")

    for mid, _provider, _total, pitched, flat in apply_rows:
        cur.execute(
            "update measurements set pitched_sq=%s, flat_sq=%s where id=%s and pitched_sq is null",
            (pitched, flat, mid))
    conn.commit()

    cur.execute("select count(*) from measurements where pitched_sq is null")
    print(f"applied. measurements still carrying an unrecorded split: {cur.fetchone()[0]}")


if __name__ == "__main__":
    main()
