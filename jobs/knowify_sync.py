"""Cloud Run Job / cron target: hourly Knowify data mirror sync.

Pulls all entities from the Knowify REST API via full-pull (v1, no since= filter)
and upserts into knowify_raw_records + first-class tables (clients/items/invoices/
payments). Tombstones rows absent from the current pull (hard-delete detection).

Single-flight: pg_try_advisory_lock key 8274124 (distinct from ingest 8274123
and token 8274125). A concurrent run grabs no lock and exits immediately.

Preflight: GET /api/v2/valid before any per-entity work. Dead token → all entities
marked auth_error, exit non-zero. No per-entity 401 storm.

Exit code: non-zero if any entity ends in error/auth_error (Cloud Run marks failed,
alert policy fires). Clean run exits 0.

Log safety (PII): logs carry entity + knowify_id + HTTP status ONLY — never raw
JSONB payloads (they contain customer PII). Payloads live only in the DB under RLS.

Run:
    python -m jobs.knowify_sync [--refresh-only]

    --refresh-only: keep-warm path — refresh tokens only, no data fetch.
"""
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text

import core.knowify.tokens as tokens
from app.models import SessionLocal
from core.knowify import mcp_client
from core.knowify.mirror import tombstone_absent, upsert_raw, write_state
from core.knowify.promote import promote_run
from core.tenant_loop import for_each_tenant

log = logging.getLogger(__name__)

_LOCK_KEY = 8274124  # distinct from ingest (8274123) and token (8274125)

# Transport for the pull: "rest" (default) or "mcp" (stopgap while REST /oauth 500s —
# see core/knowify/mcp_client.py). deploy.sh sets KNOWIFY_PULL_MODE=mcp on knowify-sync.
def _pull_mode() -> str:
    return os.getenv("KNOWIFY_PULL_MODE", "rest").strip().lower()

# Entities synced each run, in FK-safe order:
# clients first (contacts/projects/contracts reference clients), then contacts and projects,
# then contracts (deliverables reference contracts), then items/invoices/payments.
# (payments.invoice_id is NOT NULL FK to invoices.id — 0030:99)
# contracts/deliverables are raw-mirror-only — promote_run is NOT called for them.
SYNC_ENTITIES = ["clients", "contacts", "projects", "contracts", "deliverables", "items", "invoices", "payments"]

# ObjectState filter appended to GET requests where supported.
_OBJECT_STATE_FILTER = {"where[ObjectState][$in]": "Active,Cancelled,Deleted"}


# ---------------------------------------------------------------------------
# Advisory lock — single-flight
# ---------------------------------------------------------------------------

@contextmanager
def _single_flight():
    """Yield True if this process holds the sync advisory lock, False to skip.

    Session-scoped: process death auto-releases. No-op on SQLite (always True).
    Key 8274124 is distinct from ingest (8274123) and token refresh (8274125).
    """
    s = SessionLocal()
    s.info["platform_scope"] = True  # platform-level; no tenant GUC needed
    is_pg = s.bind.dialect.name == "postgresql"
    held = True
    try:
        if is_pg:
            held = bool(
                s.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar()
            )
        yield held
    finally:
        try:
            if held and is_pg:
                s.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                s.commit()
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Fetch (injectable / mockable)
# ---------------------------------------------------------------------------

def _fetch_entity(entity: str, tok: dict) -> list[dict[str, Any]]:
    """Full-pull GET /api/v2/<entity> with ObjectState filter, offset-paginated.

    Returns all records for the entity. Raises on HTTP error (caller handles).
    Adapts knowify_pull._get + _records with the ObjectState filter for tombstoning.

    knowify_pull lives under scripts/ (.dockerignore'd), so it's imported lazily HERE —
    only the REST path touches it. The MCP path (mcp_client) never imports scripts, so
    the container starts cleanly when KNOWIFY_PULL_MODE=mcp.
    """
    from scripts.knowify.knowify_pull import _get, _records  # noqa: PLC0415

    params = {"limit": 100, "offset": 0, **_OBJECT_STATE_FILTER}
    all_rows = []
    while True:
        resp, tok = _get("/" + entity, tok, params)
        rows, _ = _records(resp)
        all_rows.extend(rows)
        if len(rows) < params["limit"]:
            break
        params = {**params, "offset": params["offset"] + params["limit"]}
    return all_rows


# ---------------------------------------------------------------------------
# Per-tenant sync body
# ---------------------------------------------------------------------------

def _sync_tenant(
    db,
    tenant_id: int,
    tok: dict,
    entity_data: dict[str, list],
    fetch_errors: set[str],
    tombstone: bool = True,
) -> dict:
    """Upsert raw + tombstone + promote for all entities for one tenant.

    entity_data: pre-fetched {entity: [records]} (fetch happens outside the
    tenant loop so a fetch error is isolated before touching any tenant's DB).
    fetch_errors: set of entity names that failed at fetch time.
    Returns {entity: status} dict with a status for every entity in SYNC_ENTITIES.

    Two-phase commit: raw+state writes are committed first so a promote failure
    (per-record FK violation that corrupts the SA session) does not roll back
    the raw mirror or sync_state. Promote runs in a second transaction.
    """
    statuses: dict[str, str] = {e: "error" for e in fetch_errors}

    # ---- Phase 1: raw upsert + tombstone + write_state (committed before promote) ----
    for entity in SYNC_ENTITIES:
        records = entity_data.get(entity)
        if records is None:
            # Entity errored at fetch time — write error state, then continue.
            try:
                write_state(db, entity, rows_seen=0, status="error")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                log.error(
                    "knowify sync: write_state entity=%s tenant=%d error=%s",
                    entity, tenant_id, type(exc).__name__,
                )
            continue

        try:
            present_ids = {str(r["Id"]) for r in records}
            upsert_raw(db, entity, records)
            # MCP mode skips tombstoning: its pull is not guaranteed to enumerate every
            # non-deleted ObjectState the way the REST ObjectState filter does, so a
            # missing row could be an incomplete pull, not a real delete. A stale
            # un-tombstoned row is far safer than wrongly hard-deleting 7k customers.
            # ponytail: no hard-delete detection in mcp mode; the REST path restores it.
            if tombstone:
                tombstone_absent(db, entity, present_ids)
            write_state(db, entity, rows_seen=len(records), status="ok")
            statuses[entity] = "ok"
            log.info(
                "knowify sync: entity=%s tenant=%d rows_seen=%d status=ok",
                entity, tenant_id, len(records),
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            write_state(db, entity, rows_seen=0, status="error")
            statuses[entity] = "error"
            log.error(
                "knowify sync: entity=%s tenant=%d status=error error=%s",
                entity, tenant_id, type(exc).__name__,
            )

    # Commit phase-1 writes so promote cannot roll them back.
    db.commit()
    # Re-stamp tenant_id after commit (new transaction).
    db.info["tenant_id"] = tenant_id

    # ---- Phase 2: promote (FK-safe order: clients → items → invoices → payments) ----
    # promote_run catches per-record exceptions internally. A flush exception inside
    # promote_invoices/promote_payments marks the SA transaction DEACTIVE even when
    # caught at the record level. We always rollback after promote to reset the session
    # to a clean state for the outer for_each_tenant commit.
    try:
        promote_run(
            db,
            clients=entity_data.get("clients"),
            contacts=entity_data.get("contacts"),
            projects=entity_data.get("projects"),
            items=entity_data.get("items"),
            invoices=entity_data.get("invoices"),
            payments=entity_data.get("payments"),
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error(
            "knowify sync: promote raised tenant=%d error=%s",
            tenant_id, type(exc).__name__,
        )
        return statuses

    # Probe: a per-record flush exception inside promote_run (caught at the record level)
    # can leave the session DEACTIVE without raising. Detect and recover.
    try:
        db.flush()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error(
            "knowify sync: session deactive after promote tenant=%d error=%s",
            tenant_id, type(exc).__name__,
        )

    return statuses


def _fetch_entity_mcp(entity: str, access_token: str) -> list[dict[str, Any]]:
    """Full-pull one entity via the MCP transport (stopgap). Raises on transport error.

    Thin wrapper over core.knowify.mcp_client.fetch_entity so tests can patch this seam
    the same way they patch _fetch_entity for the REST path.
    """
    return mcp_client.fetch_entity(entity, access_token)


def _mark_all_auth_error(db, tenant_id: int) -> None:
    """Write auth_error into sync_state for every entity (per-tenant). Used by both
    transports when the token is dead/unrefreshable — no per-entity 401 storm."""
    for entity in SYNC_ENTITIES:
        write_state(db, entity, rows_seen=0, status="auth_error")
        log.error("knowify sync: entity=%s tenant=%d status=auth_error", entity, tenant_id)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(limit=None, refresh_only: bool = False) -> dict:  # noqa: ARG001 (limit unused in v1)
    """Run the Knowify sync job.

    Transport is chosen by KNOWIFY_PULL_MODE: "rest" (default) or "mcp" (stopgap while
    REST /oauth 500s). refresh_only=True: keep-warm path — refresh the token only, no fetch.
    Returns dict with exit_code (0=clean, 1=any error/auth_error).
    """
    logging.basicConfig(level=logging.INFO)
    mode = _pull_mode()

    if refresh_only:
        rc = tokens.mcp_refresh_only() if mode == "mcp" else tokens.refresh_only()
        return {"exit_code": rc, "mode": "refresh_only", "pull_mode": mode}

    with _single_flight() as ok:
        if not ok:
            log.info("knowify sync: already running (advisory lock held) — skip")
            return {"skipped": "knowify sync already running", "exit_code": 0}

        # Acquire a token + pick the fetch transport. A dead/unrefreshable token →
        # mark all entities auth_error, exit non-zero (no per-entity 401 storm).
        if mode == "mcp":
            try:
                access = tokens.mcp_access_token()
            except tokens.AuthError:
                log.error("knowify sync (mcp): token refresh failed — all entities auth_error")
                for_each_tenant(SessionLocal, _mark_all_auth_error)
                return {"exit_code": 1, "auth_error": True}
            tok = {"access_token": access}  # carried through for the _sync_tenant signature
            def _fetch(entity: str) -> list[dict[str, Any]]:
                return _fetch_entity_mcp(entity, access)
            do_tombstone = False  # MCP pull can't safely detect hard-deletes (see _sync_tenant)
        else:
            tok = tokens.load_tokens()
            if not tokens.is_valid(tok):
                log.error(
                    "knowify sync: /api/v2/valid returned dead token — all entities auth_error"
                )
                for_each_tenant(SessionLocal, _mark_all_auth_error)
                return {"exit_code": 1, "auth_error": True}
            def _fetch(entity: str) -> list[dict[str, Any]]:
                return _fetch_entity(entity, tok)
            do_tombstone = True

        # Fetch all entities BEFORE opening tenant sessions.
        # Network errors are isolated per entity; a bad entity does not block others.
        entity_data: dict[str, list | None] = {}
        fetch_errors: set[str] = set()

        for entity in SYNC_ENTITIES:
            try:
                entity_data[entity] = _fetch(entity)
                log.info(
                    "knowify sync: fetched entity=%s rows=%d",
                    entity, len(entity_data[entity]),
                )
            except Exception as exc:  # noqa: BLE001
                entity_data[entity] = None
                fetch_errors.add(entity)
                log.error(
                    "knowify sync: fetch entity=%s status=error error=%s",
                    entity, type(exc).__name__,
                )

        # Per-tenant upsert + promote.
        all_statuses: dict[str, str] = {}

        def _fn(db, tenant_id: int) -> None:
            tenant_statuses = _sync_tenant(
                db, tenant_id, tok, entity_data, fetch_errors, tombstone=do_tombstone
            )
            all_statuses.update(tenant_statuses)

        for_each_tenant(SessionLocal, _fn)

        # Exit non-zero if any entity ended in error or auth_error (AC-17).
        has_failure = any(
            s in ("error", "auth_error") for s in all_statuses.values()
        )
        return {"exit_code": 1 if has_failure else 0, "statuses": all_statuses}


if __name__ == "__main__":
    refresh_only = "--refresh-only" in sys.argv[1:]
    result = run(refresh_only=refresh_only)
    sys.exit(result.get("exit_code", 0))
