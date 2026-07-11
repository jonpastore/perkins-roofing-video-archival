#!/usr/bin/env python3
"""Headless Knowify pull via the MCP HTTP endpoint — STOPGAP while Knowify's REST
OAuth is broken (their /oauth server 500s on the RFC 8707 `resource` binding, so a
resource-bound REST token can't be minted). The Claude Code MCP connector already
holds a valid OAuth token bound to https://assistant.knowify.com/api/v2/mcp; we
reuse it to drive the same `query` tool from a script (no interactive tool calls).

    python scripts/knowify/mcp_pull.py > /tmp/knowify_dump.json

Reads the token from Claude Code's creds (KNOWIFY_MCP_CREDS overrides the path).
Pulls clients + invoices + payments (the entities promote.py first-classes).

NOTE ON MONEY UNITS: the MCP/query layer returns invoice amounts in DOLLARS but
payment `Amount` in CENTS. This script emits raw values + a `_payments_in_cents:true`
flag; the seed step divides payment amounts by 100 (REST would already be dollars).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

MCP_URL = "https://assistant.knowify.com/api/v2/mcp"
CREDS = os.environ.get("KNOWIFY_MCP_CREDS", os.path.expanduser("~/.claude/.credentials.json"))
UA = "perkins-knowify-mcp-pull/1.0"


def _load_token() -> str:
    d = json.load(open(CREDS))
    for k, v in d.get("mcpOAuth", {}).items():
        if k.startswith("knowify") and v.get("accessToken"):
            return v["accessToken"]
    sys.exit("no knowify MCP token in creds — connect the Knowify MCP first")


def _parse_sse(raw: bytes) -> dict:
    """Streamable-HTTP MCP replies as SSE: lines of 'data: <json>'. Return the last
    JSON object's parsed body (the JSON-RPC response)."""
    out = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("data:"):
            try:
                out = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    return out


class MCP:
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
                               "clientInfo": {"name": "perkins-seed", "version": "1.0"}}})
        # required follow-up notification
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notify=True)
        except urllib.error.HTTPError:
            pass

    def query(self, table: str, fields=None, limit=100, offset=0, order=None, where=None):
        args = {"table": table, "limit": limit, "offset": offset}
        if fields:
            args["fields"] = fields
        if order:
            args["order"] = order
        if where:
            args["where"] = where
        resp = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "query", "arguments": args}})
        result = resp.get("result", {})
        content = result.get("content") or []
        text = content[0].get("text") if content else json.dumps(result.get("structuredContent", {}))
        return json.loads(text)


def pull_all(m: MCP, table: str, fields: list[str], order=None, page=100, cap=None, where=None) -> list[dict]:
    rows, offset = [], 0
    while True:
        data = m.query(table, fields=fields, limit=page, offset=offset, order=order, where=where)
        batch = data.get("Data") or data.get("data") or []
        rows.extend(batch)
        total = data.get("Total")
        offset += page
        if len(batch) < page or (cap and len(rows) >= cap) or (total and offset >= total):
            break
    return rows if not cap else rows[:cap]


def main():
    cap = int(os.environ.get("KNOWIFY_CAP", "0")) or None
    m = MCP(_load_token())
    m.initialize()
    # Include INACTIVE clients (Knowify auto-filters to Active) so invoices for inactive
    # clients resolve to a real customer, and carry ObjectState → our is_active flag.
    clients = pull_all(m, "Clients",
                       ["Id", "ClientName", "CompanyName", "Email", "PhoneNumber", "ObjectState"],
                       where={"ObjectState": {"$in": ["Active", "Inactive"]}}, cap=cap)
    invoices = pull_all(m, "Invoices",
                        ["Id", "InvoiceNumber", "ClientId", "ProjectId", "BusinessState",
                         "ObjectState", "TotalAmount", "OutstandingAmount", "InvoiceDate", "DueDate"],
                        order=[["Id", "DESC"]], cap=cap)
    payments = pull_all(m, "Payments",
                        ["Id", "Amount", "PaymentDate", "InvoiceId", "ReceivableId", "PayableId",
                         "Voided", "ObjectState", "isAIA", "CheckNumber", "isCreditCard"],
                        order=[["Id", "DESC"]], cap=cap)
    json.dump({"_payments_in_cents": True, "clients": clients, "invoices": invoices,
               "payments": payments}, sys.stdout)
    sys.stderr.write(f"pulled clients={len(clients)} invoices={len(invoices)} payments={len(payments)}\n")


if __name__ == "__main__":
    main()
