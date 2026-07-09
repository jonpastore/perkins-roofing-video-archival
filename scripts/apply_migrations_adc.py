#!/usr/bin/env python3
"""Apply migrations via ADC only (no gcloud CLI token needed).

Fetches db-password from Secret Manager using ADC (in-process, never printed),
connects via the Cloud SQL Connector, applies infra/migrations/*.sql >= MIN_MIGRATION
(idempotent), then probes RLS role state so the operator knows whether the app role
can bypass RLS. Companion to apply_migrations_connector.py for hosts whose gcloud CLI
user token is stale but whose ADC is fresh.
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
