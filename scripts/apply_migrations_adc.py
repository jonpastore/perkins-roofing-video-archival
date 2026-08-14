#!/usr/bin/env python3
"""Apply migrations via ADC only (no gcloud CLI token needed).

Fetches db-password from Secret Manager using ADC (in-process, never printed),
connects via the Cloud SQL Connector, applies infra/migrations/*.sql >= MIN_MIGRATION
(idempotent), then probes RLS role state so the operator knows whether the app role
can bypass RLS. Companion to apply_migrations_connector.py for hosts whose gcloud CLI
user token is stale but whose ADC is fresh.

DB_URL is ignored — the target is Cloud SQL for GOOGLE_CLOUD_PROJECT, which is
required (this used to default to prod). Applied files are recorded in
schema_migrations and skipped on later runs; edit an applied file and this
refuses rather than re-running a data UPDATE.
"""
import glob
import os
import sys

from google.cloud import secretmanager
from google.cloud.sql.connector import Connector

sys.path.insert(0, "scripts")
from apply_migrations_connector import _statements  # reuse the dollar-quote-aware splitter
from migration_ledger import (  # noqa: E402
    LEDGER_DDL,
    decide,
    file_checksum,
    record_applied,
    require_project,
)

MIN_MIGRATION = os.environ.get("MIN_MIGRATION", "0013")


def _password(project: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/db-password/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode().strip()


def main() -> None:
    project = require_project()
    conn_name = f"{project}:us-central1:{project}-pg"
    connector = Connector()
    conn = connector.connect(conn_name, "pg8000", user="app", password=_password(project), db="perkins")
    cur = conn.cursor()
    try:
        # 28 RLS policies use the BARE current_setting('app.tenant_id') — no missing-ok flag — so
        # they raise 42704 "unrecognized configuration parameter" rather than returning no rows in
        # a session that never set it. That is the right failure mode for the app (core/tenant.py
        # refuses to query without a tenant), but it means this runner cannot touch a tenant table
        # at all: 0029's seed INSERT into tc_versions dies before reaching anything after it.
        # 0041 works around it with its own `SET LOCAL`; setting it once here fixes every migration
        # instead of requiring each new one to remember. Tenant 1 is the only tenant, and every
        # seed in infra/migrations writes tenant_id = 1.
        cur.execute("SET app.tenant_id = '1'")
        cur.execute(LEDGER_DDL)
        conn.commit()
        cur.execute("SELECT filename, checksum FROM schema_migrations")
        applied = {row[0]: row[1] for row in cur.fetchall()}
        for path in sorted(glob.glob("infra/migrations/*.sql")):
            name = os.path.basename(path)
            if name < f"{MIN_MIGRATION}":
                continue
            checksum = file_checksum(path)
            if decide(name, checksum, applied) == "skip":
                print(f"skip {name} (already applied)")
                continue
            n = 0
            for stmt in _statements(open(path).read()):
                cur.execute(stmt)
                n += 1
            record_applied(cur.execute, name, checksum)
            conn.commit()
            print(f"applied {name} ({n} statements)")

        # ── Post-apply verification (no secret ever printed) ──────────────────
        cur.execute("SELECT to_regclass('public.tenants'), to_regclass('public.tenant_gcip_map'), "
                    "to_regclass('public.tenant_offboard_log'), to_regclass('public.platform_admins')")
        print("F4/F5/F6 tables:", cur.fetchone())
        cur.execute("SELECT count(*) FROM tenants")
        print("tenant rows:", cur.fetchone()[0])

        # ── RLS role state (H2): can the app role bypass RLS? ─────────────────
        cur.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        u, rolsuper, rolbypassrls = cur.fetchone()
        print(f"ROLE_STATE user={u} rolsuper={rolsuper} rolbypassrls={rolbypassrls}")

        # ── Which tenant-scoped tables have RLS enabled + forced? ─────────────
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity"
        )
        print("tables with RLS enabled:", cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' AND c.relforcerowsecurity"
        )
        print("tables with RLS FORCED:", cur.fetchone()[0])
    finally:
        cur.close()
        conn.close()
        connector.close()
    print("DONE")


if __name__ == "__main__":
    main()
