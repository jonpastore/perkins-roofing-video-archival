# Continuation — 2026-08-11 (pm)

Picks up from [CONTINUATION-2026-08-11.md](CONTINUATION-2026-08-11.md). That session's P1–P5 are
done and merged, plus a punch list Jon added live during this one. **PRs #46, #47, #48 are merged
to `main` (dacc919).**

---

## §0 THE PATTERN, AGAIN — 8 more of them

The morning session found five defects of one shape: *the write path worked and nothing read it
back.* This session found **eight more**, and every single one of Jon's proposal complaints was
this and not the thing it looked like:

| what it looked like | what it was |
|---|---|
| "T&C toggle must be off" | `include_terms` defaults true on BOTH sides. `_load_tc_context` took the newest `TcVersion` — `v0.1-DRAFT`, **NULL `content_gcs`** — loaded `""`, and the template dutifully printed "Terms and conditions to be attached." |
| "scope of work isn't showing" | the form has sent `scope_of_work_text` on every proposal since the field existed; **no context field, no template block** ever read it |
| "we need a debug pricing view" | the entire chain existed — engine `explain` → `_freeze_calc_breakdown` → template section → form checkbox — and the UI **never sent `debug`**, so the freeze always failed closed and the checkbox silently unticked itself |
| "no standing seam option" | `repair.roof_types` was config-driven, but the dropdown rendered `EXISTING_ROOF_OPTIONS`, a **hard-coded list shared with the priced demo selector** |
| "Save should work" (video description) | CORS `_ALLOWED_METHODS` never included **PATCH** — and `/quoting/customers/{id}/deactivate` had been calling one from the browser all along |
| `VIDEO_DESCRIPTION_PROMPT` | key existed, editable, **empty in prod** — the generic `DEFAULT_PROMPT` was what ran |
| the 5-hashtag rule | the prompt *asked* for "approximately 5"; nothing checked the output |
| Proposals tab "empty" | `loading` started `false`, so the empty state rendered before the fetch |

**The check that works is still exercising the running system.** Everything claimed below was
verified by calling the endpoint, reading the row back, or checking the PROD config — not by
reading the code that should do it.

---

## §1 SHIPPED THIS SESSION

### PR #46 — editable descriptions, Josh's prompt, warranty 1.7.0
- `PATCH /video/{id}/description`, `description_model = "edited"`, dirty-tracked textarea with a
  beforeunload guard, Regenerate warns before overwriting.
- `core.video_description.enforce()` — hard 5-hashtag ceiling + the OUTPUT RULE's ban on
  `Hook:`/`Hashtags:` scaffolding are ENFORCED; chatter and a tagless caption are **reported**
  (`fixes` / `problems` ride back in the response).
- **`VIDEO_DESCRIPTION_PROMPT` seeded in prod: 9,544 chars.** Generated a caption on
  `28s-iCZJj_k` and read it back through `/video/proposals` — Josh's register exactly.
- Warranty plugin **1.7.0**: two-column checker results (sticky verdict, scrolling detail, both
  from ONE `verdictFor()` call), uplift rebuilt from Josh's clip-spacing sheet.
- Deleted `core/audio_filter.py`, `adapters/media_cleanup.py`, `adapters/broll_providers.py`.

### PR #47 — Vertex SDK migration (own PR, as instructed)
- `vertexai.*` → `google-genai`. **`google-genai` was NOT in `app/requirements.txt`** — this would
  have ImportError'd in prod. Pinned. `adapters/frame_pick.py` had the same import; migrated too.
- Both traps verified live: token meter read **25 tokens** vs a 5-token char-estimate fallback;
  re-embedding a prod chunk scores **cosine 1.000000** at 3072 dims. `embed()` now raises on any
  other width.

### PR #48 — Jon's punch list
T&C selection, scope of work on the proposal, the price build-up, real package names on tiers,
Proposals loading state, gutters/Coastal include-toggles, customer auto-select, paste-to-fill
addresses, **Roofr report upload**, repair metal profiles, Contacts relabelled.

### PR #49 — the address decides waterfront; metal warranty on the proposal (§1a)
Jon's follow-ups, same day.

- **Waterfront is OFF by default again. `core/salt_water.py` decides it from the ADDRESS**, using
  the same tidal layer and the same published setbacks the public warranty checker uses. One
  implementation in `core/`, because an estimate that disagrees with the customer-facing tool
  about the same house is the two-copies defect this repo keeps shipping. Validated against the
  checker's own gate pins and against the 77 ft read out of a real browser: 188 Lone Pine Dr
  **77 ft** (steel VOID, aluminium conditional), Miami River 266 ft, Fort Lauderdale 1,406 ft,
  Golden Gate Estates 38,052 ft and correctly NOT waterfront.
  It only ever ticks the box **on** — a deliberate untick is never silently restored — and a
  failed lookup is non-fatal and never reads as "not waterfront".
- **"Metal Roof Warranty at This Address"** on metal proposals: the distance, each
  manufacturer's verdict at that house, and the terms from Tim's proposal (Metal Alliance 25 yr
  substrate corrosion + 40 yr Kynar, Perkins 10 yr workmanship, Polyglass 20 yr underlayment).
  Two "metal roofs" quoted on one house can carry completely different coverage and the
  difference is the salt-water setback, not the metal — that is the fact a competitor's quote
  does not have.
- ⚠️ The Dockerfile now **COPYs the warranty assets**. Without that line this imports fine,
  deploys fine, and 500s on the first real call.
- Cost measured rather than assumed: 0.9s lazy load, ~3ms per query after, **220 MB peak against
  a 1 GiB limit**, and lazy — an instance that never runs a check never pays it. 100% coverage
  on `core/salt_water.py`.

### The price build-up, verified end to end (Jon asked directly)
`debug=true` → **7 of 7** line items carry `explain`; `debug=false` → **0**. That was the missing
link, and it is fixed. The proposal section renders real arithmetic:

| Line | How it is calculated | Amount |
|---|---|---|
| Base Cost (L+M) | 30 squares × $420.00 | $12,600.00 |
| Overhead | 2 days shingle × $1,064 + 2.5 days demo dry-in flat × $1,064 | $4,789.12 |
| Profit | 30 squares × $100.00 | $3,000.00 |

Tick **Show pricing breakdown** with audience **Internal** — customer mode deliberately collapses
to three summary rows and prints no formulas.

### Prod config written (not code — these are live now)
| key | before | after |
|---|---|---|
| `VIDEO_DESCRIPTION_PROMPT` | empty | 9,544 chars (Josh's, strict-5 hashtags) |
| `repair.roof_types` × 3 branches | `[shingle, tile, metal, flat]` | + `metal_standing_seam`, `metal_5v_crimp`, `metal_corrugated`, `metal_tile` (jupiter v33, miami v34, naples v33) |

---

## §2 ⚠️ THINGS JON MUST DECIDE

1. **`v0.1-DRAFT` TcVersion (id=2) is still in prod with a NULL `content_gcs`.** Harmless now —
   the code skips it and Josh's real terms load (**verified: 42,042 chars, byte-identical to
   row 1**) — but it is a placeholder that will confuse the next person. Worth deleting.
2. ~~218.8 PSF has two clip spacings~~ — **SETTLED 2026-08-11 from Perkins' own proposal** (Tim
   Kanak, "Metal and Flat Re-Roof", 5/26/2026, in the thread Marco sent):

   > "Panel fabricated by Metal Alliance (US Steel) for a **-218.8psf at 12" clip spacing**.
   > Increase clip spacing to 6" for an additional $45.00 per SQ. NOTE: 24 GA is THICKER than
   > 26 GA."

   Josh's sheet was right, the old row (218.8 at 6") was wrong, removing it was correct. The
   quote is now the recorded source, and 6" spacing is shown as the paid upgrade it is — one
   that does NOT raise the tested pressure, which is the section's whole argument.
3. ~~Waterfront defaults ON~~ — **reversed the same day at Jon's request**. It is off, and the
   ADDRESS decides it now (§1a).
4. ~~Warranty plugin 1.7.0 built but not installed~~ — **installed on staging and verified in a
   real browser** (see §3). Nothing outstanding.

### Still blocked on Jon (carried from the morning, unchanged)
- The email to Tim + marco + josh with the NHD analysis and the C-8 open item is **unsent**.
  Tim's 2026-08-06 message DOES carry attachments — use Graph `$search`, never `$filter`.
- Josh must **retry the brand-video upload**. IAM binding verified present, never executed.
- **C-8 canal, North Miami**: two gauges 122 m apart read 465 µS/cm and 20,450. Is the salt line
  in the right place?

---

## §3 DEPLOYED AND VERIFIED ON THE RUNNING SYSTEM

```
pytest tests            green (exit 0). 5 skips, ALL with stated reasons: 1 golden fixture that
                        needs Tim's own number for a 498 sq TPO job (a deliberate refusal to
                        invent one) + 4 live-Knowify smokes behind KNOWIFY_MCP_LIVE=1.
check_tidal_layer.py    all pins pass
mutate_tidal_gates.py   9/9 gates catch their mutation
npm run build           clean
```

**API** — `platform:dacc919`, revision **api-00248-lh7**, 100% traffic. Smoke-tested against prod:

| check | result |
|---|---|
| `PATCH /video/{id}/description` | **200**, `model = "edited"`, and the edit reads back through `/video/proposals` |
| CORS preflight | `GET, POST, PUT, **PATCH**, DELETE, OPTIONS` |
| `POST /measurements/parse-roofr` | live and validating (422 on no file, not 404) |
| `/estimator/rates` repair types | the four metal profiles are served |
| regenerate a description | **exactly 5 hashtags**, `fixes: []`, `problems: []` |

⚠️ **The first smoke run returned 405 and the OLD CORS header.** Traffic was still on
`api-00247-vwm` — I had read `spec.template...image`, which is the template for the NEXT
revision, not what is serving. `status.latestReadyRevisionName` is the field that answers
"what is actually running". Re-verified after `deploy.sh` exited.

**Frontend** — deployed, and the LIVE bundle was fetched and grepped rather than trusted:
`Include the Coastal package`, `Additional contacts`, `Upload a Roofr report`, `Save
description`, `parse-roofr`, `Include gutters` all present. (This repo has shipped a stale
deploy with every check green before — see the 08-03 entry in README.)

**Second deploy (PR #49)** — image `8f7d43e`, revision **api-00251-g28**, 100% traffic.
`POST /estimator/salt-water` smoke-tested three ways against prod:

| check | result |
|---|---|
| by coordinates (cold) | 200 in 2.8 s — **77.3 ft**, ICWW ABOVE ROYAL PALM BRIDGE, steel `void`, aluminium `cond` |
| warm query (Golden Gate) | 200 in **0.3 s**, 38,051.7 ft, not waterfront |
| by address (geocoded) | 200, 77.3 ft — the prod Maps key resolves |
| warranty terms | Perkins 10, Metal Alliance 25 + 40, Polyglass 20 |

The 2.8 s cold call is the proof that the `COPY wp-plugin/.../assets` line landed: without it the
first call is a 500, not a slow success. Frontend redeployed and the live bundle grepped for
`estimator/salt-water`, `metal_warranty`, `warranty_terms` — all present. Plugin **1.7.1** on
staging, serving `checker.css?ver=1.7.1` with the corrected uplift source.

**Warranty plugin 1.7.0** — installed on staging and driven in a real browser at
188 Lone Pine Dr: **77 ft**, summary column `position: sticky`, side by side (summary ends
470px, detail starts 486px), 4 per-material verdicts beside 4 detail cards, and the summary is
still on screen after a 900px scroll — which is the entire point of the layout.

⚠️ Mid-check the tool appeared BROKEN on staging: `no gz`, then `Unexpected token '<'`. That was
GoDaddy **429**-ing me after my own repeated multi-MB asset fetches, not a defect — every asset
serves 200 at the right size when requested once. Worth knowing before diagnosing it as a bug.

`mutate_tidal_gates.py` initially reported **8/9** — `m_version_drift` matched the literal
`'1.6.1'`, so bumping the plugin to 1.7.0 turned that mutation into a silent no-op and reported a
working gate as decorative. It matches the constant by pattern now and **refuses to run if it ever
matches zero times**. A mutation that changes nothing is worse than no mutation: it accuses a good
gate.

---

## §4 NOT DONE

- **USPS address validation.** The paste-parser ships and works; validating the parsed address
  against USPS needs a USPS Web Tools / USPS APIs credential nobody has registered yet. Say the
  word and it is a small endpoint behind that key.
- `core/reframe.py` `speaker_mediapipe` is still unimplemented (§4 gap 7, morning session).

---

## §5 COMMANDS

```sh
# prod DB (ADC is stale — --gcloud-auth borrows the CLI account)
~/bin/cloud-sql-proxy --gcloud-auth video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &
export DB_URL="postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins"

# the two config seeds this session added (both idempotent, both dry-run by default)
PYTHONPATH=. .venv/bin/python scripts/seed_video_description_prompt.py [--apply]
PYTHONPATH=. .venv/bin/python scripts/seed_repair_metal_types.py [--apply]

# deploy — deploy.sh REFUSES a dirty tree, and Jon's tree carries unrelated article/Wendy work
git worktree add -q --detach /tmp/deploy-wt origin/main && cp .env /tmp/deploy-wt/.env
cd /tmp/deploy-wt && bash scripts/deploy.sh
cd web && npm run build && firebase deploy --only hosting:app --non-interactive

# warranty plugin (the .gz is gitignored — check it matches before zipping)
zip -r /tmp/perkins-metal-warranty-1.7.0.zip perkins-metal-warranty \
    -x "perkins-metal-warranty/tests/*" "*/.omc/*" "*.mutbak"
```

⚠️ `npm run build` is the gate, not `tsc --noEmit`.
⚠️ Commit hook needs `Refs #N <pct>%` / `Closes #N` / `No-Task: <reason>` ALONE on its line.
⚠️ Mail: Graph **`$search`**, never `$filter` on an address.
⚠️ `session.info["tenant_id"] = 1` before the first query, or `platform_scope = True`.

---

## §6 ARCHIVE DIRECTIVE (STANDING — PERFORM ON EVERY CONTINUATION)

When writing a new session continuation/handoff `.md`: move the **oldest** top-level
`CONTINUATION-*.md` into `docs/continuations/` so only the latest **3** remain at top level, fix
every inbound link to the moved file, refresh the docs index's "most recent" pointer, and update
related docs.

Performed this session: `CONTINUATION-2026-08-03.md` → `docs/continuations/`; inbound links in
`README.md`, `CONTINUATION-2026-08-11.md` and `docs/mixed-roof-sold-book-2026-08-03.md`
repointed. Top level now holds **08-04, 08-11, 08-11-pm**.
