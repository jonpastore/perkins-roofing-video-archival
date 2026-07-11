#!/usr/bin/env python3
"""Apply DB migrations to Cloud SQL via the Cloud SQL Python Connector (no Auth Proxy needed).

Companion to apply_migrations.sh for hosts without the proxy binary. Authenticates via ADC
(the gcloud user running it) and reads the db-password from Secret Manager. Runs every
infra/migrations/*.sql at or after MIN_MIGRATION in filename order. All migrations are
idempotent (CREATE/ALTER ... IF NOT EXISTS), so re-running is safe (R3: git -> apply).

Usage:
    .venv/bin/python scripts/apply_migrations_connector.py
    MIN_MIGRATION=0001 .venv/bin/python scripts/apply_migrations_connector.py   # apply all
"""
import glob
import os
import subprocess

from google.cloud.sql.connector import Connector

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")
CONN = f"{PROJECT}:us-central1:{PROJECT}-pg"
# 0001-0009 were applied long ago; default to the recent batch. Override via env to apply all.
MIN_MIGRATION = os.environ.get("MIN_MIGRATION", "0010")


def _password() -> str:
    return subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=db-password", "--project", PROJECT]
    ).decode().strip()


def _statements(sql: str):
    """Split a .sql file into executable statements.

    Dollar-quote-aware: $$ ... $$ blocks (PG DO blocks, anonymous functions) are
    kept intact even if they contain semicolons. Line/inline -- comments are stripped
    first so a semicolon inside a comment can't split a statement.
    """
    stripped = []
    for ln in sql.splitlines():
        i = ln.find("--")
        stripped.append(ln if i == -1 else ln[:i])
    text = "\n".join(stripped)
    current: list[str] = []
    in_dollar_quote = False
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "$" and i + 1 < n and text[i + 1] == "$":
            in_dollar_quote = not in_dollar_quote
            current.append("$$")
            i += 2
            continue
        ch = text[i]
        if ch == ";" and not in_dollar_quote:
            stmt = "".join(current).strip()
            if stmt:
                yield stmt
            current = []
        else:
            current.append(ch)
        i += 1
    stmt = "".join(current).strip()
    if stmt:
        yield stmt


def main() -> None:
    connector = Connector()
    conn = connector.connect(CONN, "pg8000", user="app", password=_password(), db="perkins")
    cur = conn.cursor()
    # Tenant-scoped seeds (e.g. 0030's invoice-counter seed) run under FORCE ROW LEVEL
    # SECURITY as the NOBYPASSRLS `app` user, so set the tenant GUC to Perkins (tenant 1 —
    # the only tenant these migrations seed) or the WITH CHECK policy rejects the INSERT.
    cur.execute("SELECT set_config('app.tenant_id', '1', false)")
    conn.commit()
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
        # Verify the Track D columns the ORM depends on now exist.
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='articles' AND column_name IN ('cluster_id','priority','scheduled_at') "
            "ORDER BY column_name"
        )
        print("articles new columns:", [r[0] for r in cur.fetchall()])
        cur.execute("SELECT to_regclass('public.clusters')")
        print("clusters table:", cur.fetchone()[0])
    finally:
        cur.close()
        conn.close()
        connector.close()
    print("migrations applied OK")


if __name__ == "__main__":
    main()
