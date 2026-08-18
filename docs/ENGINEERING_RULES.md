# Engineering Rules — Perkins v2 Platform

Standing, non-negotiable rules for this project. Set by the owner 2026-07-04. Every wave and
every change must satisfy these. CI enforces what it can; the rest is a manual per-wave gate.

## R1 — Test coverage 100% on `core/` (per wave)
- `pytest --cov=core --cov-config=.coveragerc --cov-fail-under=100` must pass for every wave.
  `.coveragerc` already uses `fail_under = 100` and `precision = 2` — do not “fix” a miss by
  lowering the gate.
- **TDD:** write the failing test from the TRD/DDD first (watch it fail), then the minimum
  implementation. A feature that lands with tests written after the fact is a defect, not a
  waiver.
- The gate measures `core/` (pure logic). **Because adapters/api/jobs are coverage-omitted,
  every wave must ALSO add at least one behavioral/integration validation for new I/O code**
  (a `scripts/validate_*.py` hermetic check or a live smoke) — coverage % alone is not "done".

## R2 — Deep review by architect AND critic (per wave)
- Before a wave is "done", run a full deep review with BOTH the `architect` and `critic` agents.
- They must specifically hunt for: **gaps** (spec/plan items not implemented), **unwired/dead
  code** (written but never called), schema/migration mismatches, and common problems
  (security, resource leaks, error handling, idempotency, cost/quota).
- All HIGH/critical findings must be fixed (or explicitly deferred with owner sign-off) before
  the wave is committed as complete. Record the review verdict in the wave's memory/notes.

## R3 — 100% Infrastructure as Code, git is the source of truth
- **No direct/manual deploys.** Every piece of infrastructure and host configuration must be
  expressed in code committed to git:
  - **Cloud (GCP):** Terraform (`infra/`). Nothing created by hand in the console/gcloud that
    Terraform doesn't own.
  - **Host/OS config (cerberus, etc.):** Ansible (`ansible/`) — for anything Terraform can't do.
- Changes flow git → `terraform apply` / `ansible-playbook`, never the reverse. If reality
  diverges from git, git wins: re-converge, don't hand-patch.
- Terraform state is authoritative for cloud; keep it consistent (migrate to a remote GCS
  backend before multi-operator use — tracked as hardening).

### R3-ENFORCE — no direct deploy, ever (owner directive 2026-07-06)
- **Infrastructure changes (Cloud Scheduler jobs, Secret Manager secrets/IAM bindings, buckets,
  Cloud SQL, Cloud Run service/job *definitions*, service accounts) go ONLY through
  `terraform apply` from committed code.** NEVER `gcloud ... create/update/delete` or the console
  for anything Terraform owns — that is exactly what caused the 2026-07-06 drift (an out-of-band
  `crawl-comments` scheduler + secrets created by hand, invisible to state).
- The ONLY gcloud allowed is **read-only / operational**: `... describe|list|logging read`,
  `run jobs execute`, `scheduler jobs run|pause|resume`. These do not define infrastructure.
- **Always commit before deploy.** The app image is tagged with the git SHA, so a deploy from a
  dirty tree ships code that isn't in git. `scripts/deploy.sh` hard-refuses a dirty working tree.
- Any new infra need → add the resource to `infra/*.tf`, commit, `terraform apply`, `drift_check`.
  If you find drift, reconcile it via `terraform import` + apply (codify reality), never by hand.

## R4 — Drift check (per wave)
- Every wave must run `scripts/drift_check.sh` and show **no drift**:
  - `terraform plan -detailed-exitcode` → exit 0 (no changes) after the wave's apply.
  - `ansible-playbook <play> --check` → `changed=0`.
- A non-empty plan/`--check` diff means someone deployed out-of-band — fix by codifying it in
  git and re-applying, not by ignoring the diff.

## R5 — Ansible for what Terraform can't
- Terraform owns GCP. Ansible owns host/OS/service config (the cerberus Whisper node, GPU
  dedication, systemd units, packages). Both are committed; both are drift-checked (R4).

## R6 — Commit protocol (every commit, owner directive 2026-07-18)
- **On every commit, in the same session, before moving on:**
  1. **Docs** — update the affected docs (plan/spec/backlog/continuation, `docs/`) so git stays
     the source of truth. No feature ships with stale docs.
  2. **Drift** — run `scripts/drift_check.sh`; show no drift (R4). If the change touched infra,
     apply from git first, then re-check.
  3. **Jarvis** — update tasks/projects so the canonical task list matches reality. Jarvis is
     canonical; never leave a parallel list in markdown. **ENFORCED BY HOOK since 2026-08-02** —
     `.githooks/commit-msg` refuses a commit that references no task, and refuses a `Closes`
     without evidence. Every commit carries one of:

         Closes #453                 finished it — REQUIRES a `Verified:` line
         Refs #429 60%               progress, never closes
         No-Task: <reason>           deliberately not task work

     `.githooks/post-commit` then applies it to Jarvis in real time, running `ruff` on the changed
     Python first and leaving the task **open at 90%** instead of closing it when that fails.
     Enable in a fresh clone with `git config core.hooksPath .githooks`.

     ⚠️ **What the hook does NOT do, so nobody reads a green check as more than it is:** it cannot
     evaluate a task's acceptance criteria — those are prose ("95% out-of-sample with rule
     selection nested inside the CV") and no parser settles them. It cannot run the coverage gate
     either; R7 forbids it and an hour-long commit hook gets bypassed within a day. **CI is still
     the verdict.** The hook makes the claim explicit and the evidence mandatory.

     Why it exists: R6.3 was written 2026-07-18 and skipped six times — #430, #449, #418,
     #385/#386, #409/#410 — the last two fixed by ONE commit whose subject names both task numbers
     and closed neither. An unenforced rule is a suggestion.
  4. **Memory** — record durable, non-obvious facts in project memory (`memory/` + `MEMORY.md`
     index): decisions, blockers, gotchas, credential/data gates. Not code structure or git
     history (those live in the repo).
- This is a gate, not a suggestion: a commit without docs+drift+jarvis+memory is incomplete.

## R7 — Never edit the tree while a long gate is running (owner directive 2026-07-30)

The coverage gate is 40–60 min on a dev box. Editing `core/` or `tests/` while it runs
invalidates it: pytest imported the modules at collection, but coverage maps line numbers from
the file **on disk at report time**, so the result describes code that no longer exists. On
2026-07-30 this burned three consecutive full runs — roughly two hours — for one usable number.

- Finish **all** edits, then run the expensive gate **once**, then do not touch the tree until
  it returns. Batch fixes; do not trickle them in.
- For a small follow-up fix after a green full run, re-run only the affected test files. The
  full sweep runs in CI anyway — a second local full sweep buys nothing.
- Never `pkill -f "<pattern>"` to stop a run: the pattern matches the killing shell itself.
  Capture the PID and `kill "$PID"` (this is written down because it has been hit twice).
- Do not wrap a long run in `... | tail -n`: the pipeline's exit code is `tail`'s, so a failing
  suite reports success. Redirect to a file, echo `$?`, then read the file.

## R8 — Verify before asserting, especially when it sounds like a discovery

Every wrong claim in the 2026-07-30 session came from asserting before checking, and each took
exactly one command to disprove: "the CDN URL expired" (the URL had been copied from console
output truncated at 70 chars), "8 files use drop_all" (5), "extra_line_items has no test"
(`tests/core/test_estimator.py:86`). None were invented — all were stated one command too early.

- A count, a filename, a URL or an "X is broken" claim gets the command **before** the sentence.
- Console output is truncated by default. Never copy an identifier out of a printed table —
  re-read it from the source.
- An image tag is not proof a deploy is serving: check behaviour. `spec.template` is desired
  state, and traffic can still be on the old revision mid-roll.
- State the measurement, not the impression: "17 of 26,063 lines" beats "a few lines".

## R9 — Delegation is best-effort; the work is not

Review subagents can return idle with no output. That is a tool failure, not a reason to stop.

- One retry, then do the review inline yourself and **label it as self-review** in the report.
- Never let a failed delegation silently downgrade R2: say plainly whether an independent
  architect/critic pass happened or did not.
- Do not spawn a second wave of agents to chase a first wave that produced nothing.

## R10 — Heuristics touching published text are corpus-validated, and refusing beats guessing

Extends the `core/pii.py` lesson (a detector whose unit tests were green at a 98% false-positive
rate on real data).

- Run any new pattern over the **whole** corpus (`knowify_raw_records` deliverables = 26,063
  lines) and read a sample of what it changes, before it ships. Unit tests cannot see this class
  of error.
- On an ambiguous input, DROP the line rather than transform it. The 2026-07-30 building-number
  rule first rewrote "2022 -2026 Annual Maintenance" into "2026 Annual Maintenance" — a
  confident, wrong label. Losing a scope line costs detail; a mangled or leaked one costs trust.
- Report both directions: what the rule changed AND what it deliberately left alone.

## R11 — Implemented features must not leave the docs behind (owner 2026-08-18)

Code is the source of truth. Docs that still describe the old world are a defect.

- Every feature that exists in code has, in the **same change** (or the change that marks it
  done): `docs/specs/<feature>.md`, `docs/plans/<feature>.md` if it was phased, and
  `docs/requirements/<feature>-{trd,prd,ddd,uiux}.md`.
- **Drift check is part of the implementation, not a follow-up.** If you change behavior, the
  TRD/PRD/DDD/UIUX that still describe the previous behavior must be updated in that commit.
  A green test suite with stale requirements is not done.
- Status in those files is literal: `done` only when shipped and verified; `implemented-local`
  when the tree has it but prod does not; `blocked` names the blocker.
- New work is TDD against the TRD/DDD (R1). Do not invent a second requirements pile in
  chat, Jarvis notes, or continuation markdown.

## Per-wave Definition of Done (checklist)
- [ ] All wave tasks implemented — no unwired/dead code (architect-verified).
- [ ] `pytest --cov=core --cov-fail-under=100` green (R1) + a behavioral validation for new I/O.
- [ ] Spec/TRD/PRD/DDD/UIUX match the code (R11); no leftover “old world” requirements.
- [ ] `ruff check core adapters api jobs` clean.
- [ ] architect review: no unaddressed HIGH gaps (R2).
- [ ] critic review: no unaddressed HIGH/critical issues (R2) — or an explicit
      statement that delegation failed and the review was done inline (R9).
- [ ] Expensive gates run ONCE on a settled tree (R7); any new published-text
      heuristic corpus-validated (R10).
- [ ] All infra/config changes in Terraform/Ansible, applied from git (R3).
- [ ] `scripts/drift_check.sh` shows no drift (R4).
- [ ] Committed on `feat/platform-v2` with a descriptive message.

## Current standing operational directives
- **cerberus is dev-only for STT** (prod STT moved to GCP/Vertex on 2026-07-06). The
  `whisper-perkins` service is stopped + disabled; the GPU is released back to ollama
  (`ansible/whisper.yml`, `dedicate_gpu=false`). For local dev/testing, start Whisper
  on-demand: `systemctl start whisper-perkins` — do NOT flip `dedicate_gpu` back to true
  unless re-dedicating for a specific workload (requires an Ansible apply + `drift_check`).
