#!/usr/bin/env python3
"""Apply migrations via ADC only (no gcloud CLI token needed).

Fetches db-password from Secret Manager using ADC (in-process, never printed),
connects via the Cloud SQL Connector, applies infra/migrations/*.sql >= MIN_MIGRATION
(idempotent), then probes RLS role state so the operator knows whether the app role
can bypass RLS. Companion to apply_migrations_connector.py for hosts whose gcloud CLI
user token is stale but whose ADC is fresh.

⚠️ TWO THINGS THAT LOOK LIKE OPTIONS AND ARE NOT.

1. **DB_URL IS IGNORED.** The target is built from GOOGLE_CLOUD_PROJECT (default
   video-archival-and-content-gen) — i.e. PROD — via the Cloud SQL Connector. Several docs
   show `DB_URL=postgresql+psycopg://... python scripts/apply_migrations_adc.py`; the prefix is
   decorative and does nothing. There is no way to point this script at a different database
   short of changing GOOGLE_CLOUD_PROJECT.

2. **THERE IS NO MIGRATION LEDGER.** Nothing records what has been applied. EVERY run re-executes
   EVERY migration from MIN_MIGRATION (0013) forward, and correctness rests entirely on each
   .sql being idempotent. That mostly holds — but it means an unguarded statement anywhere in
   the range aborts the run and silently blocks every LATER migration from being applied at all
   (0040's bare ADD CONSTRAINT did exactly that, hiding 0041-0052). It also means an UPDATE
   without a WHERE guard re-asserts its original value on every run: 0026's
   workspace_admin_subject and 0027's cors_origins re-scoping are both live examples, harmless
   today only because tenant 2 was never onboarded and Ez-Bids W2 never re-scoped those rows.

   Before adding a migration, re-run this script and confirm it still reaches the end.
"""
import glob
import os
import sys

from google.cloud import secretmanager
from google.cloud.sql.connector import Connector

sys.path.insert(0, "scripts")
from apply_migrations_connector import _statements  # reuse the dollar-quote-aware splitter

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")
CONN = f"{PROJECT}:us-central1:{PROJECT}-pg"
MIN_MIGRATION = os.environ.get("MIN_MIGRATION", "0013")


def _password() -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/db-password/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode().strip()


def main() -> None:
    connector = Connector()
    conn = connector.connect(CONN, "pg8000", user="app", password=_password(), db="perkins")
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
        conn.commit()
        for path in sorted(glob.glob("infra/migrations/*.sql")):
            name = os.path.basename(path)
            if name < f"{MIN_MIGRATION}":
                continue
            n = 0
            for stmt in _statements(open(path).read()):
                cur.execute(stmt)
                n += 1
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
