# Perkins v2 Platform — project rules for agents

Read `docs/ENGINEERING_RULES.md` — it is binding for every change in this repo. Summary:

- **R1** Test coverage ≥ 97% on `core/` per wave, PLUS a behavioral validation for new I/O
  (adapters/api/jobs are coverage-omitted — a green % is not "done" on its own).
- **R2** Every wave gets a deep review by BOTH the `architect` and `critic` agents (gaps,
  unwired/dead code, schema/migration mismatches, security, idempotency, cost). Fix all
  HIGH/critical findings before marking the wave done.
- **R3** 100% Infrastructure as Code, git is the source of truth. GCP → Terraform (`infra/`);
  host/OS/service config → Ansible (`ansible/`). **No manual/direct deploys.** git → apply,
  never the reverse.
- **R4** Every wave runs `scripts/drift_check.sh` and shows no drift (terraform plan clean +
  ansible `--check` changed=0).
- **R5** Ansible handles what Terraform can't (cerberus Whisper node, GPU dedication, systemd).

Operational: the cerberus RTX 5090 is dedicated to Whisper for this project (ollama disabled
via `ansible/whisper.yml`). Waves + architecture live in `docs/superpowers/{specs,plans}/`.
Backlog to scope: `docs/BACKLOG.md`.
