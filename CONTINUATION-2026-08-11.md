# CONTINUATION — 2026-08-11

Warranty-tool NHD fix shipped and verified; Josh's two approval-queue asks built and deployed;
Josh's brand-video upload unblocked. **Four things are still open and §5 is the plan for them.**

Prior sessions: `CONTINUATION-2026-08-04.md`, `docs/continuations/CONTINUATION-2026-08-03.md`.

---

## §0 THE PATTERN THIS SESSION KEPT HITTING

Five separate defects, one shape: **the write path worked and nothing read it back.**

| defect | written | read |
|---|---|---|
| tidal layer | FDEP classified reaches correctly | the reach wasn't in the graph at all (OSM had the canal as polygons) |
| `VIDEO_DESCRIPTION_PROMPT` | key stored, editable | nothing consumed it (fixed same day) |
| `videos.description` | generated + persisted | `/video/proposals` never returned it → silent regeneration |
| brand video upload | endpoint + 200-MiB validation | service account had read-only on the bucket, never once worked |
| unproxied yt-dlp egress | fallback path existed | no log line — losing the VPN would read as ordinary failures |

**The check that works is exercising the running system**, not reading the code that should do it.
Two corrections I had to make to my own claims prove the cost of skipping that:
- I "verified" the tidal layer against OSM — *the layer's own upstream source*. It agreed with itself.
- I called `incomplete=False` a bug; `jobs/enumerate_channel.py:88` deliberately treats only
  `videos`/`shorts` as coverage-critical. Read the code before criticising it.

---

## §1 SHIPPED AND VERIFIED

**Warranty tool** — PRs #37/#38/#39/#40, plugin **1.6.1** live on staging.
- NHD flowlines (ftype 336/460/558/334) over the 165 marine-WBID tiles merged into the graph as
  untagged ways **before** the barrier snap. 188 Lone Pine Dr: 3,079 ft → **77 ft**, all 9 steels VOID.
- USGS gauge hold-out agreement **82% → 89%**. 1,344 client addresses swept: **135 changed (10%),
  every one strictly more restrictive, 0 looser**.
- Asset 2.3 → 22.4 MB; host sends no content-encoding, so the build writes a `.gz` twin (2.88 MB)
  and `checker.js` inflates it via `DecompressionStream`. **The `.gz` is gitignored — regenerate
  before zipping the plugin.**
- `loadGmaps()` was unmemoised → double Maps injection → the tool **hung on "Finding the address"**
  for anyone typing fast (2 of 3 runs). Memoised + 20s `geocode()` backstop.
- **9/9 gate mutations caught** (`scripts/mutate_tidal_gates.py`). No gate is decorative.

**Platform** — PRs #41/#42/#43/#44, API `a32de84`, frontend live.
- Brand-video upload 502 was `api-run-sa` holding **read-only** on the reels bucket. Fixed via
  Terraform (`objectAdmin`, IAM-conditioned to the `brand/` prefix). Both GCS handlers now
  `logger.exception` — the 403 previously reached only the uploader's browser.
- Download source video on each proposal card (reuses `/archive/{id}/download`).
- `VIDEO_DESCRIPTION_PROMPT` + textarea in Admin Config → **Platform Settings**.
- `POST /video/{id}/description` → transcript → Vertex → **persists** to `videos.description`
  (migration **0056**). Verified end-to-end on `28s-iCZJj_k`.

**VPN verified working** — `archive`/`render` carry the tunnel, `enumerate-channel` deliberately
does not (YouTube blocks datacenter *downloads*, not metadata listing). 8/8 logs: egress 1–5
bot-blocked, download landed on **6/14**. It is load-bearing, not belt-and-braces.

---

## §2 THE EMAIL THAT DEFINES THE REMAINING WORK

**josh@perkinsroofing.net, 2026-08-11 13:41, "Social media prompt + Metal Roof Clip Spacing Sheet".**
It is the source for both features built today — and one requirement was missed:

> "If the clips are ready for publication, please **add a download option**." ✅ done
> "add an area where a description can be auto-generated, **allowing us to review and edit it
> before posting**." ❌ **the panel is read-only**
> "I have included the social media prompt I use for video descriptions below." → **10,962 bytes,
> 18 sections**, saved at `/tmp/perkins_att/` + scratchpad `josh_master_prompt_full.txt`

⚠️ **The attachment is a PNG, not a PDF** — "Metal Clip Spacing (1).PNG", 2.5 MB. There is no PDF
on that message. Jon: *"use the images and text as you fit to best display its reference data,
not a style guide."*

⚠️ **Graph `$filter=from/emailAddress/address eq '…'` MISSES messages** (case sensitivity). It
returned 0 for both Josh and Tim while `$search="…"` found them immediately. **Use `$search`.**
That bug is why I twice told Jon there was no attachment when there was.

**Reference data from the PNG** (the numbers, not the artwork):

| Manufacturer | System | Seam | Clip config | Max tested design pressure |
|---|---|---|---|---|
| Metal Alliance | Mechanical Seam | 1.5" | 12" O.C. | **−218.8 PSF** |
| Gulf Coast | Versaloc | 1.5" | 8" O.C. | −189.25 PSF |
| Englert | Series 1300 | 1.5" | Approved assembly | −165 PSF |

Clips on a 20' panel: 12" O.C. → 20 · 8" O.C. → 30 · 6" O.C. → 40.
Thesis: *more clips ≠ stronger roof*; strength is the tested assembly (PSF). Licence CCC1331944.

---

## §3 OPEN — BLOCKED ON JON

1. **Email to Tim + team** (tim@, marco@, josh@perkinsroofing.net) with the NHD analysis, the
   validations, and the C-8 open item. Never sent. Tim's 8/6 message **does** carry
   `Screenshot 2026-08-06 at 7.42.43 AM.png` (986 KB) + a 1.4 MB JPEG — retrieve and read those
   before writing; one of them is the address Jon referred to.
2. **Josh must retry the brand-video upload.** The IAM binding is verified present, but never
   *executed* — impersonating `api-run-sa` needs Token Creator, and Policy Troubleshooter API is
   disabled. If it fails now, the logs finally say why.
3. **C-8 canal, North Miami** — two gauges 122 m apart: `NE 135 ST` 465 µS/cm (fresh) vs
   `UPSTREAM OF S-28` 20,450 µS/cm. The fresh one wins on channel distance, so a house at the
   S-28 end reads 2,812 ft → warranty-safe. Decide whether the layer draws the salt line right.

---

## §4 GAPS FOUND, NOT YET FIXED

| # | Gap | Evidence |
|---|---|---|
| 1 | Description panel **read-only**; Josh asked to review **and edit** | his email, §2 |
| 2 | `VIDEO_DESCRIPTION_PROMPT` still empty → generic `DEFAULT_PROMPT` fallback in use | queried prod config |
| 3 | Warranty page still carries placeholder uplift data | Josh's sheet is the real source |
| 4 | **Vertex SDK removal date passed 2026-06-24** — `adapters/llm.py` uses `vertexai.generative_models` | runtime warning; `google-genai 2.10.0` already installed |
| 5 | `adapters/media_cleanup.clean_audio` — **no callers** | grep |
| 6 | `adapters/broll_providers.py` — dead scaffold, zero importers | grep |
| 7 | `core/reframe.py` — `speaker_mediapipe` unimplemented | TODO |

**Verified clean, do not re-audit:** all 21 `EDITABLE_KEYS` have readers; 158 UI `apiFetch` sites
all resolve against the live OpenAPI spec; every skipped test is environmental
(`node`/PG/Knowify token) or a deliberate refusal to invent Tim's numbers.

---

## §5 THE PLAN

**P1 — Make the description usable (Josh is blocked on this today).**
- `videos.description` is already persisted and returned by `/video/proposals`. Add
  `PATCH /video/{video_id}/description` (role `approve_video`) accepting `{description}` so an
  edited caption saves. Set `description_model` to `"edited"` on manual save so a human edit is
  distinguishable from a generated one — otherwise "regenerate everything the old model wrote"
  silently destroys hand-written captions.
- `VideoApproval.tsx`: swap the read-only `<div>` for a `<textarea>` + Save (dirty-tracked, so a
  reload cannot silently discard). Keep Regenerate; warn when it would overwrite an edited caption.
- Test: `PATCH` round-trip + the model-flag flip.

**P2 — Load Josh's master prompt into `VIDEO_DESCRIPTION_PROMPT`.**
Source: scratchpad `josh_master_prompt_full.txt` (10,962 B). Set it via Admin Config → Platform
Settings, or a `scripts/seed_*.py`-style versioned write. It contains **no `{transcript}`
placeholder** — `core.video_description.render_prompt` appends the transcript in that case by
design, so it works as-is. Regenerate one description afterwards and read it: the prompt is tuned
for Instagram/Facebook captions, so expect a different register from the current default.

**P3 — Rebuild the warranty page from the clip-spacing reference data.**
Two-column layout Jon asked for: **results** column (the verdict the visitor came for) beside a
**detail** column (the facts that justify it), so the important numbers stay visible while
scrolling. Replace placeholder uplift values with the §2 table. `wp-plugin/perkins-metal-warranty/
assets/guide.json` already holds `uplift[]` with `panel/attachment/psf/mph/hvhz/note` — that is
the shape to fill. Ship the PSF comparison + the clips-per-panel table. Use the PNG's *data*;
do not reproduce its marketing artwork.

**P4 — Vertex SDK migration (own PR, do not ride along).**
`genai.Client(vertexai=True, project, location)` → `client.models.generate_content(...)` /
`embed_content(...)`. **Two traps:** `VertexLLM.chat` reads `response.usage_metadata` for the
per-tenant token meter (shape differs — a silently-zero meter is worse than a crash), and
embeddings are `embed_dim=3072` (wrong `output_dimensionality` mismatches the vector corpus
*silently*). Verify both before merging.

**P5 — Housekeeping.** Delete `adapters/broll_providers.py` (zero importers). Decide whether
`clean_audio` gets wired into `render_job` or removed. Both are deletion-over-addition calls.

---

## §6 COMMANDS

```sh
# rebuild + verify the tidal layer (the .gz is gitignored — regenerate before zipping)
.venv/bin/python scripts/build_tidal_layer.py            # ~8 min from cache
.venv/bin/python scripts/check_tidal_layer.py            # pins; exits non-zero on failure
.venv/bin/python scripts/mutate_tidal_gates.py           # 9/9 gates must catch
.venv/bin/python scripts/sweep_warranty_addresses.py --out after.json --diff before.json

# DB (prod, via proxy — ADC is stale; --gcloud-auth uses the CLI account instead)
~/bin/cloud-sql-proxy --gcloud-auth video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &
export DB_URL="postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins"
# session.info["tenant_id"] = 1 is REQUIRED before the first query (RLS), or platform_scope=True

# deploy — deploy.sh REFUSES a dirty tree (R3-ENFORCE). Jon's tree has unrelated article/Wendy
# work in it, so deploy from a clean worktree rather than stashing someone else's changes:
git worktree add -q --detach /tmp/deploy-wt main && cp .env /tmp/deploy-wt/.env
cd /tmp/deploy-wt && bash scripts/deploy.sh            # ~10 min; then: git worktree remove --force
cd web && npm run build && firebase deploy --only hosting:app --non-interactive
```

⚠️ `npm run build` is the gate, not `tsc --noEmit`.
⚠️ Commit hook needs `Refs #N <pct>%` / `Closes #N` / `No-Task: <reason>` ALONE on its line.
⚠️ Mail: use Graph **`$search`**, never `$filter` on an address.

---

## §7 ARCHIVE DIRECTIVE (STANDING — PERFORM ON EVERY CONTINUATION)

When writing a new session continuation/handoff `.md`: move the **oldest** top-level
`CONTINUATION-*.md` into `docs/continuations/` so only the latest **3** remain at top level, fix
every inbound link to the moved file, refresh the docs index's "most recent" pointer, and update
related docs.

Performed this session: `CONTINUATION-2026-08-02-night.md` → `docs/continuations/`; inbound links
in `README.md` and `CONTINUATION-2026-08-03.md` repointed. Top level now holds 08-03, 08-04, 08-11.
