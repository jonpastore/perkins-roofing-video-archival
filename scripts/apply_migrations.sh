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
import glob, os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DB_URL"])
files = sorted(glob.glob("infra/migrations/*.sql"))
for f in files:
    raw = open(f).read()
    # strip full-line SQL comments, then split into statements on ';'
    body = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("--"))
    with engine.begin() as c:
        for stmt in (s.strip() for s in body.split(";")):
            if stmt:
                c.execute(text(stmt))
    print(f"  applied {f}")
print("== migrations complete ==")
PY
