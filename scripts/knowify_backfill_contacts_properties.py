#!/usr/bin/env python3
"""Dry-run/apply Knowify contacts + properties promotion.

Default is dry-run: fetches source data, runs promotion in one transaction, prints
aggregate counts, then rolls back. Use --apply to commit.

Sources:
  --source raw  : read existing knowify_raw_records (no network)
  --source mcp  : pull clients/contacts/projects live through Knowify MCP

Local Cloud SQL example (no proxy):
  .venv/bin/python scripts/knowify_backfill_contacts_properties.py \
    --cloud-sql-connector --source mcp
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from core.tenant import register_tenant_session_events


def _make_factory(args: argparse.Namespace):
    if args.cloud_sql_connector:
        from google.cloud.sql.connector import Connector

        project = args.project
        region = args.region
        instance = args.instance or f"{project}-pg"
        conn_name = f"{project}:{region}:{instance}"
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
        raise SystemExit("DB_URL is required unless --cloud-sql-connector is used")
    engine = create_engine(db_url, future=True)
    factory = sessionmaker(bind=engine, future=True)
    register_tenant_session_events(factory, strict=True)
    return factory, engine.dispose


def _fetch_from_raw(session, tenant_id: int) -> dict[str, list[dict[str, Any]]]:
    from app.models import KnowifyRawRecord

    data: dict[str, list[dict[str, Any]]] = {"clients": [], "contacts": [], "projects": []}
    for entity in data:
        rows = session.execute(
            select(KnowifyRawRecord.payload).where(
                KnowifyRawRecord.tenant_id == tenant_id,
                KnowifyRawRecord.entity == entity,
                KnowifyRawRecord.is_present.is_(True),
            )
        ).scalars().all()
        data[entity] = list(rows)
    return data


def _fetch_from_mcp() -> dict[str, list[dict[str, Any]]]:
    from core.knowify import mcp_client, tokens

    access = tokens.mcp_access_token()
    return {
        "clients": mcp_client.fetch_entity("clients", access),
        "contacts": mcp_client.fetch_entity("contacts", access),
        "projects": mcp_client.fetch_entity("projects", access),
    }


def _count(session) -> dict[str, int]:
    from app.models import Contact, Property

    return {
        "contacts": session.execute(select(func.count()).select_from(Contact)).scalar_one(),
        "properties": session.execute(select(func.count()).select_from(Property)).scalar_one(),
    }


def _run(args: argparse.Namespace) -> int:
    from core.knowify.promote import promote_client_contacts, promote_contacts, promote_properties, promote_run

    factory, close = _make_factory(args)
    session = factory()
    session.info["tenant_id"] = args.tenant_id
    try:
        before = _count(session)
        if args.source == "raw":
            source = _fetch_from_raw(session, args.tenant_id)
        else:
            source = _fetch_from_mcp()

        print("source_counts", {k: len(v) for k, v in source.items()}, flush=True)
        if args.promote_clients:
            counts = promote_run(
                session,
                clients=source["clients"],
                contacts=source["contacts"],
                projects=source["projects"],
            )
        else:
            # Backfill mode assumes customers were already promoted by the existing
            # Knowify sync, and only materializes contacts/properties. This avoids
            # 7k no-op customer upserts during the production dry-run/apply.
            counts = {"clients": 0, "contacts": 0, "properties": 0, "items": 0, "invoices": 0, "payments": 0}
            counts["contacts"] += promote_client_contacts(session, source["clients"])
            counts["properties"] += promote_properties(session, clients=source["clients"])
            counts["contacts"] += promote_contacts(session, source["contacts"])
            counts["properties"] += promote_properties(session, projects=source["projects"])
        session.flush()
        after = _count(session)
        delta = {k: after[k] - before[k] for k in before}
        print("promotion_counts", counts, flush=True)
        print("before", before, flush=True)
        print("after", after, flush=True)
        print("delta", delta, flush=True)

        if args.apply:
            session.commit()
            print("committed", True, flush=True)
        else:
            session.rollback()
            print("committed", False, flush=True)
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Commit writes. Default rolls back.")
    parser.add_argument("--source", choices=["raw", "mcp"], default="raw")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument(
        "--promote-clients",
        action="store_true",
        help="Also upsert customer rows; default skips them for faster backfills.",
    )
    parser.add_argument("--db-url")
    parser.add_argument("--cloud-sql-connector", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen"))
    parser.add_argument("--region", default=os.environ.get("GCP_REGION", "us-central1"))
    parser.add_argument("--instance")
    parser.add_argument("--database", default="perkins")
    parser.add_argument("--db-password")
    args = parser.parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
