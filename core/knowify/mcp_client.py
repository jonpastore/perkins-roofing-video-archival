"""Knowify pull via the MCP HTTP endpoint — STOPGAP transport for jobs.knowify_sync.

Why this exists: Knowify's REST /oauth 500s on the RFC 8707 `resource` binding (Wave-0),
so a resource-bound REST token can't be minted and the REST pull path is dead. The Claude
Code MCP connector holds a working OAuth token bound to the /api/v2/mcp audience; the sync
job reuses it (via core.knowify.tokens.mcp_access_token) to drive the same `query` tool
from the container. Lifted from scripts/knowify/mcp_pull.py but self-contained (scripts/ is
.dockerignore'd, so the job cannot import it).

MONEY UNITS: the MCP/query layer returns invoice amounts in DOLLARS but payment `Amount`
in CENTS. `fetch_entity` normalizes payment Amount to dollars (÷100, Decimal, 2dp) so the
rest of the pipeline (raw mirror + promote, both written for REST=dollars) is unchanged.

FIELD NAMES already match what core.knowify.promote expects (Id/ClientName/TotalAmount/…) —
this is the exact pull→promote path the production seed used successfully.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any

from core.knowify.rest import MCP_URL, UA

log = logging.getLogger(__name__)

# entity (lowercase, as used by jobs.knowify_sync) -> MCP table + query spec.
# items is intentionally absent: its MCP field schema is unverified and items are
# secondary (Tim's sheet is authoritative for costs). fetch_entity returns [] for it.
_SPEC: dict[str, dict] = {
    "clients": {
        "table": "Clients",
        "fields": ["Id", "ClientName", "CompanyName", "Email", "PhoneNumber", "ObjectState",
                   # expanded 2026-07-11 for Legacy Data / Quotes UI
                   "Address1", "City", "StateProvince", "Zip", "PhoneNumberMobile",
                   "ContactName", "Notes", "PaymentTerms", "ParentId", "DateCreated"],
        # Knowify auto-filters to Active; include Inactive so invoices for inactive clients
        # resolve to a real customer and ObjectState carries our is_active flag.
        "where": {"ObjectState": {"$in": ["Active", "Inactive"]}},
    },
    "contacts": {
        "table": "Contacts",
        "fields": ["Id", "ClientId", "VendorId", "ContactName", "Email", "Phone",
                   "ObjectState", "DateCreated", "DateModified"],
        # Include inactive for the raw mirror's source completeness. Promotion skips
        # inactive contacts because the native contacts table has no soft-delete flag.
        "where": {"ObjectState": {"$in": ["Active", "Inactive"]}},
        "order": [["Id", "DESC"]],
    },
    "projects": {
        "table": "Projects",
        "fields": ["Id", "ProjectName", "ClientId", "ContractId", "DraftContractId",
                   "BusinessState", "ContractType", "ObjectState", "Address1", "City",
                   "StateProvince", "Zip", "DateCreated", "DueDate", "ProjectNumber",
                   "Notes", "SalesLead"],
        "order": [["Id", "DESC"]],
        # MONEY NOTE (verified 2026-07-11): Projects has no money fields.
    },
    "contracts": {
        "table": "Contracts",
        "fields": ["Id", "ContractType", "BusinessState", "ObjectState",
                   "OriginalContractSum", "CurrentContractSum", "AdditionalContractSum",
                   "DepositAmount", "ClientId", "ProjectId", "ContractName", "Description",
                   "ContactName", "PONumber", "DateCreated", "ExpirationDate", "StartDate",
                   "IsSigned", "IsChangeOrder", "PaymentTerms"],
        "order": [["Id", "DESC"]],
        # MONEY NOTE (verified 2026-07-11): Contracts money fields (OriginalContractSum,
        # CurrentContractSum, AdditionalContractSum, DepositAmount) are ALREADY DOLLARS
        # from the MCP layer — do NOT apply _cents_to_dollars. Only `payments` is cents.
    },
    "deliverables": {
        "table": "Deliverables",
        "fields": ["Id", "ContractId", "Description", "Quantity", "UnitPrice", "Price",
                   "UnitName", "BusinessState", "IsChangeOrder", "ChangeOrderNumber",
                   "CostLabor", "CostMaterials", "MarkupPercentage", "PriceBilled",
                   "UnitsBilled", "BillingPeriodicity", "IsTaxable", "ObjectState"],
        "order": [["Id", "DESC"]],
        # MONEY NOTE (verified 2026-07-11): Deliverables money fields (UnitPrice, Price,
        # CostLabor, CostMaterials, PriceBilled) are ALREADY DOLLARS — not cents.
    },
    "invoices": {
        "table": "Invoices",
        "fields": ["Id", "InvoiceNumber", "ClientId", "ProjectId", "BusinessState",
                   "ObjectState", "TotalAmount", "OutstandingAmount", "InvoiceDate", "DueDate",
                   # expanded 2026-07-11 for Legacy Data / Quotes UI
                   "PaymentTerms", "ForDeposit", "IsRetainage", "PONumber"],
        "order": [["Id", "DESC"]],
    },
    "payments": {
        "table": "Payments",
        "fields": ["Id", "Amount", "PaymentDate", "InvoiceId", "ReceivableId", "PayableId",
                   "Voided", "ObjectState", "isAIA", "CheckNumber", "isCreditCard"],
        "order": [["Id", "DESC"]],
        # MONEY NOTE: payments Amount is CENTS — _cents_to_dollars applies ONLY here.
    },
}


def _parse_sse(raw: bytes) -> dict:
    """Streamable-HTTP MCP replies as SSE: lines of 'data: <json>'. Return the last
    JSON object's parsed body (the JSON-RPC response).

    Fail loud if NO data frame parsed — a truncated/garbled reply must surface as a fetch
    error, not degrade to {} (which would look like a successful empty pull → stale-but-ok).
    """
    out: dict | None = None
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("data:"):
            try:
                out = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    if out is None:
        raise ValueError("MCP reply had no parseable SSE data frame")
    return out


class MCP:
    """Minimal MCP JSON-RPC client over streamable HTTP (one session per instance)."""

    def __init__(self, token: str):
        self.token = token
        self.sid: str | None = None

    def _post(self, payload: dict, notify: bool = False):
        body = json.dumps(payload).encode()
        h = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "User-Agent": UA}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(MCP_URL, data=body, headers=h, method="POST")
        r = urllib.request.urlopen(req, timeout=60)
        if r.headers.get("Mcp-Session-Id"):
            self.sid = r.headers["Mcp-Session-Id"]
        if notify:
            return None
        return _parse_sse(r.read())

    def initialize(self):
        self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "perkins-sync", "version": "1.0"}}})
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)
        except urllib.error.HTTPError:
            pass

    def query(self, table: str, fields=None, limit=100, offset=0, order=None, where=None) -> dict:
        args: dict[str, Any] = {"table": table, "limit": limit, "offset": offset}
        if fields:
            args["fields"] = fields
        if order:
            args["order"] = order
        if where:
            args["where"] = where
        resp = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "query", "arguments": args}})
        # Fail loud on a JSON-RPC error or a tool-level isError, so a degraded endpoint
        # surfaces as a per-entity fetch error — never a fake "ok" with zero rows.
        result = resp.get("result", {})
        if resp.get("error") or result.get("isError"):
            raise RuntimeError(f"MCP query error for table={table}")  # no token in message
        content = result.get("content") or []
        text = content[0].get("text") if content else json.dumps(result.get("structuredContent", {}))
        return json.loads(text)


def _pull_all(m: MCP, table: str, fields: list[str], order=None, where=None, page: int = 100) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        data = m.query(table, fields=fields, limit=page, offset=offset, order=order, where=where)
        batch = data.get("Data") or data.get("data") or []
        rows.extend(batch)
        total = data.get("Total")
        offset += page
        if len(batch) < page or (total and offset >= total):
            break
    return rows


def _cents_to_dollars(rows: list[dict]) -> list[dict]:
    """Normalize payment Amount cents->dollars (Decimal, 2dp) so promote sees dollars.
    Mirrors scripts/knowify/seed_from_json.py so seed and live sync agree exactly."""
    for r in rows:
        if r.get("Amount") is not None:
            r["Amount"] = str((Decimal(str(r["Amount"])) / 100).quantize(Decimal("0.01")))
    return rows


def fetch_entity(entity: str, access_token: str) -> list[dict[str, Any]]:
    """Full-pull one entity via MCP, returning REST-shaped records for the mirror/promote.

    Opens its own MCP session per call so a failure on one entity stays isolated (matches
    the REST path's per-entity isolation in jobs.knowify_sync). Raises on transport error;
    the caller marks that entity error and continues.
    """
    spec = _SPEC.get(entity)
    if spec is None:
        # items (and any future secondary entity): skipped in MCP mode, not an error.
        log.info("knowify mcp fetch: entity=%s skipped (no MCP spec)", entity)
        return []
    m = MCP(access_token)
    m.initialize()
    rows = _pull_all(m, spec["table"], spec["fields"],
                     order=spec.get("order"), where=spec.get("where"))
    if entity == "payments":
        rows = _cents_to_dollars(rows)
    log.info("knowify mcp fetch: entity=%s rows=%d", entity, len(rows))
    return rows
