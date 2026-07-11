#!/usr/bin/env python3
"""Seed the Knowify mirror from a JSON dump (produced by mcp_pull.py) via the REAL
promote pipeline (core/knowify/promote.py). One-off stopgap population while the
automated hourly sync can't run (Knowify REST OAuth is 500-ing).

    # local / proxy target:
    DB_URL=sqlite:////tmp/knowify.db python scripts/knowify/seed_from_json.py /tmp/knowify_full.json
    # prod Cloud SQL (needs `gcloud auth application-default login` for the connector):
    python scripts/knowify/seed_from_json.py /tmp/knowify_full.json --cloudsql

Idempotent: re-running upserts on the crosswalk id and no-ops the ledger (safe to
repeat). Payment amounts are divided by 100 when the dump sets `_payments_in_cents`
(the MCP/query layer returns payments in cents; the REST layer would be dollars).
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def _engine(cloudsql: bool):
    if not cloudsql:
        url = os.environ.get("DB_URL")
        if not url:
            sys.exit("set DB_URL=... or pass --cloudsql")
        return create_engine(url, future=True)
    # Prod Cloud SQL via the Python Connector (ADC) — same path as apply_migrations_connector.
    from google.cloud.sql.connector import Connector

    from scripts.apply_migrations_connector import CONN, _password
    connector = Connector()

    def creator():
        return connector.connect(CONN, "pg8000", user="app", password=_password(), db="perkins")

    engine = create_engine("postgresql+pg8000://", creator=creator, future=True)
    # The app user is NOBYPASSRLS under FORCE RLS — stamp the tenant GUC on every new
    # connection so promote's INSERTs pass the tenant_isolation WITH CHECK (Perkins=1).
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _stamp_tenant(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', '1', false)")
        cur.close()

    return engine


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    cloudsql = "--cloudsql" in sys.argv
    if not args:
        sys.exit("usage: seed_from_json.py <dump.json> [--cloudsql]")
    dump = json.load(open(args[0]))

    from app.models import Base, Invoice  # noqa: E402
    from core.invoicing import derive_invoice_status  # noqa: F401,E402
    from core.knowify import promote  # noqa: E402

    clients = dump["clients"]
    invoices = dump["invoices"]
    payments = dump["payments"]
    if dump.get("_payments_in_cents"):
        for p in payments:
            if p.get("Amount") is not None:
                p["Amount"] = str((Decimal(str(p["Amount"])) / 100).quantize(Decimal("0.01")))

    engine = _engine(cloudsql)
    if not cloudsql:
        Base.metadata.create_all(engine)  # local demo: build the schema (prod is migrated)
    S = sessionmaker(bind=engine, future=True)
    s = S()
    s.info["tenant_id"] = 1
    # ensure tenant 1 exists (idempotent across dialects)
    ins = "INSERT OR IGNORE" if engine.dialect.name == "sqlite" else "INSERT"
    tail = "" if engine.dialect.name == "sqlite" else " ON CONFLICT (id) DO NOTHING"
    s.execute(text(f"{ins} INTO tenants (id,name,slug,status,settings,created_at) "
                   f"VALUES (1,'Perkins Roofing','perkins','active','{{}}',CURRENT_TIMESTAMP){tail}"))
    s.commit()

    nc = promote.promote_clients(s, clients)
    s.commit()
    ni = promote.promote_invoices(s, invoices)
    s.commit()
    npay = promote.promote_payments(s, payments)
    s.commit()

    total = s.execute(select(Invoice)).scalars().all()
    paid = sum(1 for r in total if r.status == "paid")
    cust_n = s.execute(text("SELECT count(*) FROM customers")).scalar()
    pay_n = s.execute(text("SELECT count(*) FROM payments")).scalar()
    ledger = s.execute(text("SELECT count(*) FROM job_billing_events "
                            "WHERE idempotency_key LIKE 'knowify:%'")).scalar()
    counter = s.execute(text("SELECT count(*) FROM tenant_invoice_counters")).scalar()
    print(f"seeded: clients~{nc} invoices~{ni} payments~{npay}")
    print(f"in DB: customers={cust_n} invoices={len(total)} (paid={paid}) payments={pay_n} "
          f"knowify_ledger_events={ledger}")
    print(f"invoice counter rows (MUST be 0 — never touched): {counter}")
    s.close()


if __name__ == "__main__":
    main()
