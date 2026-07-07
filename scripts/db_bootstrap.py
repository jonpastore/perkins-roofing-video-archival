"""Idempotent Cloud SQL bootstrap — enable the pgvector extension. Run once after
`terraform apply` creates the instance (rule R3: reproducible, not a manual console step).

Uses the Cloud SQL Python Connector (authenticates via ADC), so it needs neither psql nor
an authorized-networks entry. The app-user password is read from Secret Manager (db-password).

Run: .venv/bin/python scripts/db_bootstrap.py
"""
import subprocess

from google.cloud.sql.connector import Connector

CONN = "video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg"


def _pw():
    return subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=db-password"],
        check=True, capture_output=True, text=True).stdout.strip()


def _ver_tuple(v):
    parts = []
    for p in str(v).split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts[:3])


def main():
    connector = Connector()
    # NOTE: CREATE EXTENSION / ALTER EXTENSION require a superuser role. Cloud SQL grants
    # cloudsqlsuperuser to the built-in `postgres` user; if the `app` user lacks it this will
    # fail with "permission denied to create extension" — grant it or run this as postgres.
    conn = connector.connect(CONN, "pg8000", user="app", password=_pw(), db="perkins")
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute("ALTER EXTENSION vector UPDATE")   # pick up a newer pgvector if the image has it
    conn.commit()
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ver = cur.fetchone()[0]
    cur.close()
    conn.close()
    connector.close()
    print("pgvector enabled:", ver)
    # 0001_embedding_3072.sql builds an HNSW index with halfvec_cosine_ops and store.py queries
    # `embedding::halfvec(3072)`; the halfvec type only exists in pgvector >= 0.7.0. Fail loudly
    # rather than let migration 0001 / every vector search error with "type halfvec does not exist".
    if _ver_tuple(ver) < (0, 7, 0):
        raise SystemExit(
            f"pgvector {ver} is too old — halfvec(3072) requires >= 0.7.0. "
            "Upgrade the Cloud SQL pgvector version before applying migrations."
        )


if __name__ == "__main__":
    main()
