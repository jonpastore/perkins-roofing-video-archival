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


def _dollar_tag_at(sql: str, i: int) -> str | None:
    """The dollar-quote delimiter starting at ``i`` (``$$`` or ``$name$``), else None.

    A bare ``$`` that is not a delimiter — e.g. inside an identifier — must fall through to
    ordinary text rather than toggling the scanner into a block it never leaves.
    """
    if sql[i] != "$":
        return None
    j = i + 1
    while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
        j += 1
    if j < len(sql) and sql[j] == "$":
        return sql[i:j + 1]
    return None


def _statements(sql: str):
    """Split a .sql file into executable statements.

    One left-to-right scan tracking three states, because a semicolon only ends a statement
    outside all of them:

      * ``$tag$ ... $tag$``  PG dollar-quoted blocks (DO blocks, function bodies) — their
        internal semicolons are not separators. The tag may be empty (``$$``) or named
        (``$func$``), and only the SAME tag closes it.
      * ``' ... '``     string literals, with the SQL ``''`` escape for an embedded quote.
      * ``-- ...``      line comments, skipped to end of line.

    The quote state is why comments are handled HERE rather than stripped line-by-line first.
    Both bugs that fix were real: 0046's column comment contains
    ``'... NULL = split unknown; 0 = no flat section.'``, and a naive scan split it mid-string
    and sent Postgres an unterminated literal (42601), aborting every later migration. A
    pre-pass that cut at the first ``--`` had the mirror-image flaw — it would truncate any
    string literal containing a double dash.

    Tagged dollar-quotes are handled even though no migration uses one today: this parser sends
    its output straight to PROD, and a `$func$ ... $func$` body treated as plain text would split
    on the first internal semicolon and ship a fragment.
    """
    current: list[str] = []
    dollar_tag: str | None = None   # the OPEN delimiter, e.g. "$$" or "$func$"; None = outside
    in_string = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        if in_string:
            # '' is an escaped quote and stays inside the literal; a lone ' ends it.
            if ch == "'" and i + 1 < n and sql[i + 1] == "'":
                current.append("''")
                i += 2
                continue
            if ch == "'":
                in_string = False
            current.append(ch)
            i += 1
            continue

        if dollar_tag is None and ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue

        if ch == "$":
            tag = _dollar_tag_at(sql, i)
            if tag is not None:
                if dollar_tag is None:
                    dollar_tag = tag          # opening delimiter
                elif tag == dollar_tag:
                    dollar_tag = None         # only the SAME tag closes it
                current.append(tag)
                i += len(tag)
                continue

        if ch == "'" and dollar_tag is None:
            in_string = True
            current.append(ch)
            i += 1
            continue

        if ch == ";" and dollar_tag is None:
            stmt = "".join(current).strip()
            if stmt:
                yield stmt
            current = []
            i += 1
            continue

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
