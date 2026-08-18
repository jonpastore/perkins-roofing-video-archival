# AGENTS.md - Morpheus-governed project

This project follows the Morpheus engineering constitution (ADR-0004). Use the
`morpheus-ek` CLI (global) and the `morpheus-graph` MCP tools while working here.

## Workflow (spec-driven)
1. Spec: `docs/specs/<feature>.md` (why/what, users, constraints, non-goals)
2. Plan: `docs/plans/<feature>.md` (phased how/when)
3. Requirements: `docs/requirements/<feature>-{trd,prd,ddd,uiux}.md`
4. TDD: write tests from the TRD/DDD **before** implementation; watch them fail; then code
5. After any behavior change, re-read those four requirement files and fix drift in the same commit
6. `core/` coverage gate is 100% (`.coveragerc` `fail_under = 100`)

## Rules
- Cyclomatic complexity <= 10 (documented waivers only)
- No parallel/duplicate systems; one canonical implementation
- Infrastructure as Code where possible; reproducible + rollbackable
- Dry-run by default; never destructive; always a rollback path
- Secure defaults: least privilege, no secrets in code, gated egress
- Provenance: ADRs for decisions; record sources

## Tooling
```bash
morpheus-ek graph build --target .            # build the repo knowledge graph
morpheus-ek graph review-context --changed-files <files...>
morpheus-ek analyze budget --target .         # prioritized findings
morpheus-ek policy check --target .           # constitution checks (if policy packs apply)
morpheus-ek model codex-usage                 # token/context usage for this codex session
```
The `morpheus-graph` MCP server (see .mcp.json) exposes get_node / search_nodes /
impact_of / review_context / affected_tests to the assistant.
