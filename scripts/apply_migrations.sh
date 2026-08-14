#!/usr/bin/env bash
# Apply DB schema migrations from git (R3: infra as code, git -> apply, never the reverse).
# Runs pending infra/migrations/*.sql in filename order. Already-applied files are skipped
# via schema_migrations. GOOGLE_CLOUD_PROJECT is required when DB_URL is not set — there
# is no implicit prod default.
#
# Requires: the Cloud SQL Auth Proxy listening on 127.0.0.1:5432 (or set DB_URL yourself),
# and application-default credentials able to read the db-password secret.
#   Usage: GOOGLE_CLOUD_PROJECT=... scripts/apply_migrations.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${DB_URL:-}" ]]; then
  if [[ -z "${GOOGLE_CLOUD_PROJECT:-}" ]]; then
    echo "GOOGLE_CLOUD_PROJECT is required — refusing to default to prod." >&2
    exit 1
  fi
  PW="$(gcloud secrets versions access latest --secret=db-password --project "$GOOGLE_CLOUD_PROJECT")"
  DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
fi

echo "== Applying migrations from infra/migrations =="
DB_URL="$DB_URL" PYTHONPATH="scripts${PYTHONPATH:+:$PYTHONPATH}" .venv/bin/python - "$@" <<'PY'
import glob, os, re, sys
from sqlalchemy import create_engine, text

from migration_ledger import LEDGER_DDL, decide, file_checksum

# Create the base tables FIRST (the ORM owns them; no migration issues their CREATE TABLE).
# Without this, the ALTER-only migrations (0001 ALTER chunks, 0002/0008/0009 ALTER videos)
# fail with "relation does not exist" on a fresh DB. create_all is idempotent.
import app.models as _m
_m.init_db()

# Strip ALL SQL line-comments (full-line AND trailing "-- ..."), then split on ';'.
# Trailing comments left in place broke the naive split — a "DEFAULT 0  -- note" line
# fed a comment into the parser (migration 0035). Migrations here are plain DDL with
# no "--" inside string literals, so an inline strip is safe.
_COMMENT = re.compile(r"--.*$", re.MULTILINE)

engine = create_engine(os.environ["DB_URL"])
with engine.begin() as c:
    c.execute(text(LEDGER_DDL))
    applied = {row[0]: row[1] for row in c.execute(text(
        "SELECT filename, checksum FROM schema_migrations"))}
files = sorted(glob.glob("infra/migrations/*.sql"))
for f in files:
    name = os.path.basename(f)
    checksum = file_checksum(f)
    if decide(name, checksum, applied) == "skip":
        print(f"  skip {name} (already applied)")
        continue
    body = _COMMENT.sub("", open(f).read())
    with engine.begin() as c:
        for stmt in (s.strip() for s in body.split(";")):
            if stmt:
                c.execute(text(stmt))
        c.execute(
            text("INSERT INTO schema_migrations (filename, checksum) VALUES (:f, :c)"),
            {"f": name, "c": checksum},
        )
    print(f"  applied {f}")
print("== migrations complete ==")
PY
