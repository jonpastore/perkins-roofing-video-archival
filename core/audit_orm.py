"""ORM-level change tracking: before/after values for every audited model write.

Why at the ORM and not in the routes: before/after has to be captured around the mutation
itself, and there are 86 mutating endpoints. Per-route snapshots would cover the ones someone
remembered on the day, and the revert you actually need would be the one that was missed.
SQLAlchemy already knows precisely which attributes changed and what they were — this reads
that, instead of asking humans to re-state it.

Shape:
  before_flush  — capture (SQLAlchemy still holds the old values here; after commit they are
                  gone, so this is the only moment the "before" side exists)
  after_commit  — write, in a separate transaction, only once the change is real. Auditing in
                  before_flush would log changes that then rolled back.

Scoped to AUDITED_MODELS: the business objects a human would want to undo. Auditing every row
of every table would bury those under embedding writes and job bookkeeping.
"""
from __future__ import annotations

import logging

from sqlalchemy import event, inspect

from core.audit import current_actor, diff, snapshot

log = logging.getLogger(__name__)

# The things a person creates, edits, signs — and would ask to have back.
AUDITED_MODELS: frozenset[str] = frozenset({
    "Article", "Clip", "MiniSeries", "SocialPost", "ScheduledContent",
    "Estimate", "Proposal", "Invoice", "Payment", "Customer", "Measurement",
    "PriceBookItem", "PricingConfig", "Faq", "ContractFaq", "Tenant", "UserSettings",
})

_BUFFER = "_audit_pending"


def _describe(obj) -> tuple[str, str | None]:
    """(entity_type, entity_id) for a model instance, using its real primary key."""
    name = type(obj).__name__
    try:
        pk = inspect(obj).identity
        return name, (str(pk[0]) if pk and pk[0] is not None else None)
    except Exception:  # noqa: BLE001
        return name, None


def _changed_fields(obj) -> dict:
    """{field: {"from": x, "to": y}} using SQLAlchemy's own attribute history.

    Read in before_flush deliberately: this is the last moment the old values exist in memory.
    """
    before, after = {}, {}
    state = inspect(obj)
    for attr in state.attrs:
        hist = attr.history
        if not hist.has_changes():
            continue
        before[attr.key] = hist.deleted[0] if hist.deleted else None
        after[attr.key] = hist.added[0] if hist.added else None
    return diff(before, after)


def _capture(session, _flush_context=None, _instances=None) -> None:
    """Buffer pending audit rows. Never raises: auditing must not block a write."""
    try:
        pending = session.info.setdefault(_BUFFER, [])
        for obj, verb in (
            [(o, "create") for o in session.new]
            + [(o, "update") for o in session.dirty]
            + [(o, "delete") for o in session.deleted]
        ):
            etype = type(obj).__name__
            if etype not in AUDITED_MODELS:
                continue
            if verb == "update" and not session.is_modified(obj, include_collections=False):
                continue
            name, eid = _describe(obj)
            # Every path goes through diff(): it owns secret redaction, and building the
            # create/delete payloads by hand bypassed it and captured a secret_token in full.
            if verb == "create":
                changes = diff({}, snapshot(obj))
            elif verb == "delete":
                # The whole row: a delete is the change most likely to need undoing.
                changes = diff(snapshot(obj), {})
            else:
                changes = _changed_fields(obj)
            if not changes:
                continue
            pending.append({
                "tenant_id": getattr(obj, "tenant_id", None) or session.info.get("tenant_id"),
                "action": f"{name.lower()}.{verb}",
                "entity_type": name,
                "entity_id": eid,
                "changes": changes,
                # An INSERT has no identity yet at before_flush — the PK is assigned by the
                # flush. Without re-reading it after commit, every create would record
                # entity_id=None and "which proposal was created?" would be unanswerable.
                "_obj": obj,
            })
    except Exception as exc:  # noqa: BLE001
        log.error("audit capture failed (write proceeds): %s", exc)


def _flush_buffer(session) -> None:
    """Write buffered rows after the transaction really committed."""
    pending = session.info.pop(_BUFFER, None)
    if not pending:
        return
    try:
        from api.audit_mw import write  # noqa: PLC0415 — avoid an app<-core import at module load

        actor = current_actor.get() or {}
        for row in pending:
            tenant_id = row.pop("tenant_id", None)
            obj = row.pop("_obj", None)
            if row.get("entity_id") is None and obj is not None:
                # Now that the flush has run, the PK exists. Reads the identity key only —
                # not attributes — so it cannot trigger a refresh on an expired instance.
                try:
                    row["entity_id"] = _describe(obj)[1]
                except Exception:  # noqa: BLE001
                    pass
            if tenant_id is None:
                # Nothing to scope it to; audit_log is RLS-tenant-scoped. Say so rather than
                # drop it silently — a gap that looks like inactivity is the worst outcome.
                log.info("audit(no-tenant) %s %s", row.get("action"), row.get("entity_id"))
                continue
            write(
                tenant_id=int(tenant_id),
                action=row["action"],
                actor_email=actor.get("email"),
                actor_role=actor.get("role"),
                impersonating=bool(actor.get("impersonating")),
                impersonating_as=actor.get("impersonating_as"),
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                source=actor.get("source") or ("api" if actor.get("email") else "job"),
                request_id=actor.get("request_id"),
                detail={"changes": row["changes"]},
            )
    except Exception as exc:  # noqa: BLE001
        log.error("audit flush failed: %s", exc)


def _discard_buffer(session) -> None:
    """Rolled back: the change never happened, so neither did the audit row."""
    session.info.pop(_BUFFER, None)


def register_change_tracking(session_factory) -> None:
    """Attach change tracking to a sessionmaker. Idempotent, and a no-op when auditing is off."""
    from app.config import settings  # noqa: PLC0415

    if not settings.AUDIT_ENABLED:
        return
    if getattr(session_factory, "_audit_tracking", False):
        return
    event.listen(session_factory, "before_flush", _capture)
    event.listen(session_factory, "after_commit", _flush_buffer)
    event.listen(session_factory, "after_rollback", _discard_buffer)
    session_factory._audit_tracking = True
