#!/usr/bin/env python3
"""Import Tim/Roofr golden measurement fixtures into measurements.

Creates clearly-labeled golden fixture customers/properties when an exact fixture
property is not already present. The measurement provider is `roofr_fixture` and
raw_payload contains the full extracted Roofr fields.

Default dry-run. Use --apply to commit.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Customer, Measurement, Property
from core.tenant import register_tenant_session_events

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/perkins-analysis/roofr_baseline.json"
FIXTURES = ROOT / "docs/perkins-analysis/proposal_fixtures.json"


def _pitch_num(raw: str | None) -> float | None:
    if not raw:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*/\s*12", str(raw))
    return float(m.group(1)) if m else None


def _split_addr(addr: str) -> tuple[str, str, str, str | None]:
    parts = [p.strip() for p in addr.split(",")]
    street = parts[0]
    city = parts[1] if len(parts) > 1 else ""
    state = "FL"
    zip_code = None
    if len(parts) > 2:
        tail = " ".join(parts[2:])
        z = re.search(r"\b(\d{5})(?:-\d{4})?\b", tail)
        zip_code = z.group(1) if z else None
    return street, city, state, zip_code


def _code_zone(addr: str) -> str:
    # Lake Worth Beach golden fixture is the only one called HVHZ in Tim's analyzed docs.
    if "404 South M" in addr or "Lake Worth Beach" in addr:
        return "HVHZ"
    return "FBC"


def _fixtures_by_address() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not FIXTURES.exists():
        return out
    for row in json.loads(FIXTURES.read_text()):
        addr = row.get("property_address") or ""
        out[addr.lower()] = row
    return out


def _addr_key(value: str) -> str:
    out = value.lower()
    out = re.sub(r"\([^)]*\)", "", out)
    out = out.replace(" street", " st").replace(" drive", " dr").replace(" road", " rd")
    out = out.replace(" northeast ", " ne ").replace(" northwest ", " nw ")
    out = out.replace(" southeast ", " se ").replace(" southwest ", " sw ")
    out = out.replace(" south ", " s ").replace(" north ", " n ")
    out = re.sub(r"[^a-z0-9]+", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _match_fixture(address: str, fixtures: dict[str, dict]) -> dict | None:
    al = _addr_key(address)
    normalized = {_addr_key(k): v for k, v in fixtures.items()}
    if al in normalized:
        return normalized[al]
    street = _addr_key(address.split(",", 1)[0])
    for k, v in fixtures.items():
        if _addr_key(k).startswith(street):
            return v
    return None


def _factory(args):
    if args.cloud_sql_connector:
        from google.cloud.sql.connector import Connector
        project = args.project
        conn_name = f"{project}:{args.region}:{args.instance or f'{project}-pg'}"
        if args.db_password:
            password = args.db_password
        else:
            try:
                from google.cloud import secretmanager
                password = secretmanager.SecretManagerServiceClient().access_secret_version(
                    name=f"projects/{project}/secrets/db-password/versions/latest"
                ).payload.data.decode()
            except Exception:
                password = subprocess.check_output([
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
    db_url = args.db_url
    if not db_url:
        raise SystemExit("DB_URL or --cloud-sql-connector required")
    engine = create_engine(db_url, future=True)
    factory = sessionmaker(bind=engine, future=True)
    register_tenant_session_events(factory, strict=True)
    return factory, engine.dispose


def run(args) -> int:
    baseline = json.loads(BASELINE.read_text())
    fixtures = _fixtures_by_address()
    factory, close = _factory(args)
    db = factory()
    db.info["tenant_id"] = args.tenant_id
    created_customers = created_properties = created_measurements = updated_measurements = 0
    try:
        for addr, roofr in baseline.items():
            fixture = _match_fixture(addr, fixtures)
            customer_name = (fixture or {}).get("customer_name") or f"Roofr Fixture — {addr.split(',',1)[0]}"
            street, city, state, zip_code = _split_addr(addr)

            prop = db.execute(
                select(Property).where(
                    Property.tenant_id == args.tenant_id,
                    Property.street.ilike(street),
                ).limit(1)
            ).scalar_one_or_none()
            if prop is None:
                cust = db.execute(
                    select(Customer).where(
                        Customer.tenant_id == args.tenant_id,
                        Customer.display_name == customer_name,
                    )
                ).scalar_one_or_none()
                if cust is None:
                    cust = Customer(
                        tenant_id=args.tenant_id,
                        display_name=customer_name,
                        notes="Golden Roofr fixture customer created from Tim attachments for estimator calibration.",
                    )
                    db.add(cust)
                    db.flush()
                    created_customers += 1
                prop = Property(
                    tenant_id=args.tenant_id,
                    customer_id=cust.id,
                    street=street,
                    city=city,
                    state=state,
                    zip=zip_code,
                    code_zone=_code_zone(addr),
                    notes="Golden Roofr fixture property created from Tim attachments for estimator calibration.",
                )
                db.add(prop)
                db.flush()
                created_properties += 1

            raw_payload = {**roofr, "source_address": addr, "fixture": fixture}
            existing = db.execute(
                select(Measurement).where(
                    Measurement.tenant_id == args.tenant_id,
                    Measurement.provider == "roofr_fixture",
                    Measurement.property_id == prop.id,
                )
            ).scalar_one_or_none()
            target = existing or Measurement(
                tenant_id=args.tenant_id,
                property_id=prop.id,
                provider="roofr_fixture",
                status="complete",
                created_by="import_roofr_golden_measurements.py",
            )
            target.total_sq = round(float(roofr.get("total_sqft") or 0) / 100.0, 2)
            target.hips_lf = roofr.get("hips_ft")
            target.ridges_lf = roofr.get("ridges_ft")
            target.valleys_lf = roofr.get("valleys_ft")
            target.rakes_lf = roofr.get("rakes_ft")
            target.eaves_lf = roofr.get("eaves_ft")
            target.wall_flashings_lf = roofr.get("wall_flashing_ft")
            target.pitch_primary = _pitch_num(roofr.get("predominant_pitch"))
            target.confidence = 1.0
            target.raw_payload = raw_payload
            target.provenance_note = (
                "Roofr golden fixture extracted from Tim attachments; "
                "source of truth for estimator calibration."
            )
            if existing is None:
                db.add(target)
                created_measurements += 1
            else:
                updated_measurements += 1
            print({
                "address": addr,
                "customer": customer_name,
                "property_id": prop.id,
                "measurement_total_sq": target.total_sq,
                "action": "update" if existing else "create",
            })

        if args.apply:
            db.commit()
        else:
            db.rollback()
        print("summary", {
            "apply": args.apply,
            "created_customers": created_customers,
            "created_properties": created_properties,
            "created_measurements": created_measurements,
            "updated_measurements": updated_measurements,
        })
        return 0
    finally:
        db.close()
        close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--tenant-id", type=int, default=1)
    p.add_argument("--db-url")
    p.add_argument("--cloud-sql-connector", action="store_true")
    p.add_argument("--project", default="video-archival-and-content-gen")
    p.add_argument("--region", default="us-central1")
    p.add_argument("--instance")
    p.add_argument("--database", default="perkins")
    p.add_argument("--db-password")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
