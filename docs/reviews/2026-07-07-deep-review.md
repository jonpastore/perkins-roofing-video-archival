# Deep Review — 2026-07-07 (architect + critic, per R2)

Full-surface review of the v2 platform (`core/`, `api/`, `adapters/`, `jobs/`, `infra/`) run as
five parallel auditors, then triaged and fixed. Records the R2 verdict per ENGINEERING_RULES.

## Baseline at review time

| Gate | Result |
|---|---|
| `pytest tests/` | 1114 passed |
| `--cov=core --cov-fail-under=97` | 97.47% ✅ |
| `web` build (`tsc + vite`) | ✅ |
| `ruff check core adapters api jobs` | ❌ 26 errors (CI lint gate red) |

After fixes: **1122 passed, coverage 97.49%, ruff clean, web build green.**

## Fixed (HIGH/critical + high-value medium)

| # | Severity | Area | Finding | Fix |
|---|---|---|---|---|
| 1 | HIGH | lint gate | `ruff` red incl. `F821 np` in aggregate_topics (verified NOT a runtime bug — lazy annotation + local import) | Hoisted `import numpy`; autofixed I001/F401/F811; per-file E501 ignore for two prompt-string modules |
| 2 | HIGH | security (auth) | `effective_role` elevated any `DEFAULT_ADMINS` email to admin without checking `email_verified`; `verify_token` dropped that claim → config-dependent admin escalation on the public service | `verify_token` now returns `email_verified`; `effective_role` requires it for email-based elevation; explicit role claims still honored. Tests added |
| 3 | HIGH | reliability | Instagram + TikTok adapters made HTTP calls with **no timeout** → the social cron could hang forever | Added `timeout=30` to every `meta_ig`/`tiktok` request |
| 4 | HIGH | correctness | `promote_job` mid-loop `s.rollback()` reverted rows already promoted in the same run (state loss + inflated count + re-publish) | Commit per-row; rollback only unwinds the failing row. Regression tests added |
| 5 | HIGH | schema | Base tables exist only in `create_all()`; ALTER-only migrations fail on a fresh DB | `apply_migrations.sh` runs `init_db()` before applying SQL |
| 6 | HIGH | schema | `Article.focus_keyword` in ORM + consumers but no migration creates it | Added `0010_article_focus_keyword.sql` |
| 7 | HIGH | schema | `halfvec(3072)` (0001 + every vector query) needs pgvector ≥ 0.7.0, unverified | `db_bootstrap.py` runs `ALTER EXTENSION vector UPDATE` + asserts ≥ 0.7.0 |
| 8 | CRIT | infra | `internal-secret` read by 3 schedulers via a `data` source but never created by Terraform → `plan` NOT_FOUND + unreconciled 2026-07-06 drift | Created `random_password`/secret/version in IaC; repointed refs |
| 9 | MED | cost | `embed_job` re-embedded the whole corpus every run/retry | Skip-if-unchanged on `(embed_model, version)`; `--force` flag; `try/finally` session |
| 10 | MED | security | `ffmpeg make_card` escaped only `'`/`:` — external video titles could inject filtergraph metacharacters | Escape `\ ' : % [ ] , ;` (backslash first) |
| 11 | MED | correctness | `core.jsonld.build_faq_page` hard-subscripted `item["q"]` → a malformed LLM FAQ item KeyErrored and discarded the whole article | Defensive `q/question`, `a/answer`, skip empty. Tests added |
| 12 | LOW | reliability | `backfill_metadata` no per-batch error isolation + leaked the HTTP response | Per-batch try/except + `with urlopen(...)` |
| 13 | LOW | reliability | Session leaks in `embed_job` / `enumerate_channel` on the error path | `try/finally: s.close()` |
| 14 | LOW | correctness | `chunk_segments` crashed on `CHUNK_SIZE=0` (operator-editable) | `max(1, int(chunk_size))`. Test added |
| 15 | MED | infra | Cloud Build context had no `.dockerignore` (secrets/`dev.db` shipped to the build) | Added `.dockerignore` |

## Deferred to backlog (unverifiable here / owner-owned infra)

`infra/main.tf` is being actively iterated and cannot be `terraform validate`d in this
environment, so the remaining infra findings are logged in [BACKLOG.md](../BACKLOG.md) rather
than hand-edited blind:

- `google-idp-client-secret` version seeding + `depends_on` (fresh-apply blocker).
- Public `allUsers`→`run.invoker` applied by `deploy.sh --allow-unauthenticated` instead of
  Terraform (R3 gap).
- `drift_check.sh` misses `billing_account` var and only checks `whisper.yml` (R4 can't pass).
- `jobs-sa` has project-wide `storage.objectAdmin` (scope to the two buckets).
- No monitoring notification channel / log-based alert; billing budget has no `all_updates_rule`.
- Cloud SQL: no PITR / single-zone; docs claim "private IP only" but it's public+SSL.
- `aggregate_topics` job is unwired (nothing schedules it) though its table is consumed.
- `article` Cloud Run Job is deployed but its `__main__` needs args it isn't given (dead).
- R1 behavioral validations missing for `crawl_comments`, `aggregate_topics`, `embed_job`, etc.
- `EMBED_MODEL` split-brain default (config `nomic-embed-text` vs adapter `gemini-embedding-001`).
- `ABSTAIN_THRESHOLD=0.71` calibrated on Ollama embeddings — recalibrate for Vertex before go-live.

## Verified-correct (no action)

Auth gating complete on every mutating route; `/internal/*` fails closed via `hmac.compare_digest`;
no SQL injection (ORM bound params throughout); subprocess calls are arg-lists (no shell) with
timeouts; HTML sanitized via bleach; secrets never returned/logged; `social_posts` /
`comment_drafts` / `faq_entries` upsert-idempotency matches their unique constraints; pgvector
dim (3072) consistent across model/migration/query/embedder; the pgvector migration DDL ordering
and `1 - (embedding <=> …)` similarity are correct.
