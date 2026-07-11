"""Knowify MCP-transport tests (stopgap pull path) — network MOCKED.

Contract under test:
- SSE parsing returns the last `data:` JSON object (the JSON-RPC response).
- payment Amount is normalized cents->dollars (Decimal, 2dp) — the money gotcha that
  the REST path never hits (REST is already dollars).
- fetch_entity pulls each entity with the exact table/fields/where promote expects, and
  returns [] for `items` (no MCP spec — secondary entity).
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from core.knowify import mcp_client as M

# --------------------------------------------------------------------------- #
# SSE parsing
# --------------------------------------------------------------------------- #

def test_parse_sse_returns_last_data_json():
    raw = b"data: {\"a\": 1}\n\ndata: {\"b\": 2}\n"
    assert M._parse_sse(raw) == {"b": 2}


def test_parse_sse_ignores_non_data_and_bad_json():
    raw = b": comment\ndata: not-json\ndata: {\"ok\": true}\n"
    assert M._parse_sse(raw) == {"ok": True}


def test_parse_sse_raises_when_no_data_frame():
    # no parseable data: frame -> fail loud (must not degrade to {} = fake empty pull)
    with pytest.raises(ValueError):
        M._parse_sse(b"event: ping\n")


def test_query_raises_on_tool_error(monkeypatch):
    m = M.MCP("tok")
    monkeypatch.setattr(m, "_post", lambda p: {"result": {"isError": True,
                                                          "content": [{"text": "boom"}]}})
    with pytest.raises(RuntimeError):
        m.query("Clients", fields=["Id"])


def test_query_raises_on_jsonrpc_error(monkeypatch):
    m = M.MCP("tok")
    monkeypatch.setattr(m, "_post", lambda p: {"error": {"code": -32000, "message": "nope"}})
    with pytest.raises(RuntimeError):
        m.query("Clients", fields=["Id"])


# --------------------------------------------------------------------------- #
# cents -> dollars normalization (money)
# --------------------------------------------------------------------------- #

def test_cents_to_dollars_divides_by_100():
    rows = [{"Id": "1", "Amount": 667800}, {"Id": "2", "Amount": 1}]
    M._cents_to_dollars(rows)
    assert rows[0]["Amount"] == "6678.00"
    assert rows[1]["Amount"] == "0.01"


def test_cents_to_dollars_leaves_none():
    rows = [{"Id": "1", "Amount": None}, {"Id": "2"}]
    M._cents_to_dollars(rows)
    assert rows[0]["Amount"] is None
    assert "Amount" not in rows[1]


def test_cents_to_dollars_matches_money_decimal():
    """A normalized string round-trips through the same _money the seed used."""
    from core.invoicing import _money
    rows = [{"Amount": 667800}]
    M._cents_to_dollars(rows)
    assert _money(rows[0]["Amount"]) == Decimal("6678.00")


# --------------------------------------------------------------------------- #
# MCP.query — parses content[0].text into a dict
# --------------------------------------------------------------------------- #

def test_query_parses_content_text(monkeypatch):
    payload = {"Data": [{"Id": "1"}], "Total": 1}
    resp = {"result": {"content": [{"text": json.dumps(payload)}]}}
    m = M.MCP("tok")
    sent = {}
    monkeypatch.setattr(m, "_post", lambda p: sent.update(p) or resp)
    # pass order + where so those arg branches are built into the JSON-RPC call
    out = m.query("Clients", fields=["Id"], order=[["Id", "DESC"]], where={"ObjectState": "Active"})
    assert out == payload
    args = sent["params"]["arguments"]
    assert args["order"] == [["Id", "DESC"]]
    assert args["where"] == {"ObjectState": "Active"}


def test_query_falls_back_to_structured_content(monkeypatch):
    resp = {"result": {"structuredContent": {"Data": [], "Total": 0}}}
    m = M.MCP("tok")
    monkeypatch.setattr(m, "_post", lambda p: resp)
    assert m.query("Invoices") == {"Data": [], "Total": 0}


# --------------------------------------------------------------------------- #
# _pull_all — offset pagination stops on short page / Total
# --------------------------------------------------------------------------- #

def test_pull_all_paginates_until_short_page(monkeypatch):
    pages = [
        {"Data": [{"Id": str(i)} for i in range(100)], "Total": 150},
        {"Data": [{"Id": str(i)} for i in range(100, 150)], "Total": 150},
    ]
    calls = iter(pages)
    m = M.MCP("tok")
    monkeypatch.setattr(m, "query", lambda *a, **k: next(calls))
    rows = M._pull_all(m, "Invoices", ["Id"], page=100)
    assert len(rows) == 150


def test_pull_all_single_short_page(monkeypatch):
    m = M.MCP("tok")
    monkeypatch.setattr(m, "query", lambda *a, **k: {"Data": [{"Id": "1"}], "Total": 1})
    assert M._pull_all(m, "Clients", ["Id"], page=100) == [{"Id": "1"}]


# --------------------------------------------------------------------------- #
# fetch_entity — spec-driven pull + per-entity behavior
# --------------------------------------------------------------------------- #

def _stub_pull(monkeypatch, rows, capture=None):
    monkeypatch.setattr(M.MCP, "initialize", lambda self: None)

    def _fake(m, table, fields, order=None, where=None, page=100):
        if capture is not None:
            capture.update(table=table, fields=fields, order=order, where=where)
        return rows
    monkeypatch.setattr(M, "_pull_all", _fake)


def test_fetch_entity_payments_normalized(monkeypatch):
    _stub_pull(monkeypatch, [{"Id": "1", "Amount": 667800}])
    out = M.fetch_entity("payments", "tok")
    assert out[0]["Amount"] == "6678.00"


def test_fetch_entity_invoices_not_normalized(monkeypatch):
    _stub_pull(monkeypatch, [{"Id": "1", "TotalAmount": 6678.00}])
    out = M.fetch_entity("invoices", "tok")
    assert out[0]["TotalAmount"] == 6678.00  # invoices already dollars — untouched


def test_fetch_entity_clients_uses_spec(monkeypatch):
    cap: dict = {}
    _stub_pull(monkeypatch, [{"Id": "1"}], capture=cap)
    M.fetch_entity("clients", "tok")
    assert cap["table"] == "Clients"
    assert "ClientName" in cap["fields"]
    assert cap["where"] == {"ObjectState": {"$in": ["Active", "Inactive"]}}


def test_fetch_entity_items_skipped(monkeypatch):
    # items has no MCP spec — returns [] without any pull
    monkeypatch.setattr(M, "_pull_all", lambda *a, **k: pytest.fail("must not pull items"))
    assert M.fetch_entity("items", "tok") == []


# --------------------------------------------------------------------------- #
# New entities: contracts / projects / deliverables
# --------------------------------------------------------------------------- #

def test_spec_has_contracts_entry():
    spec = M._SPEC["contracts"]
    assert spec["table"] == "Contracts"
    for f in ("Id", "ContractName", "ClientId", "ProjectId",
              "OriginalContractSum", "CurrentContractSum", "IsSigned"):
        assert f in spec["fields"], f"contracts spec missing field {f!r}"
    assert spec.get("order") == [["Id", "DESC"]]


def test_spec_has_projects_entry():
    spec = M._SPEC["projects"]
    assert spec["table"] == "Projects"
    for f in ("Id", "ProjectName", "ClientId", "Address1", "City", "StateProvince", "Zip"):
        assert f in spec["fields"], f"projects spec missing field {f!r}"
    assert spec.get("order") == [["Id", "DESC"]]


def test_spec_has_deliverables_entry():
    spec = M._SPEC["deliverables"]
    assert spec["table"] == "Deliverables"
    for f in ("Id", "ContractId", "Description", "Quantity", "UnitPrice", "Price"):
        assert f in spec["fields"], f"deliverables spec missing field {f!r}"
    assert spec.get("order") == [["Id", "DESC"]]


def test_spec_clients_expanded():
    fields = M._SPEC["clients"]["fields"]
    for f in ("Address1", "City", "StateProvince", "Zip", "PhoneNumberMobile",
              "ContactName", "Notes", "PaymentTerms", "ParentId", "DateCreated"):
        assert f in fields, f"clients spec missing expanded field {f!r}"


def test_spec_invoices_expanded():
    fields = M._SPEC["invoices"]["fields"]
    for f in ("PaymentTerms", "ForDeposit", "IsRetainage", "PONumber"):
        assert f in fields, f"invoices spec missing expanded field {f!r}"


def test_fetch_entity_contracts_not_cents_normalized(monkeypatch):
    """Contracts money fields are dollars from MCP — must NOT be divided by 100."""
    _stub_pull(monkeypatch, [{"Id": "1", "OriginalContractSum": 15000.00,
                               "CurrentContractSum": 15000.00, "DepositAmount": 3000.00}])
    out = M.fetch_entity("contracts", "tok")
    assert out[0]["OriginalContractSum"] == 15000.00
    assert out[0]["DepositAmount"] == 3000.00


def test_fetch_entity_deliverables_not_cents_normalized(monkeypatch):
    """Deliverables money fields are dollars from MCP — must NOT be divided by 100."""
    _stub_pull(monkeypatch, [{"Id": "1", "UnitPrice": 250.00, "Price": 500.00,
                               "CostLabor": 100.00, "CostMaterials": 150.00}])
    out = M.fetch_entity("deliverables", "tok")
    assert out[0]["UnitPrice"] == 250.00
    assert out[0]["Price"] == 500.00


def test_fetch_entity_projects_uses_spec(monkeypatch):
    cap: dict = {}
    _stub_pull(monkeypatch, [{"Id": "1"}], capture=cap)
    M.fetch_entity("projects", "tok")
    assert cap["table"] == "Projects"
    assert "ProjectName" in cap["fields"]
    assert cap.get("where") is None  # no where filter on projects


def test_fetch_entity_contracts_uses_spec(monkeypatch):
    cap: dict = {}
    _stub_pull(monkeypatch, [{"Id": "1"}], capture=cap)
    M.fetch_entity("contracts", "tok")
    assert cap["table"] == "Contracts"
    assert "ContractName" in cap["fields"]


# --------------------------------------------------------------------------- #
# _post / initialize / query over mocked HTTP (the raw transport seam)
# --------------------------------------------------------------------------- #

class _FakeHTTP:
    """Stand-in for urlopen's return: .headers.get(...) + .read() (no context manager)."""

    def __init__(self, body: bytes = b"", sid: str | None = None):
        self._b = body
        self.headers = {"Mcp-Session-Id": sid} if sid else {}

    def read(self) -> bytes:
        return self._b


def test_initialize_swallows_http_error_on_notification(monkeypatch):
    """The notifications/initialized call may return 4xx — must be swallowed silently."""
    import urllib.error
    calls = []

    def _fake_post(self, payload, notify=False):
        calls.append(notify)
        if notify:
            raise urllib.error.HTTPError(None, 405, "Method Not Allowed", {}, None)

    monkeypatch.setattr(M.MCP, "_post", _fake_post)
    m = M.MCP("tok")
    m.initialize()  # must not raise
    assert calls == [False, True]  # initialize + notification


def test_post_initialize_and_query_over_mocked_http(monkeypatch):
    payload = {"Data": [{"Id": "1"}], "Total": 1}
    sse = ("data: " + json.dumps(
        {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"text": json.dumps(payload)}]}}
    )).encode()
    seen = {"auth": None, "sid_sent": []}

    def _fake_urlopen(req, timeout=0):
        seen["auth"] = req.headers.get("Authorization")
        seen["sid_sent"].append(req.headers.get("Mcp-session-id"))  # header casing normalized
        return _FakeHTTP(sse, sid="sess-1")

    monkeypatch.setattr(M.urllib.request, "urlopen", _fake_urlopen)
    m = M.MCP("tok")
    m.initialize()                       # exercises _post (notify + non-notify) + session id
    assert m.sid == "sess-1"
    assert m.query("Clients", fields=["Id"]) == payload
    assert seen["auth"] == "Bearer tok"  # bearer token sent, never logged
