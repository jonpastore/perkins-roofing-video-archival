# CONTINUATION — 2026-07-21

Very large session. Estimator finished + hardened, clips fixed, and the article/SEO
pipeline rebuilt for local generation with real grounding. **HEAD `4227442`, main == origin,
tree clean.**

## Prod state
- **Deployed API image: `41472dc`** (Quoting config panel, pre-send review gate, estimator
  tile roof-cuts + guards, article-gen code — all live). Commits AFTER 41472dc (`fa6d863`
  model switch, `0f47540` schema scope, `e40bff8` numeric gate, `4227442` mil) are
  **article-generation code that is OPT-IN**: prod `LLM_BACKEND` stays `vertex`, so they are
  behavior-neutral in prod until someone sets `LLM_BACKEND=litellm`. **No deploy needed** for
  them; deploy only when you actually want to flip generation to local.
- **Prod pricing config (non-destructive version bumps):** low-slope reconciled to **v5**,
  tile-brands to **v6** (miami/jupiter/naples). `scripts/reconcile_low_slope_pricing.py` +
  `scripts/reconcile_tile_brands.py`.
- SPA deployed (Quoting panel, honest Clip Studio help, review-block UI, estimating sliders +
  measurement prefill). Alerting active (dmarc@perkinsroofing.net).

## What shipped, by area

### Estimator / Quoting
- **Quoting config panel** (`e8564d8`): deposit / reminder cadence / license + proposal-template
  CRUD + embedded T&C library (reuses ContractFaq).
- **Pre-send fairness/security review** wired into `send_proposal` (`e8564d8`): HIGH issues block
  the send (422) unless `override_review`; `review_error` warns, never wedges. Review-issue UI +
  one-click override (`b87deb6`). **LIVE — it adds a synchronous Vertex call to the send path.**
- **Margin % + commission % sliders** + **measurement auto-load/prefill** (`adda2b9`, `44db347`).
  Commission %-of-profit / %-of-job toggle already existed (confirmed in 07-20 frames).
- **Low-slope pricing** resolved from **Exhibit B §4** (`legal/06-exhibit-B-pricing-engine-rules.pdf`)
  and reconciled to prod. IMPORTANT: `wood_deck_oh_adder=50` and `FBC polyglass_sav_sap=450` are
  **Tim's LIVE-SHEET values and OUTRANK Exhibit B's 45/475** — Jon's rule: the home-office/Jupiter
  live sheet is the most current pricing. (`dc5f701`, `5685ae3`, `9e8c204`, `7a61f74`)
- **Tile roof-cuts** decoded from Tim's "Custom Tile Calc" FORMULAS (`fc5bd8c`,
  `docs/estimating/tile-roof-cuts-pricing-linkage.md`) + brand rake units wired w/ null-field
  guard (`6bc0419`, prod v6). Per-brand rake $/LF: Eagle 4.82, West Lake 4.50, Crown 4.30 (default),
  Verea "S" 5.78, Verea Caribbean 19.14, Other 45. Verea/Other `field`=null (Tim owes field cost).

### Clips / AV
- **Speaker tracking FIXED** (`1b81ca6`): YuNet detection works, but the tracking crop filter's
  `if(lte(t,..),..)` commas broke ffmpeg's -vf parser, so reframe threw and clips silently stayed
  LANDSCAPE. Escape the commas → fixed. speech_cleanup (`af4547a`) + broll (`b4b8b57`) also fixed.
- **Clip Studio help** made location-aware + honest (`2eb6194`, `1b81ca6`) — all 14 features were
  built, help just didn't say where they were.

### Articles / SEO (the big rebuild)
- **07-20 Zoom** transcribed LOCALLY (faster-whisper large-v3 on the RTX 2060, free) + 422 frames;
  change list extracted by local gpt-oss (free) → `docs/meetings/2026-07-20-*.md`. Most asks
  already shipped; new items → Jarvis #385-389.
- **Pipeline hardened for local, grounded generation:**
  - Local `gpt-oss-120b` **non-think** generator (opt-in via `LLM_BACKEND=litellm` +
    `LITELLM_API_KEY`) with **Vertex pinned as the validator** (`a8f8394`, `fa6d863`).
  - **Per-post schema scoped to FAQ + Video ONLY** (`0f47540`) — Rank Math owns Org/Article/
    Breadcrumb/Person on the live site; emitting them again was the duplication Wendy flagged.
  - **Internal links** (cluster→pillar + →services pages), **no `/blog/`** in post URLs (`e40bff8`);
    **YouTube "Subscribe" footer** on every article; **dense answer-first** length (cluster 1000 /
    pillar 1500).
  - **Numeric-grounding gate** (`core/numeric_grounding.py`, `e40bff8` + `4227442`): every
    unit-anchored figure (mph/$/%/gauge/mil/inch/ft/lb/degrees/dates/dims) must trace to source, or
    it is repaired (2 LLM rounds) then the sentence is deleted. **BLOCKS, not report-only.** Bias:
    cut over publish a wrong number. metal-first topic priority.
- **Proof** (`docs/samples/`): 2 metal-roofing clusters generated locally — good, dense, expert
  content. The numeric gate correctly flagged the proof's OWN ungrounded prices + snap-lock
  comparison rating, i.e. it works.

## Plan + tracking
`docs/perkins-buildout-plan-2026-07-21.md`. Jarvis project **perkins-buildout-2026-07** (#2015),
tasks **#374-389** (every task prefixed "use local/free models first"). Memories:
`buildout-plan-2026-07-21`, `execution-routing-sonnet-not-opus`, `outbound-email-gate-testing`.

## OPEN — needs Tim (draft email sits in jpastore79@gmail.com, move to degenito to send)
1. **Per-branch daily overhead** (time-based; Miami > Jupiter > Naples $0) — the one real pricing dep.
2. **Gutter hangers** — baked into the $16.80 7" price or separate?
3. **Downspouts** — separate LF input ($10.50 4x5?) per 07-17 Zoom; our model bundles them.
4. **Verea "S" + Verea Caribbean field-tile $/sq** (rake known, field null).
5. **FBC low-slope deltas** beyond polyglass ($450 vs $475).
6. **T&C** — confirm the 49-clause version in GCS (`gs://…-media/tenants/1/contracts/josh_proposal_terms_2026-07-11.pdf`) is current.

## OPEN — Wendy / SEO vendor (reply DRAFTED in chat, ready to send — no emdashes, peer tone)
- Concede: our pipeline emitted a full schema graph that duplicated Rank Math; now scoped to
  FAQ+Video (fixed). Stale `jhk.14f` URLs were demo base-URL vars; Org/Author @ids already canonical.
- Hold: several "false negatives" are real (missing VideoObject, missing internal links she herself
  asks for, staging breadcrumbs). AIO checks (MCP/OAuth/A2A) are intentional, not noise.
- Condition: **bring staging into parity with prod** (they changed prod 7/16, not staging).
- Build to her import spec: Avada Portfolio, categories Commercial/Residential/Construction,
  tags=locations, skills=roof-types, TOC→H2-only, featured-image-from-content, no /blog/, FAQ+Video
  schema only. **Rank Math owns sitemap/robots/schema** → our submission layer only needs the
  IndexNow + Google-Indexing-API ping on publish.

## Infra / tooling gotchas
- **Local whisper**: `faster-whisper` large-v3 on the RTX 2060 needs
  `LD_LIBRARY_PATH=.venv/…/nvidia/{cublas,cudnn}/lib` or it crashes at encode (`libcublas.so.12`).
  Transcribe script: `scratchpad/transcribe_zoom.py`.
- **o365 mail MCP NOT available**: `jarvis-o365-connector` on cerberus is a REST API (read-focused,
  `o365-connector/api_server.py`), NOT wrapped as an MCP; `gmail-enhanced` MCP has 0 accounts and is
  Google-only (can't serve degenito O365). To enable drafts-to-mailbox: add create_draft/sendMail to
  `graph_client.py`, write `jarvis/o365-mcp/server.py` (mirror memory-mcp), register in `~/.claude.json`,
  restart. (Task available on request.)
- **OMC update**: config refresh is BLOCKED — the 4.15.4 plugin cache is missing the built coordinator
  artifact (fails closed). `~/.claude/CLAUDE.md` is SAFE/untouched. Fix: `/plugin` reinstall/update
  oh-my-claudecode (marketplace `omc`) to **4.15.6**, reload, then `/oh-my-claudecode:setup --global`
  → choose **preserve** (do NOT overwrite — the global CLAUDE.md is heavily customized).
- Two sonnet executors kept stalling in a wait-loop on background test/proof jobs, leaving verified
  work uncommitted. Pattern: take over, verify the targeted tests, commit. Never run a writer executor
  and `scripts/deploy.sh` concurrently (deploy needs a clean tree).

## Operate
- Deploy API+jobs: `bash scripts/deploy.sh` (CLEAN tree, SHA-tagged). SPA: `cd web && npm run build &&
  npx --no-install firebase deploy --only hosting:app --project video-archival-and-content-gen`.
- `export GOOGLE_APPLICATION_CREDENTIALS=/home/jon/.config/gcloud/perkins-deploy-sa.json`.
- Prod smoke: `.venv/bin/python scripts/prod_smoke.py`. Prod DB proxy already running on 127.0.0.1:5432.
- Tim's sheets (read-only, comments + FORMULA) via SA + DWD as `tim@perkinsroofing.net`, scopes
  spreadsheets.readonly + drive.readonly. Drive API is now ENABLED on the project.

---
*Standing archive directive performed: moved CONTINUATION-2026-07-20.md into docs/continuations/;
top level keeps the latest 3 (20-pm, 20-pm2, 21); README pointer refreshed.*
