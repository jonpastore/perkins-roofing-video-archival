"""Audit trail — who did what, when, and what happened.

Two layers, deliberately:

1. **Blanket.** api/audit_mw.py records EVERY mutating HTTP request. There are 86 mutating
   endpoints across 25 route modules; per-route calls would cover 86 of them and miss the 87th
   the day someone adds it. Coverage that depends on remembering isn't coverage.
2. **Semantic.** Domain code calls `record()` where the route alone doesn't say what happened.
   "POST /proposals/3/sign" is a fact; "proposal.sign by tim@ for customer 12, $18,400" is the
   thing you actually want at 2am.

This module is pure — naming and redaction, no I/O — so it is testable without a database.
`write()` in api/audit_mw.py owns persistence.

REDACTION IS NOT OPTIONAL. An audit log is a high-value target and a long-lived one: it is the
last place a password or token should land. Everything is denied by default — only fields on
`SAFE_KEYS` are stored, and even then values are truncated. If you find yourself widening
SAFE_KEYS to debug something, log it to the app logger instead.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any

# Who is acting, for code far from the request that cannot be handed the claims — chiefly the
# ORM change tracker, which sees a model mutate but has no idea who asked. Set by
# api/audit_mw.py per request; empty in jobs, which record themselves as source="job".
current_actor: contextvars.ContextVar[dict] = contextvars.ContextVar("audit_actor", default={})

# Before/after values are kept so a bad admin edit can be reverted, so the cap is far more
# generous than a log line's — an article body is ~20k chars and a truncated "before" cannot
# restore anything. Past this we keep the marker and admit the row is not revert-capable
# rather than pretending it is.
_MAX_REVERT_LEN = 8000

# Values worth keeping on an audit row: identifiers, statuses, counts, names of things. If a
# key is not here, the value is dropped and only its presence is noted. Deny-by-default,
# because the cost of a missing field is an inconvenience and the cost of a leaked one is a
# credential in a table that is retained forever and read by support staff.
SAFE_KEYS: frozenset[str] = frozenset({
    "id", "slug", "status", "state", "kind", "type", "role", "action", "reason",
    "name", "title", "subject", "topic", "keyword", "focus_keyword",
    "tenant_id", "video_id", "article_id", "proposal_id", "estimate_id", "invoice_id",
    "customer_id", "clip_id", "job_id", "series_id", "cluster_id", "post_id", "wp_post_id",
    "count", "total", "amount", "price", "quantity", "words", "score", "version",
    "email", "to_email", "from_email", "recipient",
    "start", "end", "publish_at", "scheduled_at", "due_date",
    "signed_by", "signed_at", "approved_by", "sent_by", "created_by", "updated_by",
})

# Substring match, case-insensitive: anything whose NAME smells like a credential is dropped
# even if it somehow appears on SAFE_KEYS. Belt and braces — a future edit to SAFE_KEYS should
# not be able to start leaking secrets.
_SECRET_HINTS = (
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "key",
    "authorization", "auth", "credential", "cookie", "session", "signature", "private",
    "ssn", "card", "cvv", "iban", "account_number", "routing",
)

_MAX_VALUE_LEN = 200
_MAX_KEYS = 40
_REDACTED = "[redacted]"

# Fallback only. The caller normally passes FastAPI's matched route template ("/articles/{slug}")
# and its path_params, which are authoritative — guessing which segment is an id cannot tell a
# slug ("wall-flashings") from a sub-resource, and got that wrong the first time this was
# written. This pattern is used only for unmatched paths (404s), where precision is moot.
_ID_SEG = re.compile(r"^(?:\d+|[0-9a-f]{8,}(?:-[0-9a-f]{4,}){0,4}|[^/]{24,})$", re.IGNORECASE)


def is_secretish(key: str) -> bool:
    """True when a field name suggests a credential. Errs toward dropping."""
    k = (key or "").lower()
    return any(h in k for h in _SECRET_HINTS)


def redact(payload: Any, _depth: int = 0) -> Any:
    """Reduce arbitrary data to something safe to keep forever.

    Deny-by-default: unknown keys are replaced with a presence marker rather than their value,
    so a new field on a request body cannot silently start being persisted.
    """
    if _depth > 3:
        return "[deep]"
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(payload.items()):
            if i >= _MAX_KEYS:
                out["[truncated]"] = f"{len(payload) - _MAX_KEYS} more field(s)"
                break
            key = str(k)
            if is_secretish(key):
                out[key] = _REDACTED
            elif key.lower() in SAFE_KEYS:
                out[key] = redact(v, _depth + 1)
            else:
                # Not known-safe: keep the shape, drop the content.
                out[key] = "[omitted]" if v is not None else None
        return out
    if isinstance(payload, (list, tuple)):
        return [redact(v, _depth + 1) for v in payload[:10]]
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    s = str(payload)
    return s if len(s) <= _MAX_VALUE_LEN else s[:_MAX_VALUE_LEN] + "…"


def template_path(path: str) -> str:
    """Collapse obvious identifier segments. Fallback for paths that matched no route."""
    parts = ["{id}" if seg and _ID_SEG.match(seg) else seg for seg in (path or "").split("/")]
    return "/".join(parts) or "/"


def _singular(seg: str) -> str:
    if seg.endswith("ies") and len(seg) > 3:
        return seg[:-3] + "y"
    if seg.endswith("ss") or seg == "status":
        return seg
    return seg[:-1] if seg.endswith("s") else seg


def _literal_segments(route: str) -> list[str]:
    """The non-parameter parts of a route template: /articles/{slug}/fix-seo -> [articles, fix-seo]."""
    return [s for s in (route or "").split("/") if s and not s.startswith("{")]


def action_for(method: str, route: str) -> str:
    """A stable, greppable name for what was attempted: "article.create", "proposal.sign".

    `route` is FastAPI's matched template ("/proposals/{proposal_id}/sign"), so the name
    derives from the code's own routing table and cannot drift the way a hand-written constant
    does. Ids never appear in the name — otherwise "what happened to proposals" needs a LIKE
    scan instead of an index hit.
    """
    verbs = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
    segs = _literal_segments(route)
    if not segs:
        return f"{(method or 'request').lower()}.root"
    noun = _singular(segs[0]).replace("_", "-")
    # A trailing literal after the id is the real verb: POST /proposals/{id}/sign -> proposal.sign
    if len(segs) > 1:
        return f"{noun}.{segs[-1].replace('_', '-')}"
    return f"{noun}.{verbs.get((method or '').upper(), (method or 'request').lower())}"


def entity_from(route: str, path_params: dict | None = None) -> tuple[str | None, str | None]:
    """(entity_type, entity_id) from the matched route + its path params.

    Uses the framework's own parsed params rather than guessing which path segment is an id —
    a guess cannot distinguish the slug "wall-flashings" from a sub-resource, which is exactly
    what it got wrong.
    """
    segs = _literal_segments(route)
    etype = _singular(segs[0]) if segs else None
    params = path_params or {}
    for key in ("id", "slug", "proposal_id", "estimate_id", "article_id", "customer_id",
                "invoice_id", "video_id", "clip_id", "job_id"):
        if key in params and params[key] is not None:
            return etype, str(params[key])
    for value in params.values():          # any param beats none
        if value is not None:
            return etype, str(value)
    return etype, None


# ── before/after capture, so an admin edit can be undone ──────────────────────

def _revert_value(value: Any) -> Any:
    """A stored before/after value: whole if we can, honestly marked if we cannot.

    Truncation is the enemy of revert — a clipped "before" restores nothing — so the cap is
    generous and exceeding it is reported rather than hidden. Silent truncation is how a
    revert-capable log quietly becomes a decorative one.
    """
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    s = value if isinstance(value, str) else str(value)
    if len(s) <= _MAX_REVERT_LEN:
        return s
    return {"_truncated": True, "_len": len(s), "value": s[:_MAX_REVERT_LEN]}


def diff(before: dict, after: dict) -> dict:
    """Changed fields only, as {field: {"from": x, "to": y}}.

    Only what changed: storing every column of every row would bury the one field that
    actually moved, which is the field a revert needs. Secret-named fields are recorded as
    changed but never with their values — an audit row is the last place a credential should
    land, even at the cost of not being able to revert it from here.
    """
    out: dict[str, Any] = {}
    for key in set(before or {}) | set(after or {}):
        was, now = (before or {}).get(key), (after or {}).get(key)
        if was == now:
            continue
        if is_secretish(str(key)):
            out[str(key)] = {"from": _REDACTED, "to": _REDACTED, "changed": True}
        else:
            out[str(key)] = {"from": _revert_value(was), "to": _revert_value(now)}
    return out


def snapshot(obj: Any, fields: list[str] | None = None) -> dict:
    """Column values of a SQLAlchemy model instance, for use as a before/after side."""
    try:
        cols = [c.name for c in obj.__table__.columns]
    except AttributeError:
        return {}
    names = [f for f in (fields or cols) if f in cols]
    return {n: getattr(obj, n, None) for n in names}
