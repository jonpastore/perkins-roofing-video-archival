#!/usr/bin/env python3
"""Render native proposal PDFs to GCS in a resumable, throttled batch.

- Reads native proposals from Postgres.
- Skips rows whose quote_snapshot.rendered_pdf_gcs object already exists unless --force.
- Calls the same renderer/cache helper used by GET /quoting/proposals/{id}/pdf.
- Sleeps between renders to avoid hammering Gotenberg.

Default dry-runs; use --apply to commit quote_snapshot updates.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.tenant import register_tenant_session_events


def _make_factory(args: argparse.Namespace):
    if args.cloud_sql_connector:
        from google.cloud.sql.connector import Connector

        project = args.project
        conn_name = f"{project}:{args.region}:{args.instance or f'{project}-pg'}"
        password = args.db_password or subprocess.check_output([
            "gcloud", "secrets", "versions", "access", "latest",
            "--secret=db-password", "--project", project,
        ]).decode().strip()
        connector = Connector()

        def getconn():
            return connector.connect(conn_name, "pg8000", user="app", password=password, db=args.database)

        engine = create_engine("postgresql+pg8000://", creator=getconn, future=True)
        factory = sessionmaker(bind=engine, future=True)
        register_tenant_session_events(factory, strict=True)
        return factory, connector.close

    db_url = args.db_url or os.environ.get("DB_URL")
    if not db_url:
        raise SystemExit("DB_URL required unless --cloud-sql-connector")
    engine = create_engine(db_url, future=True)
    factory = sessionmaker(bind=engine, future=True)
    register_tenant_session_events(factory, strict=True)
    return factory, engine.dispose


def _gcs_exists(uri: str) -> bool:
    if not uri.startswith("gs://"):
        return False
    from google.cloud import storage

    rest = uri[5:]
    bucket_name, _, key = rest.partition("/")
    return storage.Client().bucket(bucket_name).blob(key).exists()


def run(args: argparse.Namespace) -> int:
    from api.routes.proposals import render_and_cache_proposal_pdf
    from app.models import Proposal

    factory, close = _make_factory(args)
    db = factory()
    db.info["tenant_id"] = args.tenant_id
    rendered = skipped = errors = 0
    try:
        stmt = (
            select(Proposal)
            .where(Proposal.tenant_id == args.tenant_id)
            .order_by(Proposal.id)
        )
        if args.proposal_id:
            stmt = stmt.where(Proposal.id == args.proposal_id)
        rows = db.execute(stmt).scalars().all()
        if args.limit:
            rows = rows[: args.limit]
        print("source", {"proposals": len(rows), "apply": args.apply, "force": args.force}, flush=True)
        for row in rows:
            snap = row.quote_snapshot or {}
            cached = snap.get("rendered_pdf_gcs")
            if not args.force and isinstance(cached, str) and _gcs_exists(cached):
                skipped += 1
                continue
            if not args.apply:
                rendered += 1
                continue
            try:
                render_and_cache_proposal_pdf(db, row)
                rendered += 1
                if rendered % args.commit_every == 0:
                    db.commit()
                    db.info["tenant_id"] = args.tenant_id
                    print("progress", {"rendered": rendered, "skipped": skipped, "errors": errors}, flush=True)
                time.sleep(args.sleep_seconds)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                db.info["tenant_id"] = args.tenant_id
                errors += 1
                print("error", {"proposal_id": row.id, "error": str(exc)[:300]}, flush=True)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        summary = {"rendered": rendered, "skipped": skipped, "errors": errors, "committed": args.apply}
        print("result", summary, flush=True)
        return 0 if errors == 0 else 1
    finally:
        db.close()
        close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--commit-every", type=int, default=25)
    parser.add_argument("--db-url")
    parser.add_argument("--cloud-sql-connector", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen"))
    parser.add_argument("--region", default=os.environ.get("GCP_REGION", "us-central1"))
    parser.add_argument("--instance")
    parser.add_argument("--database", default="perkins")
    parser.add_argument("--db-password")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
