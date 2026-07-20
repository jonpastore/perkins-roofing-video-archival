# CONTINUATION — 2026-07-20 (pm-2)

All three resume tasks are **built + verified**. Commit `e8564d8` on `main`
(not yet deployed — see "Deploy decision" below).

## What shipped (commit e8564d8)

### Task 1 — Quoting config panel (was an empty placeholder)
- New `web/src/pages/QuotingConfig.tsx`, mounted at AdminConfig → Quoting.
- Sections: **deposit policy** (percent/fixed), **follow-up reminder cadence**
  (day-offset chips), **contractor license**, **proposal-template CRUD**
  (create/edit HTML/branding/set-default/delete), and the **T&C library**
  (embeds the existing `ContractFaq` component — zero duplication).
- Backed by the already-present `/quoting/settings` + `/quoting/templates`
  endpoints. api.ts got `QuotingSettings`/`ProposalTemplate` types + client fns.
- `_template_row` now returns `html_body`/`cover_page_html`/`tc_attachment_gcs`
  so templates are actually editable (it previously omitted the body).

### Task 2 — pre-send review wired into proposal generation
- **Big finding: most of Task 2 was already done by the prior session.**
  `_load_tc_context` (T&C text + summary bullets + FAQ + AI-prompt pages) is
  already set onto the render context in `render_and_cache_proposal_pdf`
  (proposals.py:~1399), and `ContractFaq.tsx` is a full T&C/FAQ/AI-prompt
  management tab. The only gap was the fairness/security review.
- `core/proposal_review.review_proposal` is now called in `send_proposal`:
  HIGH-severity findings (contradiction/unfair/predatory/security/legal)
  **block the send with 422 + the issues**, unless `SendRequest.override_review
  = true`. The fail-safe `review_error` marker (LLM down) is **logged + surfaced
  as `review_warning`, never hard-blocks** — a flaky LLM must not wedge sending.
- New helper `_assemble_review_text` flattens scope + deposit + customer notes +
  T&C + FAQ into the audited text (customer notes are the injection surface).

### Task 3 — AV end-to-end validation on a REAL MP4 (evidence, not shipped code)
- Driver: `scratchpad/av_e2e.py` drove `core.censor / reframe / captions /
  transcode` through **real ffmpeg** on `poc/data/ls9zLWRiDHg.mp4` (640×360).
- **10/10 checks pass.** Auto-censor muted the flagged span to **−91 dB** (vs
  −17.8 dB original) while preserving audio outside it; reframe → **202×360
  (9:16)**; caption mask **"▇▇▇▇▇▇▇" burned in, "badword" absent from the ASS**;
  transcode conform decision correct + valid **h264/aac** output.
- **Tuning: defaults measured correct** — `tail_pad=0.4`, next-word-start end
  heuristic, default caption style, centre reframe all produced clean output.
  No knob change warranted. (These engines had unit tests but had never been
  driven end-to-end on a real MP4 until now.)

## Tests
- `tests/test_proposal_review.py` (5) green.
- `tests/api/test_f3_proposals.py`: 3 new `TestSendReview` cases (block /
  override / warn-but-send) + an autouse `_stub_review_llm` fixture so existing
  send tests don't hit a live model. `-k "SendReview or send"` = 12 passed.
  (The full f3 suite has pre-existing slow accept/gotenberg/network tests that
  time out in this sandbox — unrelated to this change, which only touches send.)
- SPA `tsc --noEmit` + `vite build` both clean.

## Deploy decision (PENDING — needs a human go)
Not deployed. The send-gate adds a **synchronous LLM review call to the live
send path** (Vertex in prod) and can **block a send** — a real behavior change
to a client-facing flow. Deploy when ready:
- API+jobs: `bash scripts/deploy.sh` (CLEAN tree, SHA-tagged).
- SPA: `cd web && npm run build && npx --no-install firebase deploy --only
  hosting:app --project video-archival-and-content-gen`.
- No infra changed → terraform/ansible drift unaffected (R4).

## Still dark / open (unchanged)
Real T&C **wording still pending Tim** (plumbing flows it through when it lands).
B9 QB account_id collision (#358) · tenant-2 (#359) · CompanyCam reader (#360) ·
FB/LinkedIn/X/YT publishers · infra B6 (#363) · Meta/TikTok app review (#319) ·
GCP alert channel email still needs a click by dmarc@perkinsroofing.net.

## Operate
- `export GOOGLE_APPLICATION_CREDENTIALS=/home/jon/.config/gcloud/perkins-deploy-sa.json`.
- Drift: `bash scripts/drift_check.sh`. Prod smoke: `.venv/bin/python scripts/prod_smoke.py`.
- Offload SYNC: `llm -m qwen3.6-coder "…"` · ASYNC: `mcp__hermes__submit_task(model_tier="cloudflare", …)`.

Memories: `session-2026-07-20-pm2-quoting-review-av`, `clip-render-capability-audit-2026-07-20`.

---
*Standing archive directive performed: moved CONTINUATION-2026-07-19.md into
docs/continuations/; top level keeps the latest 3 (20, 20-pm, 20-pm2).*
