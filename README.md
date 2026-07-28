# Perkins Roofing — Video Intelligence & Content Platform (v2)

An AI content platform built on Perkins Roofing's YouTube catalog. It ingests videos
(transcript → Content Graph → 3072-dim embeddings), then powers a suite of LLM-driven
features on top of that knowledge base:

- **Ask** — grounded, timecoded, cited answers over the video library (RAG, with abstention).
- **Articles** — SEO articles (pillar/cluster) generated + published to WordPress with Rank Math
  metadata and JSON-LD.
- **FAQ** — mined, grounded Q&A banks feeding articles and standalone FAQ pages.
- **Clips / Reels** — content-graph-driven clip selection → rendered 9:16 reels → Instagram/TikTok.
- **Comments** — question detection + human-approved draft replies.
- **Email** — WYSIWYG/template composer with AI drafting.

Ingestion and generation run as **Cloud Run Jobs**; a **FastAPI** service backs an authenticated
**React/Vite** admin console. Everything runs in GCP (Cloud SQL + pgvector, Vertex AI, GCP STT,
GCS, Secret Manager, Cloud Scheduler) and is 100% Infrastructure-as-Code.

Built by **DeGenito**. Channel: [@perkinsroofingcorp](https://www.youtube.com/@perkinsroofingcorp).

---

## Status

| Gate | State |
|---|---|
| Tests | **1142 passing** |
| `core/` coverage | **100%** (enforced) |
| Lint (ruff) · SAST (bandit) · SCA (pip-audit) | clean (in CI) |
| Web build (tsc + vite) | green |
| Infra | 100% Terraform + Ansible, drift-checked |

## Quick start (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt pytest pytest-cov ruff bandit pip-audit

# the CI gates
ruff check core adapters api jobs
bandit -r core adapters api jobs app -lll -q
pip-audit -r app/requirements.txt
pytest tests/ --cov=core --cov-config=.coveragerc --cov-fail-under=97

# frontend
# Requires Node.js 24 (matches GitHub Actions / Firebase deploy host).
cd web && npm ci && npm run build
```

**Faster PG-backed test runs.** The RLS / billing tests need a real Postgres. By default
the fixtures spin up (and tear down) a Testcontainers instance every run. To reuse one
long-lived `pgvector` container instead — provisioning is paid once, then reused — run the
suite through the helper (it starts the container if needed, uses a fresh DB per run, and
sets `TENANCY_PG_URL` so the fixtures skip Testcontainers):

```bash
scripts/test_pg.sh                                   # full suite
scripts/test_pg.sh --cov=core --cov-fail-under=97    # the R1 gate
scripts/test_pg.sh tests/tenancy -q                  # a subset
scripts/test_pg.sh --stop-pg                          # stop + remove the container
```

Rules for every change are binding — read **[docs/ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md)**
(and **[CLAUDE.md](CLAUDE.md)**) first.

## Repository layout

| Path | What |
|---|---|
| [`core/`](core/) | Pure logic (coverage-gated at 100%) — retrieval, seo, article/faq/miniseries planners, authz, ratelimit |
| [`adapters/`](adapters/) | External I/O — GCP STT/storage/logging, Vertex LLM, WordPress, Meta/IG, TikTok, Resend, Serper, yt-dlp, Firebase |
| [`api/`](api/) | FastAPI service + `routes/` (archive, articles, clips, comments, config, email, faq, scheduling, suggestions, topics, users, video, logs) |
| [`jobs/`](jobs/) | Cloud Run Jobs — ingest, embed, enumerate, archive, render, article, social, crawl-comments, aggregate-topics, … |
| [`web/`](web/README.md) | React + TypeScript + Vite admin console (Firebase auth) |
| [`app/`](app/README.md) | Shared data layer / config / LLM routing (+ the v1 prototype core) |
| [`infra/`](infra/README.md) | Terraform + `migrations/*.sql` + Ansible |
| [`poc/`](poc/README.md) | Original proof-of-concept CLI |
| [`tests/`](tests/) | Test suite (`core`, `api`, `adapters`, `jobs`) |
| [`docs/`](docs/) | All project documentation (indexed below) |

---

## 📚 Documentation index

### Start here — charter & direction
- [CLAUDE.md](CLAUDE.md) — project rules for agents/contributors (summary of the engineering rules).
- [docs/ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md) — **binding** R1–R5 (coverage, per-wave review, 100% IaC, drift, Ansible).
- [docs/superpowers/specs/2026-07-04-perkins-platform-v2-design.md](docs/superpowers/specs/2026-07-04-perkins-platform-v2-design.md) — the v2 design spec (architecture).
- [docs/MATURITY-ROADMAP.md](docs/MATURITY-ROADMAP.md) — north-star plan to a cutting-edge AI product (Tier 0 = AI eval harness).
- [docs/BACKLOG.md](docs/BACKLOG.md) — ideas + deferred hardening items (§B6/§B7 from the reviews).

### Implementation plans (waves)
- [Wave 0 — Foundation](docs/superpowers/plans/2026-07-04-wave0-foundation.md)
- [Wave 1 — Data completeness](docs/superpowers/plans/2026-07-04-wave1-data.md)
- [Wave 2 — Content engines](docs/superpowers/plans/2026-07-04-wave2-content.md)
- [Wave 3 — Video pipeline](docs/superpowers/plans/2026-07-04-wave3-video.md)
- [Wave 4 — Social publishing](docs/superpowers/plans/2026-07-04-wave4-social.md)

### Component guides
- [app/README.md](app/README.md) — the production core / shared data layer.
- [web/README.md](web/README.md) — the React admin console.
- [infra/README.md](infra/README.md) — Terraform layout, apply/bootstrap, drift.
- [poc/README.md](poc/README.md) — the original proof-of-concept CLI.

### Operations & setup
- [docs/PRODUCTION_CHANGES.md](docs/PRODUCTION_CHANGES.md) — required config/plugins outside the codebase.
- [infra/SECRETS.md](infra/SECRETS.md) — the Secret Manager inventory and how secrets are wired.
- [docs/GSUITE_DIRECTORY_SETUP.md](docs/GSUITE_DIRECTORY_SETUP.md) — GSuite directory dropdown (one-time setup).
- [docs/YOUTUBE_REPLY_OAUTH.md](docs/YOUTUBE_REPLY_OAUTH.md) — enabling direct YouTube reply posting.

### Reviews (per-R2 verdicts)
- [2026-07-07 — deep review (backend)](docs/reviews/2026-07-07-deep-review.md)
- [2026-07-07 — comprehensive review (frontend / tests / adversarial / perf / SAST)](docs/reviews/2026-07-07-comprehensive-review.md)

### Session history / continuations
- **Most recent:** [CONTINUATION-2026-07-28.md](CONTINUATION-2026-07-28.md) (SEVEN COMMITS; the profit AND overhead mechanisms both changed. #433 is CLOSED AND DEPLOYED — a customer-mode proposal no longer prints PM Incentive, verified on a rendered document. #432 makes profit an operator percentage of eligible_base, server-side, with the $2,500/week floor ENFORCED: the Quoting slider had been computing the same figure in the browser and posting it as `flat`, where the floor only warned. #434 gives repairs profit — Tim's live example goes $1,685 -> $1,935, and EVERY repair quote rises $250 once deployed. ⚠️ THE OVERHEAD MODEL CHANGED: Jon settled it as ONE daily number per branch x days, margin the only negotiable lever. Built as overhead_basis='branch' and shipped defaulted OFF, then **FLIPPED ON and DEPLOYED 2026-07-28 (`7e335fe`, verified live on `platform:7e335fe`)** — Jon: *"use tim's numbers we validated it in the transcripts and his own quote sheet showing 1400/day OH. stop blocking that."* All three branches now price overhead as days x one branch daily burn: jupiter v26 $1,400/day (+8-10%), miami v28 $4,250/day (**+46-54%**), naples v26 $1,400/day CARRIED FORWARD from Jupiter, not measured (Tim has never stated Naples — OI-12 stays open). The burn is a FLOOR and margin is the only negotiable lever; that flat $1,400/day prices Tim's own 21 sold jobs at median -0.4% margin with 19 of 21 below his $2,500/week floor is now read as the margin squeeze itself (#431: materials +8% YoY, realised prices -24% from the 2024 peak), not as evidence against the model. ⚠️ This makes the multi-building distortion WORSE while #430 is held: Evergrene's 9 buildings each carry their own days x burn on top of fixed fees and the floor already applying nine times. Open items went 9 -> 5: six were STALE (claimed nulls prod had carried for weeks) and three more were answered from Tim's own documents — insulation breakpoints were already implemented and the checker read a dead key; plywood was never a missing number but a WRONG UNIT (per SHEET on his Lumber Schedule, not per square); the low-slope zone split is AVAILABILITY, not price. The Lumber Schedule exhibit on every proposal stated NO PRICES. Day model 83% -> 86% honest, NOT the 90% a leaderboard showed. Knowify was bound to Josh's tenant; **Tim granted admin 2026-07-28 and it is now re-bound to HIS — Perkins Roofing Jupiter, Company 30586 / Tenant 28403 — and scraped** (`be5df14`). His catalog is **226 items to Josh's 26**, 8 modified this month; Josh's has been untouched since 2026-05-07 with $0 accent items. Shipped: **219 scope templates** (171 reroof / 41 repair covering the shingle-tile-metal-flat types he named / 8 accent), a native `<datalist>` **type-ahead** ("type one or two letters and it'll auto-populate the entire scope"), and **4 accent prices** into `line_items` (skylight $1,590, curb-mounted impact $2,860, solar vent on metal $2,689, chimney cap $2,393.46) — additive keys, verified to reprice nothing, and confirmed live at exactly +$1,590 on a real quote. **tile/PREFERRED $165 is SETTLED** — his catalog confirms ours, Josh's $160 was stale. ⚠️ Still open, in `docs/knowify-price-diff-2026-07-28.md`: ridge vent ($9.79 vs his $12.50), the tile upgrade bundles (three sources, three answers, all within $5), West Lake (tier-dependent, so a flat adder is the wrong SHAPE), and HVHZ accent prices carried forward from FBC. ⚠️ Accent items are priced but NOT selectable in the SPA — `extra_line_items` is API-only. Deployed platform:372be23 — three commits above it are NOT deployed.)
- [CONTINUATION-2026-07-27-pm.md](CONTINUATION-2026-07-27-pm.md) (THE 2PM MEETING + Tim's three replies close six of the thirteen questions and CHANGE THE PROFIT MODEL. He confirmed the 5-day week and the per-week floor we shipped that morning — "an eight day job, you want a minimum of $5,000 built in regardless, right?" "Yeah, pretty much" — and killed the $4,000: $2,500 at any size. His own arithmetic gives Miami's overhead: $85k/month over 20 work days = $4,250/day, against Jupiter's $28k/20 = $1,400 which already matched our config. ⚠️ He wants the PER-SQUARE PROFIT SCALE DELETED — "an old thing I used to use... let's not have duplicate mechanisms" — replaced by an operator percentage plus the $2,500 floor, which also makes the 20-square band question moot. ⚠️ And he found a defect in what shipped that morning: "the PM incentive is not something the customer ever needs to see", but customer mode still prints it as a row. Repairs return COST with no profit ($1,685 = $1,185 + $500 materials) and need a slider with $250 min profit / $500 min service call. FIRST VALIDATION AGAINST HIS REAL PRICES: his new sheet carries actual quoted prices on 27 of 30 plus Stories, Pitch and Accessibility — engine vs his own numbers is median +1.0%, 18/21 within 10%, and the morning's floor change moved us TOWARD him, not away. Gotcha: Excel ate his pitch column as dates, 4/12 is stored 2026-04-12 and the MONTH is the rise. Work in Jarvis #432-#445. R2 still never ran. Deployed platform:d44fb51, prod jupiter v20 / miami v21 / naples v20.)
- [CONTINUATION-2026-07-27.md](CONTINUATION-2026-07-27.md) (THE TIM EMAIL IS SENT — 16:08 on 7/27, two attachments: four homes as real proposals, and docs/PRICING_RULES.md rendered to PDF, every rule sourced to a sheet cell / cell comment / email / call timestamp. Two rules were WRONG and both came from evidence nobody had swept: (1) the "93% within a day" headline was IN-SAMPLE and had reached the subject line — four-way-review F8 said so, named the falsification tests and recorded that neither had run; scripts/honest_day_model_cv.py nests rule selection inside the CV loop and the honest figure is 83% / 0.67d, against a 34% constant baseline. The steep-roof rule SURVIVED (re-chosen in 27/29 folds), so F8 was right about the number and wrong about the rule. (2) Tim's 2026-07-10 email answered two questions the draft still asked — SHINGLE INSTALL $700/day is HIS number, and the profit floor is PER ON-SITE WEEK with his own worked example "7 days ... closer to $5,000 ... 2 weeks". We had shipped a flat per-job floor and a docstring defending it with "he never said $5,000 on a two-week job". Now $2,500 x ceil(days/5): lifts 20 of his 29 homes, +$28,655 (+2.6%), 918 Mil Creek $41,575 → $43,075. Also seeded the PM incentive fix ($50 → $100 on a 35-sq Palm Beach residential job) and shipped the build-up CHECKBOX plus a CUSTOMER audience that folds base+overhead+profit into one $/sq line — folding, not hiding, because the rows must still sum to the total; brute-forced over every subset. Prod jupiter v19 / miami v20 / naples v19, deployed 542434f, drift clean. R2 on this wave still UNRUN.)
- [CONTINUATION-2026-07-26.md](docs/continuations/CONTINUATION-2026-07-26.md) (⚠️ §0 answers a question Jon asked and it changes the work: Tim NEVER asked to see how a price was built — the "notes column / word problem into an algebra equation" line at Zoom 7/17 [12:14] is JON asking Tim to annotate his 30 homes, and the draft email currently MISATTRIBUTES it to Tim and must be fixed before sending. Next: seed prod (a 35-sq Palm Beach RESIDENTIAL job charges $50 PM incentive where his live sheet says $100 — fix is in git, prod still runs the old shape), a checkbox for the new "How this price was built" proposal section, and a CUSTOMER mode for it that collapses days into $/sq and never shows profit (hiding the row is not enough — the rest must still sum to the total). This session: mixed sloped+flat roofs now quote as one job (9 of Tim's 30 homes have a flat section that was never being priced; validation on 130 sold jobs moved median error −16.3% → −2.1%); RoofR's pitched/flat split captured (migration 0046) because total_sq was ambiguous; 36% of Perkins roofs are mixed; sold prices TIME-SLICED, which killed my own "metal is 24% low" finding (all-time median blending the 2021–24 boom; real gap −5.6%) and showed 19% of 2025–26 tile jobs sold at exactly the catalog $1,100 — the published sheet IS the price, not stale; 11 pending-Tim config labels closed from the live sheet; Tim's Evergrene COMMERCIAL bid found unopened in the corpus, revealing we have no multi-building project container. Email to Tim DRAFTED not sent, 14 questions (was 22), ONE attachment: four of his homes as real proposals in the shipping format, each followed by audit pages showing the RoofR measurements we read, our days against HIS figure, and every line's rule and inputs. Nothing deployed, nothing seeded. HEAD d3c0a39)
- [docs/continuations/CONTINUATION-2026-07-25-pm.md](docs/continuations/CONTINUATION-2026-07-25-pm.md) (pricing rebuilt from TIM'S CELL COMMENTS, which Jon set as the source of truth over the headline cells: 7/12+ tile is $305 in BOTH zones — two comments both build to $305 — and WinterGuard $135, so the FBC>HVHZ "inversion" was a stale cell, not a zone difference; tile/metal demo keep a real zone split ($30/$40, $45/$60). Profit band edges now match his INCLUSIVE labels (1→$400, 4→$200, 7→$160, 14→$140, 20→$120, 29→$110) — exact-edge jobs had been taking the next band's lower rate. Tim's $2,500 minimum ENFORCED as a flat per-job floor (Zoom [08:52]); the per-week reading would have repriced 17 of his 29 homes +$20,669, flat moves 2 +$655 — switchable via profit_floor_basis. ⚠️ R2 (which I skipped before deploying) caught a CRITICAL: Miami's 1.725x overhead was live and unvalidated — the A/B ran only Jupiter, whose factor is 1.0 by construction — now REVERTED; the admin panel would also have silently collapsed the zoned adders back to scalars. Estimate-debug toggle shows formula+variables per line; 29 RoofR homes stored in `measurements` (load 9.58s→2.05s). CORPUS FIX: tim_sheet_comments.json came from the "Copy of" sheets (0 comments) — the LIVE low-slope sheet has 69 comments NEVER READ. gmail-enhanced-mcp: 4 silent bugs fixed (update_draft wiped the body, threadId never threaded, read_thread 400'd, cc+attachments invisible) — needs a cerberus service restart. Email to Tim DRAFTED not sent, 12 open questions. Deployed platform:27e076d, configs jupiter v17/miami v18/naples v17)
- [docs/continuations/CONTINUATION-2026-07-25.md](docs/continuations/CONTINUATION-2026-07-25.md) (estimator now runs TIM'S OWN METHOD: crew-days derived from RoofR cut geometry + a >=6/12 steep-roof day adder, validated against his 30-home time log — 93% of homes within 1.0 day of his own figures, mean miss 0.53d, mean overhead within $3/home (was 69%/0.98d/+$21 on a squares-only fit). Money bug: the flat published catalog under-quotes his build on 30/30 homes (mean -$72/sq, worst -$150/sq) — tile full prices now refuse the catalog (422), shingle/metal still exposed, Jon/Tim decision pending. UNBLOCKED 7/17 item #9: Tim's 77 sheet cell comments are readable via Drive API + existing DWD (material->price breakdowns, L/M/OH/P, 7/12 adder OH $90/sq, crew-size variants) — saved to ~/perkins-corpus/tim_sheet_comments.json. Also: repair T&M config was NULL on all 3 branches and is now seeded; licence CCC1331944 now prints; scope-of-work templates + proposal redesign shipped; 25 contract-FAQ answers approved; 90 articles re-pushed with <h3> FAQ headings; CI green after a day-long red lint gate. Email to Tim DRAFTED not sent: docs/email-drafts/2026-07-24-tim-estimator-quotes.md. 9 config values still pending Tim. HEAD b1a4277)
- [docs/continuations/CONTINUATION-2026-07-24-pm2.md](docs/continuations/CONTINUATION-2026-07-24-pm2.md) (Tim's 8-item list closed except Wendy's style guide: estimator now AUTO-FILLS labor days from squares using the day model fit from Tim's 30-home time log (24f0700 — config `daily_overhead_day_model`, typed days always win, low-slope derives nothing, auto-fill carries a `daily_days_auto_filled` warning); ⚠️ measured that the two OH modes DISAGREE — by-days runs up to −$243/sq under per-square (barrel tile 43 SQ ≈ −$10.4k/roof), pre-existing and Tim must settle which is authoritative; T&C + contract-FAQ are now optional proposal sections defaulting ON (3bab031); the last 53 articles linked to source videos via the generator's own grounded retrieval → 375/375 (692a367); SPA shows "Labor days used" + the new checkboxes (eae22f1). Gutters were ALREADY seeded in prod — the earlier "needs seed run" note was stale. Email to Tim drafted, not sent. Marketing meeting 7/27 2pm EST still not started. HEAD eae22f1)
- [docs/continuations/CONTINUATION-2026-07-24-pm.md](docs/continuations/CONTINUATION-2026-07-24-pm.md) (articles COMPLETE: 375 compliant on staging, all 62 metal LIVE; QC pass relativized 940 prod-absolute links + repointed 169 dead cluster→pillar links + added down-links (12966ff); fixed gmail-enhanced MCP to run locally (cwd bug + copied cerberus DeGenito token) → pulled Tim's 8-day emails + RoofR corpus to ~/perkins-corpus/; triaged Tim's 8 outstanding items — lumber-chart optional proposal attachment shipped (738b638), gutters already built (needs seed run), estimator overhead-tiers backed out of Tim's 30-home data (docs/ROOFR_OVERHEAD_TIERS.md, Tim-gated to apply), warranty checker/page/metal-articles/Greener all verified done; #7 style-guide BLOCKED on Wendy's guide. Marketing meeting 7/27 2pm EST. HEAD 738b638)
- [docs/continuations/CONTINUATION-2026-07-24.md](docs/continuations/CONTINUATION-2026-07-24.md) (compliance gate now FULLY DETERMINISTIC — closed every seo_ranking/answer_first flake with deterministic ensures: rm_kw_in_intro/meta/slug (bb843d1), rm_slug_length + rm_title_kw_position (35e776b), answer_first lede + 300-char window (17bc445); reprocessed the existing 66 pre-gate articles to 100% on staging via scripts/reprocess_articles.py (89b6950 — whole DB 113/113, all 61 published posts live-updated); added ONE grounding critic per generation iteration (9ba04a9, fixed a Vertex response_schema bug) + scripts/validate_run_with_critic.py (4a01cd7); ran 100 new articles to staging via 5 parallel processes. OPEN: grounding critic is aggressive (20 blockers on 1 smoke article) — calibrate before --apply mass-regen. HEAD 4a01cd7)
- [docs/continuations/CONTINUATION-2026-07-23-pm.md](docs/continuations/CONTINUATION-2026-07-23-pm.md) (compliance-gated article pipeline: core/article_criteria.py = ONE Wendy checklist, _compliance_gate loops until 100% or blocks, batch persists+schedules 10/day; LLM_BACKEND flipped to Vertex; CI green; Metal Roof Warranty plugin+page on staging; email flood fixed; validation found new-gen 8/12 + existing DB 0/12 — the seed of the 07-24 deterministic fixes)
- Archived: [docs/continuations/CONTINUATION-2026-07-22-pm.md](docs/continuations/CONTINUATION-2026-07-22-pm.md) · [docs/continuations/CONTINUATION-2026-07-22.md](docs/continuations/CONTINUATION-2026-07-22.md) · [docs/continuations/CONTINUATION-2026-07-21.md](docs/continuations/CONTINUATION-2026-07-21.md)
- [CONTINUATION-2026-07-20-pm2.md](docs/continuations/CONTINUATION-2026-07-20-pm2.md) (all 3 resume tasks done, commit e8564d8, deployed: (1) Quoting config panel built — deposit/reminder/license + proposal-template CRUD + embedded T&C library; (2) core/proposal_review wired into send_proposal — HIGH issues block send (422) unless override_review, review_error warns-not-blocks; T&C/FAQ/AI-prompt render was ALREADY wired; (3) AV end-to-end validated on a real MP4 through real ffmpeg — 10/10 checks, censor muted span to −91 dB, reframe 9:16, caption mask burned, valid h264/aac; defaults measured correct. Deploy pending a human go — send-gate adds a live LLM call to the send path)
- [CONTINUATION-2026-07-20-pm.md](docs/continuations/CONTINUATION-2026-07-20-pm.md) (pm batch: TikTok refresh-token persist, article-job no-op, non-root Docker, Cloud Run 5xx/job-failure alert policies + activation (alert_email=dmarc@perkinsroofing.net), suggest-clips 500 fix (null timestamps), 4 admin/estimating UI fixes, Clip Studio help modal, core/proposal_review.py (fairness+prompt-injection reviewer, unwired). API ddc6dab, HEAD 749a38d)
- Archived: [docs/continuations/CONTINUATION-2026-07-20.md](docs/continuations/CONTINUATION-2026-07-20.md) · [docs/continuations/CONTINUATION-2026-07-19.md](docs/continuations/CONTINUATION-2026-07-19.md) · [docs/continuations/CONTINUATION-2026-07-17-night.md](docs/continuations/CONTINUATION-2026-07-17-night.md) · [docs/continuations/CONTINUATION-2026-07-17-eve.md](docs/continuations/CONTINUATION-2026-07-17-eve.md) · [docs/continuations/CONTINUATION-2026-07-17.md](docs/continuations/CONTINUATION-2026-07-17.md) · [docs/continuations/CONTINUATION-2026-07-16.md](docs/continuations/CONTINUATION-2026-07-16.md) · [docs/continuations/CONTINUATION-2026-07-11-eve.md](docs/continuations/CONTINUATION-2026-07-11-eve.md) · [docs/continuations/CONTINUATION-2026-07-11.md](docs/continuations/CONTINUATION-2026-07-11.md) · [docs/continuations/CONTINUATION-2026-07-11-pm.md](docs/continuations/CONTINUATION-2026-07-11-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-10-pm.md](docs/continuations/CONTINUATION-2026-07-10-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-10.md](docs/continuations/CONTINUATION-2026-07-10.md) ·
  [docs/continuations/CONTINUATION-2026-07-09.md](docs/continuations/CONTINUATION-2026-07-09.md) ·
  [docs/continuations/CONTINUATION-2026-07-08-pm.md](docs/continuations/CONTINUATION-2026-07-08-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-08.md](docs/continuations/CONTINUATION-2026-07-08.md) ·
  [docs/continuations/CONTINUATION-2026-07-06-pm.md](docs/continuations/CONTINUATION-2026-07-06-pm.md) ·
  [docs/continuations/CONTINUATION-2026-07-06.md](docs/continuations/CONTINUATION-2026-07-06.md) ·
  [docs/continuations/CONTINUATION-2026-07-05.md](docs/continuations/CONTINUATION-2026-07-05.md) ·
  [docs/continuations/CONTINUATION-2026-07-05-am.md](docs/continuations/CONTINUATION-2026-07-05-am.md)

### Origins (v1 prototype & proposal)
- [PRODUCTION-BUILD-PLAN.md](PRODUCTION-BUILD-PLAN.md) — the v1 production build plan.
- [OVERNIGHT-RESULTS.md](OVERNIGHT-RESULTS.md) — the overnight POC results.
- [Perkins-Roofing-Proposal.md](Perkins-Roofing-Proposal.md) ([PDF](Perkins-Roofing-Proposal.pdf)) — the client proposal.

### 🔒 Internal (DeGenito only — not for client distribution)
- [INTERNAL-NOTES.md](INTERNAL-NOTES.md) — commercial/engagement notes (pricing). Keep internal.

---

*This README is the front door. When the code and a doc disagree, the code wins — please fix the doc.*
