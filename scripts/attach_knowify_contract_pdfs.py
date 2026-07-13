#!/usr/bin/env python3
"""Attach original Knowify contract/proposal PDFs to migrated native proposals.

Knowify stores the sent proposal/contract PDF as a Document row with
AssociatedEntityType='ContractPDF' (S3Uri + FileName), keyed by ContractId.

This script (bulk, no per-row LLM work):
  1) Pulls all ContractPDF/Contract documents via the Knowify MCP once.
  2) Maps ContractId -> {S3Uri, FileName, DocumentId}.
  3) Writes that reference into each migrated proposal's quote_snapshot.knowify_pdf.

Byte download to GCS is a documented follow-up: the MCP `query` returns S3Uri but
not a downloadable URL/Token, so fetching the actual bytes needs Knowify's REST
document-download endpoint (or a share Token). This script captures the reference so
the "View PDF" path can serve the original once that endpoint is wired.

Default dry-runs; use --apply to commit.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from core.tenant import register_tenant_session_events


def _make_factory(args):
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


def _contract_pdf_map() -> dict[str, dict]:
    """Return {ContractId: {s3_uri, file_name, document_id}} from Knowify MCP."""
    from core.knowify import tokens
    from core.knowify.mcp_client import MCP

    access = tokens.mcp_access_token()
    m = MCP(access)
    m.initialize()

    out: dict[str, dict] = {}
    offset = 0
    page = 200
    while True:
        args = {
            "table": "Documents",
            "fields": ["Id", "ContractId", "AssociatedEntityType", "S3Uri", "FileName", "FileType", "ObjectState"],
            "where": {"AssociatedEntityType": {"$in": ["ContractPDF", "Contract"]}},
            "order": [["Id", "DESC"]],
            "limit": page,
            "offset": offset,
        }
        resp = m._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "query", "arguments": args}})
        result = resp.get("result", {})
        if resp.get("error") or result.get("isError"):
            raise RuntimeError("Knowify Documents query error")
        content = result.get("content") or []
        text = content[0].get("text") if content else json.dumps(result.get("structuredContent", {}))
        data = json.loads(text)
        rows = data.get("Data") or data.get("data") or []
        for r in rows:
            cid = r.get("ContractId")
            if cid is None or r.get("ObjectState") not in (None, "Active"):
                continue
            key = str(cid)
            # keep the newest (first, since ordered by Id DESC) per contract
            out.setdefault(key, {
                "s3_uri": r.get("S3Uri"),
                "file_name": r.get("FileName"),
                "document_id": r.get("Id"),
                "file_type": r.get("FileType"),
            })
        total = data.get("Total")
        offset += page
        if len(rows) < page or (total and offset >= total):
            break
    return out


def run(args) -> int:
    from app.models import Proposal

    pdf_map = _contract_pdf_map()
    print("contract_pdf_documents", len(pdf_map), flush=True)

    factory, close = _make_factory(args)
    db = factory()
    db.info["tenant_id"] = args.tenant_id
    matched = 0
    try:
        rows = db.execute(
            select(Proposal.id, Proposal.quote_snapshot).where(Proposal.tenant_id == args.tenant_id)
        ).all()
        for pid, snap in rows:
            if not isinstance(snap, dict) or snap.get("source") != "knowify_import":
                continue
            ref = str(snap.get("source_ref") or "")
            pdf = pdf_map.get(ref)
            if not pdf:
                continue
            new_snap = {**snap, "knowify_pdf": pdf}
            db.execute(update(Proposal).where(Proposal.id == pid).values(quote_snapshot=new_snap))
            matched += 1
            if matched % 500 == 0:
                db.flush()
                print("progress", matched, flush=True)
        db.flush()
        print("matched_proposals", matched, flush=True)
        if args.apply:
            db.commit()
            print("committed", True, flush=True)
        else:
            db.rollback()
            print("committed", False, flush=True)
        return 0
    finally:
        db.close()
        close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tenant-id", type=int, default=1)
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
