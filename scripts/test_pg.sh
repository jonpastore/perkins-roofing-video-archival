#!/usr/bin/env bash
# Fast local test Postgres — reuse ONE long-lived pgvector container across runs.
#
# Why: the pytest PG fixtures (tests/conftest.py + tests/tenancy/conftest.py) fall
# back to Testcontainers, which provisions and tears down a fresh Postgres EVERY
# run (and can start more than one). That container start + image work dominates
# wall time. Both fixture trees honor TENANCY_PG_URL: if it is set, they connect
# to that URL and skip Testcontainers entirely.
#
# This script:
#   * starts a persistent container "perkins-test-pg" if not already running, so
#     provisioning cost is paid ONCE, then reused;
#   * creates a FRESH per-run database (the fixtures rebuild the schema, so a clean
#     DB avoids cross-run data pollution / UNIQUE collisions);
#   * exports TENANCY_PG_URL and execs pytest with any args you pass.
#
# Usage:
#   scripts/test_pg.sh                                  # full suite
#   scripts/test_pg.sh tests/tenancy -q                # a subset
#   scripts/test_pg.sh --cov=core --cov-fail-under=97  # the R1 gate
#   scripts/test_pg.sh --stop-pg                        # stop + remove the container
#
# Env knobs:
#   PERKINS_TEST_PG_CONTAINER  (default: perkins-test-pg)
#   PERKINS_TEST_PG_PORT       (default: 55432)
#   PERKINS_TEST_PG_IMAGE      (default: pgvector/pgvector:pg15)
#   PERKINS_TEST_PG_KEEP_DB=1  reuse a single fixed DB instead of a fresh one
set -euo pipefail

CONTAINER="${PERKINS_TEST_PG_CONTAINER:-perkins-test-pg}"
PORT="${PERKINS_TEST_PG_PORT:-55432}"
IMAGE="${PERKINS_TEST_PG_IMAGE:-pgvector/pgvector:pg15}"
ADMIN_USER="tc_admin"
ADMIN_PW="tc_admin_pw"

if [[ "${1:-}" == "--stop-pg" ]]; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "removed $CONTAINER" || echo "no $CONTAINER"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found — cannot start the reusable test Postgres" >&2
  exit 1
fi

# Start the persistent container once; reuse on subsequent runs.
if [[ -z "$(docker ps -q -f "name=^${CONTAINER}$")" ]]; then
  if [[ -n "$(docker ps -aq -f "name=^${CONTAINER}$")" ]]; then
    docker start "$CONTAINER" >/dev/null
  else
    echo "starting persistent test Postgres '$CONTAINER' on :$PORT ..."
    docker run -d --name "$CONTAINER" \
      -e POSTGRES_USER="$ADMIN_USER" \
      -e POSTGRES_PASSWORD="$ADMIN_PW" \
      -e POSTGRES_DB=postgres \
      -p "${PORT}:5432" \
      "$IMAGE" >/dev/null
  fi
fi

# Wait for readiness (fast once the container is warm).
for _ in $(seq 1 30); do
  if docker exec "$CONTAINER" pg_isready -U "$ADMIN_USER" -q 2>/dev/null; then
    break
  fi
  sleep 0.5
done

# Pick the database: fresh per run by default (clean schema), or a fixed one when
# PERKINS_TEST_PG_KEEP_DB=1.
if [[ "${PERKINS_TEST_PG_KEEP_DB:-}" == "1" ]]; then
  DB="perkins_test"
else
  DB="perkins_test_$$_$(date +%s)"
fi

db_exists="$(docker exec "$CONTAINER" psql -U "$ADMIN_USER" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${DB}'" 2>/dev/null || true)"
if [[ "$db_exists" != "1" ]]; then
  docker exec "$CONTAINER" createdb -U "$ADMIN_USER" "$DB"
fi

export TENANCY_PG_URL="postgresql+pg8000://${ADMIN_USER}:${ADMIN_PW}@localhost:${PORT}/${DB}"
echo "TENANCY_PG_URL=postgresql+pg8000://${ADMIN_USER}:***@localhost:${PORT}/${DB}"

cleanup() {
  if [[ "${PERKINS_TEST_PG_KEEP_DB:-}" != "1" ]]; then
    docker exec "$CONTAINER" dropdb -U "$ADMIN_USER" --if-exists --force "$DB" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

python -m pytest "$@"
