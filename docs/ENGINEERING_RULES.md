# Engineering Rules — Perkins v2 Platform

Standing, non-negotiable rules for this project. Set by the owner 2026-07-04. Every wave and
every change must satisfy these. CI enforces what it can; the rest is a manual per-wave gate.

## R1 — Test coverage ≥ 97% (per wave)
- `pytest --cov=core --cov-config=.coveragerc --cov-fail-under=97` must pass for every wave.
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

## R4 — Drift check (per wave)
- Every wave must run `scripts/drift_check.sh` and show **no drift**:
  - `terraform plan -detailed-exitcode` → exit 0 (no changes) after the wave's apply.
  - `ansible-playbook <play> --check` → `changed=0`.
- A non-empty plan/`--check` diff means someone deployed out-of-band — fix by codifying it in
  git and re-applying, not by ignoring the diff.

## R5 — Ansible for what Terraform can't
- Terraform owns GCP. Ansible owns host/OS/service config (the cerberus Whisper node, GPU
  dedication, systemd units, packages). Both are committed; both are drift-checked (R4).

## Per-wave Definition of Done (checklist)
- [ ] All wave tasks implemented — no unwired/dead code (architect-verified).
- [ ] `pytest --cov=core --cov-fail-under=97` green (R1) + a behavioral validation for new I/O.
- [ ] `ruff check core adapters api jobs` clean.
- [ ] architect review: no unaddressed HIGH gaps (R2).
- [ ] critic review: no unaddressed HIGH/critical issues (R2).
- [ ] All infra/config changes in Terraform/Ansible, applied from git (R3).
- [ ] `scripts/drift_check.sh` shows no drift (R4).
- [ ] Committed on `feat/platform-v2` with a descriptive message.

## Current standing operational directives
- **cerberus 5090 is dedicated to Whisper** for the duration of this project (ollama stopped +
  disabled via `ansible/whisper.yml`, `dedicate_gpu=true`). Release with `-e dedicate_gpu=false`
  when the project ends.
