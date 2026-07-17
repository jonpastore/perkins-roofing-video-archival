#!/usr/bin/env bash
# Apply DB schema migrations from git (R3: infra as code, git -> apply, never the reverse).
# Runs every infra/migrations/*.sql in filename order against Cloud SQL. Migrations are
# idempotent (CREATE/ALTER ... IF NOT EXISTS), so re-running is safe.
#
# Requires: the Cloud SQL Auth Proxy listening on 127.0.0.1:5432 (or set DB_URL yourself),
# and application-default credentials able to read the db-password secret.
#   Usage: scripts/apply_migrations.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${GOOGLE_CLOUD_PROJECT:-video-archival-and-content-gen}"

if [[ -z "${DB_URL:-}" ]]; then
  PW="$(gcloud secrets versions access latest --secret=db-password --project "$PROJECT")"
  DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
fi

echo "== Applying migrations from infra/migrations =="
DB_URL="$DB_URL" .venv/bin/python - "$@" <<'PY'
import glob, os, re
from sqlalchemy import create_engine, text

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
files = sorted(glob.glob("infra/migrations/*.sql"))
for f in files:
    body = _COMMENT.sub("", open(f).read())
    with engine.begin() as c:
        for stmt in (s.strip() for s in body.split(";")):
            if stmt:
                c.execute(text(stmt))
    print(f"  applied {f}")
print("== migrations complete ==")
PY
