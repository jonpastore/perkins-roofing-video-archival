"""Live Knowify MCP connectivity smoke test — OPT-IN, REAL network.

This is the one test that actually talks to Knowify. It is SKIPPED by default so
the normal suite (and CI) stays hermetic; enable it explicitly:

    KNOWIFY_MCP_LIVE=1 pytest tests/test_knowify_mcp_live.py -q

Token source (first that resolves):
  1. env  KNOWIFY_MCP_TOKEN_JSON  = the raw JSON blob, or
  2. file KNOWIFY_MCP_TOKEN_FILE  (default: <repo>/.env.knowify-mcp), which holds a
     KNOWIFY_MCP_TOKEN_JSON=<json> line — the gitignored stash mirroring Claude Code's
     Knowify connector creds (accessToken/refreshToken/clientId/expiresAt).

Discipline:
  - NEVER refreshes the token. Knowify refresh tokens are single-use and shared with the
    local Claude connector, so a refresh here could break that connector. If the access
    token is expired/absent the test SKIPS (operational reconnect needed) — it does not
    fail red and it does not rotate anything.
  - NEVER logs a token value or any customer PII — asserts only on the numeric `Total`
    and record shape (key presence), never on record contents.
"""
from __future__ import annotations

import json
import os
import time

import pytest

_LIVE = os.getenv("KNOWIFY_MCP_LIVE") == "1"
pytestmark = pytest.mark.skipif(
    not _LIVE, reason="live Knowify MCP smoke — set KNOWIFY_MCP_LIVE=1 to enable"
)

_ACCESS_SKEW_MS = 60_000  # treat as expired within 60s of expiry to avoid a mid-run 401


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_token() -> dict:
    """Resolve the MCP token blob from env or the gitignored stash file.

    pytest.skip (not fail) when the blob is absent — the smoke test is only meaningful
    when a human has stashed a live connector token.
    """
    raw = os.getenv("KNOWIFY_MCP_TOKEN_JSON")
    if not raw:
        path = os.getenv("KNOWIFY_MCP_TOKEN_FILE") or os.path.join(_repo_root(), ".env.knowify-mcp")
        if not os.path.exists(path):
            pytest.skip(f"no MCP token: set KNOWIFY_MCP_TOKEN_JSON or provide {path}")
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("KNOWIFY_MCP_TOKEN_JSON="):
                    raw = line.split("=", 1)[1]
                    break
    if not raw:
        pytest.skip("no KNOWIFY_MCP_TOKEN_JSON in env or stash file")
    try:
        tok = json.loads(raw)
    except json.JSONDecodeError:  # pragma: no cover - malformed stash
        pytest.skip("KNOWIFY_MCP_TOKEN_JSON is not valid JSON")
    if not tok.get("accessToken"):
        pytest.skip("MCP token blob has no accessToken")
    exp = tok.get("expiresAt")
    if exp and time.time() * 1000 + _ACCESS_SKEW_MS >= exp:
        pytest.skip("MCP access token expired — reconnect Knowify in Claude and re-stash")
    return tok


@pytest.fixture(scope="module")
def live_mcp():
    from core.knowify.mcp_client import MCP

    tok = _load_token()
    m = MCP(tok["accessToken"])
    m.initialize()
    return m


def test_live_session_initializes(live_mcp):
    # A session id is returned by the streamable-HTTP endpoint on initialize.
    assert live_mcp.sid


@pytest.mark.parametrize("table", ["Clients", "Invoices", "ServiceCatalogItems"])
def test_live_query_returns_total(live_mcp, table):
    data = live_mcp.query(table, fields=["Id"], limit=1)
    total = data.get("Total")
    assert isinstance(total, int) and total >= 0, f"{table} Total not a count: {total!r}"
    rows = data.get("Data") or data.get("data") or []
    # Shape only — never assert on (or log) record contents (PII / pricing).
    assert rows == [] or "Id" in rows[0]
