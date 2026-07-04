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


def main():
    connector = Connector()
    conn = connector.connect(CONN, "pg8000", user="app", password=_pw(), db="perkins")
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    print("pgvector enabled:", cur.fetchone()[0])
    cur.close()
    conn.close()
    connector.close()


if __name__ == "__main__":
    main()
