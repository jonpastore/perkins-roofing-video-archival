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

### Prod config written (not code — these are live now)
| key | before | after |
|---|---|---|
| `VIDEO_DESCRIPTION_PROMPT` | empty | 9,544 chars (Josh's, strict-5 hashtags) |
| `repair.roof_types` × 3 branches | `[shingle, tile, metal, flat]` | + `metal_standing_seam`, `metal_5v_crimp`, `metal_corrugated`, `metal_tile` (jupiter v33, miami v34, naples v33) |

---

## §2 ⚠️ THINGS JON MUST DECIDE

1. **`v0.1-DRAFT` TcVersion (id=2) is still in prod with a NULL `content_gcs`.** The code now
   skips it, but it is a placeholder shadowing the real `perkins-josh-2026-07-11` terms and
   probably wants deleting.
2. **218.8 PSF has two clip spacings.** The old guide table said 6" O.C.; Josh's sheet says 12"
   O.C. — and that difference IS the sheet's whole argument. I removed the old row rather than
   publish both. **Resolve against Metal Alliance's actual approval document**, not against
   either copy of the number. Note in `guide.json`.
3. **Waterfront now defaults ON**, so every new estimate quotes the Coastal package unless
   unticked. Jon asked for this explicitly; flagging because it moves price.
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
