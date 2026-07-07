# Comprehensive Multi-Role Review — 2026-07-07 (round 2)

A second, wider pass bringing in the roles the first review didn't apply to v2: **frontend +
a11y** (the `web/` SPA had never been reviewed), **QA test-quality**, **adversarial
re-verification of the round-1 fixes**, **performance/reliability/DevEx**, and **SAST/SCA**.
Five parallel auditors; findings triaged and fixed. Records the R2 verdict.

## Headline: a round-1 "fix" had regressed

The adversarial verifier caught that the round-1 `embed_job` skip-if-unchanged fix **silently
no-op'd the nomic→gemini re-embed** under its documented invocation, because `EMBED_MODEL` had a
split-brain default (`app/config.py` = `nomic-embed-text` vs `adapters/llm.get_embedder` =
`gemini-embedding-001`). Fixed at the source (backend-aware default) + regression tests.

## Baseline → after

`ruff` (CI scope) clean · `pytest` 1122→**1132 passed** · `core` cov **97.49%** · web build ✅ ·
bandit **0 HIGH** (19 Medium = dual-use urlopen/2 SQL false-positives) · pip-audit **0 CVEs**.

## Fixed

| Severity | Area | Finding | Fix |
|---|---|---|---|
| CRITICAL | reliability | `_LLM_CAP` counts a never-reset process-global `Cost` on the long-lived API → after 20k LLM calls every request 500s | `Cost.reset()` + lock; API resets per-request via middleware (jobs are fresh processes, per-run cap preserved) |
| HIGH | correctness | `embed_job` skip regressed → migration silently no-ops (split-brain `EMBED_MODEL`) | Backend-aware `EMBED_MODEL` default in `config.py`; tests prove nomic→gemini re-embeds |
| HIGH | reliability | Session/connection leaks on the hot search path (`app/store.py`, `app/retrieval.py`) — every `/ask` | `try/finally: s.close()` in both |
| MEDIUM | security | `ffmpeg make_card` — round-1 escaping actually *broke* apostrophes (`\'` ends an ffmpeg quote early) | Canonical `'\''` sequence + `expansion=none`; tests for apostrophe + injection |
| MEDIUM | maintainability | `datetime.utcnow()` deprecated (naive-UTC inconsistency, 43 suite warnings) | `_utcnow()` helper in `models.py` (warnings 43→20) |
| MEDIUM | perf | Lexical `ILIKE '%q%'` legs + `content_graph.kind` do full-table scans on every search | `0011_search_indexes.sql`: pg_trgm GIN on text/label/detail + `kind` btree |
| MEDIUM | DevEx | CI had no SAST/SCA | Added `bandit -lll` + `pip-audit` gates to `ci.yml` |
| — | test debt | round-1 I/O fixes had NO regression tests (coverage illusion) | Added tests: ffmpeg escaping, social timeouts, embed_job skip/isolation, firebase `verify_token` mapping; conftest autouse verifier reset |
| — | deps | Unpinned floors far behind latest | Bumped `app/requirements.txt` floors to current latest (fastapi 0.139, numpy 2.5, firebase-admin 7.5, google-cloud-* current…); resolve clean, tests green, 0 CVEs; frontend `npm update` (oxlint) — build green |

## Verified-correct (round-1 fixes that held up)

email_verified admin-elevation gate (all three layers, no bypass), promote_job per-row commit,
jsonld defensive FAQ + article_job subscripts guarded, social timeouts on every call, migrations
init_db-first + halfvec≥0.7 assert + focus_keyword, main.tf internal-secret self-consistent,
chunking guard, backfill per-batch isolation, enumerate try/finally.

## Deferred to backlog (see BACKLOG.md §B6/§B7)

Frontend: bundle code-splitting/lazy + TinyMCE defer (1.7MB bundle), global 401/error-boundary,
Scheduling naive `publish_at` tz bug, Faq "load more" error guard, broken nav links, modal a11y
(focus trap/Esc/dialog roles), form label association, unpaginated Archive/Articles lists.
Backend: `embed()` has no cost cap; retry/backoff inconsistent across HTTP adapters; overlapping-
cron double-publish risk (`with_for_update(skip_locked)`); `suggestions` O(videos×articles) scan;
12/20 jobs + 8/16 adapters still lack an R1 behavioral test; dependency lockfile for reproducible
builds. Infra items from round 1 remain (idp secret, allUsers-in-TF, drift vars, PITR, alerts).
