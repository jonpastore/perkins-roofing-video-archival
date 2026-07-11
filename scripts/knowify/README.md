# Knowify integration (read-only) — CLI OAuth + bulk importer

Pulls Perkins' Knowify data (invoices, clients, projects, payments, milestones,
items, contracts, etc.) for the Knowify-replacement migration (task #15) and to
validate our invoicing/milestone/numbering model against reality.

## Endpoints (discovered 2026-07-10)
- **Read-only MCP** (2 conversational tools — Platform Knowledge, Query Knowify):
  `https://assistant.knowify.com/api/v2/mcp` — registered in Claude Code (`claude mcp list`).
  Authenticate interactively with `/mcp` (browser OAuth). Good for exploration.
- **REST API v2** (full granular read/write scopes — the real bulk source):
  base `https://api.knowify.com/v2/<entity>`.
- **OAuth AS**: `https://developers-v2.knowify.com` — supports Dynamic Client
  Registration (`/oauth/reg`), so no pre-provisioned app is needed.

## Usage (no passwords stored — OAuth only)
```bash
python scripts/knowify/knowify_oauth.py     # log in once (opens browser → Knowify login)
python scripts/knowify/knowify_pull.py      # pull all entities → $KNOWIFY_OUT (default /tmp/knowify_data)
python scripts/knowify/knowify_pull.py invoices clients   # subset
```
Tokens live in `~/.config/knowify/tokens.json` (chmod 600, **outside the repo** — never committed).
Scopes requested are **`:read` only** — this tooling never writes to Knowify.

## Notes
- `knowify_pull.py` auto-detects the response/pagination shape on first run; if
  Knowify's paging differs from the common `page`/`limit`/`cursor` patterns,
  the first pull reveals it in `_summary.json` and it's a one-line tweak.
- For write-back / QuickBooks sync later, the same OAuth app can request `:write`
  scopes — kept out of the read-only importer deliberately.
