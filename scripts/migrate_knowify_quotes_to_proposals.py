#!/usr/bin/env python3
"""Dry-run/apply migration of mirrored Knowify contracts into native Proposal rows.

Default dry-runs and rolls back. Use --apply to commit. This does not fetch Knowify;
it reads knowify_raw_records populated by knowify-sync.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

from sqlalchemy import create_engine, delete, select
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


def _pick(payload: dict, fields: tuple[str, ...]) -> dict:
    return {f: payload.get(f) for f in fields}


def _load_raw(db, tenant_id: int) -> tuple[list, dict[str, list[dict]], dict[str, dict]]:
    from api.routes.quotes import _DELIVERABLE_FIELDS, _PROJECT_ADDRESS_FIELDS
    from app.models import KnowifyRawRecord

    rows = db.execute(
        select(KnowifyRawRecord).where(
            KnowifyRawRecord.tenant_id == tenant_id,
            KnowifyRawRecord.entity.in_(["contracts", "deliverables", "projects"]),
            KnowifyRawRecord.is_present.is_(True),
        )
    ).scalars().all()
    contracts = []
    deliverables: dict[str, list[dict]] = {}
    projects: dict[str, dict] = {}
    for row in rows:
        payload = row.payload or {}
        if row.entity == "contracts":
            contracts.append(row)
        elif row.entity == "deliverables":
            cid = str(payload.get("ContractId") or "")
            if cid:
                deliverables.setdefault(cid, []).append(_pick(payload, _DELIVERABLE_FIELDS))
        elif row.entity == "projects":
            pid = str(payload.get("Id") or row.knowify_id or "")
            if pid:
                projects[pid] = _pick(payload, _PROJECT_ADDRESS_FIELDS)
    return contracts, deliverables, projects


def _quote_from_raw(contract_row, deliverables: dict[str, list[dict]], projects: dict[str, dict]) -> dict[str, Any]:
    from api.routes.quotes import _CONTRACT_FIELDS

    payload = contract_row.payload or {}
    contract_id = str(payload.get("Id") or contract_row.knowify_id)
    project_id = str(payload.get("ProjectId") or "")
    return {
        "contract_id": contract_id,
        "contract": _pick(payload, _CONTRACT_FIELDS),
        "line_items": deliverables.get(contract_id, []),
        "project_address": projects.get(project_id),
        "project_id": project_id,
        "content_hash": contract_row.content_hash,
    }


def _contract_total(contract: dict) -> float:
    for field in ("CurrentContractSum", "OriginalContractSum"):
        try:
            value = float(contract.get(field) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _norm_addr(value: object) -> str:
    return str(value or "").strip().lower()


def _property_key_from_project(addr: dict) -> tuple[str, str, str, str] | None:
    street = _norm_addr(addr.get("Address1"))
    city = _norm_addr(addr.get("City"))
    state = _norm_addr(addr.get("StateProvince"))
    zip_code = _norm_addr(addr.get("Zip"))
    if not street or not city or not state:
        return None
    return (street, city, state, zip_code)


def _property_key(prop) -> tuple[str, str, str, str]:
    return (_norm_addr(prop.street), _norm_addr(prop.city), _norm_addr(prop.state), _norm_addr(prop.zip))


def run(args: argparse.Namespace) -> int:
    from api.routes.proposals import _build_knowify_quote_snapshot, knowify_proposal_state
    from app.models import Customer, Property, Proposal
    from core.proposal import generate_accept_token

    factory, close = _make_factory(args)
    db = factory()
    db.info["tenant_id"] = args.tenant_id
    migrated = 0
    existing = 0
    skipped = 0
    errors: dict[str, int] = {}
    try:
        contracts, deliverables, projects = _load_raw(db, args.tenant_id)
        contracts = contracts[: args.limit] if args.limit else contracts
        print("source_counts", {
            "contracts": len(contracts),
            "deliverable_contracts": len(deliverables),
            "projects": len(projects),
        }, flush=True)

        customers = db.execute(
            select(Customer.id, Customer.knowify_customer_id).where(
                Customer.tenant_id == args.tenant_id,
                Customer.knowify_customer_id.isnot(None),
            )
        ).all()
        customer_by_knowify = {str(kid): cid for cid, kid in customers if kid is not None}

        props = db.execute(
            select(Property).where(Property.tenant_id == args.tenant_id)
        ).scalars().all()
        properties_by_customer: dict[int, list] = {}
        properties_by_customer_key: dict[tuple[int, tuple[str, str, str, str]], int] = {}
        for prop in props:
            properties_by_customer.setdefault(prop.customer_id, []).append(prop)
            properties_by_customer_key[(prop.customer_id, _property_key(prop))] = prop.id

        imported_rows = db.execute(
            select(Proposal.id, Proposal.quote_snapshot).where(Proposal.tenant_id == args.tenant_id)
        ).all()
        existing_refs: set[str] = set()
        imported_ids: list[int] = []
        for pid, snap in imported_rows:
            if isinstance(snap, dict) and snap.get("source") == "knowify_import":
                imported_ids.append(pid)
                ref = snap.get("source_ref")
                if ref is not None:
                    existing_refs.add(str(ref))
        if args.purge_existing_imports and imported_ids:
            db.execute(delete(Proposal).where(Proposal.id.in_(imported_ids)))
            db.flush()
            print("purged_existing_imports", len(imported_ids), flush=True)
            existing_refs.clear()

        print("prefetch", {
            "knowify_customers": len(customer_by_knowify),
            "properties": len(props),
            "existing_imports": len(existing_refs),
        }, flush=True)

        for row in contracts:
            quote = _quote_from_raw(row, deliverables, projects)
            contract_id = quote["contract_id"]
            if _contract_total(quote["contract"]) <= 0:
                skipped += 1
                errors["zero-value/default contract"] = errors.get("zero-value/default contract", 0) + 1
                continue
            if contract_id in existing_refs:
                existing += 1
                continue
            try:
                knowify_client_id = quote["contract"].get("ClientId")
                if knowify_client_id is None:
                    raise ValueError("missing Knowify ClientId")
                customer_id = customer_by_knowify.get(str(knowify_client_id))
                if customer_id is None:
                    raise ValueError("Knowify ClientId is not backfilled")

                property_id = None
                addr_key = _property_key_from_project(quote.get("project_address") or {})
                if addr_key is not None:
                    property_id = properties_by_customer_key.get((customer_id, addr_key))
                if property_id is None:
                    customer_props = properties_by_customer.get(customer_id, [])
                    if len(customer_props) == 1:
                        property_id = customer_props[0].id
                if property_id is None:
                    raise ValueError("no safe property match")

                snapshot = _build_knowify_quote_snapshot(quote)
                title = quote["contract"].get("ContractName") or f"Knowify quote {contract_id}"
                state = knowify_proposal_state(quote["contract"])
                created_at = state["created_at"] or datetime.now(timezone.utc).replace(tzinfo=None)
                db.add(Proposal(
                    tenant_id=args.tenant_id,
                    customer_id=customer_id,
                    property_id=property_id,
                    title=title,
                    quote_snapshot=snapshot,
                    status=state["status"],
                    accept_token=generate_accept_token(),
                    accepted_at=state["accepted_at"],
                    sent_at=state["sent_at"],
                    created_by="knowify_bulk_import",
                    created_at=created_at,
                    updated_at=created_at,
                    version_number=1,
                ))
                existing_refs.add(contract_id)
                migrated += 1
                if migrated % 500 == 0:
                    db.flush()
                    print("progress", {"migrated": migrated, "existing": existing, "skipped": skipped}, flush=True)
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                key = str(exc)
                errors[key] = errors.get(key, 0) + 1
        db.flush()
        print("result", {"migrated": migrated, "existing": existing, "skipped": skipped}, flush=True)
        print("skip_reasons", errors, flush=True)
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
    parser.add_argument("--purge-existing-imports", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
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
