"""Knowify endpoint constants — single source, importable INSIDE the jobs container.

`scripts/` is .dockerignore'd (only core/adapters/api/jobs/app ship in the image),
so `core.knowify.tokens` and `jobs.knowify_sync` must NOT import Knowify URLs from
`scripts.knowify.knowify_pull` — that ImportErrors at container startup. These live
here instead; the interactive scripts import them back from here.
"""
from __future__ import annotations

# REST API base (assistant.knowify.com/api/v2) — the /oauth resource that 500s (Wave-0).
API = "https://assistant.knowify.com/api/v2"
# OAuth token endpoint — SAME server issues both REST and MCP tokens (RFC 8707 resource
# is the only difference: API above for REST, MCP_URL below for the MCP audience).
TOKEN_URL = "https://developers-v2.knowify.com/oauth/token"
# Streamable-HTTP MCP endpoint — the resource the Claude Code connector's token binds to.
MCP_URL = "https://assistant.knowify.com/api/v2/mcp"
UA = "perkins-knowify-importer/1.0"
