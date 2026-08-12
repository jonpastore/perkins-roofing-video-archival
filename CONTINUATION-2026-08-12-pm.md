# 2026-08-12 pm — wind cleanup and PII redaction built; A/B ready to judge

Picks up from [CONTINUATION-2026-08-12.md](CONTINUATION-2026-08-12.md), which has the day's
earlier work (publish queue, metal uplift, CompanyCam tags) and §1 "what I got wrong today".

**STATUS: committed, suite green, R2 findings fixed.** R2 returned **REJECT** with two CRITICALs —
both reproduced against real ffmpeg, neither caught by the 20 passing tests, one of them a silent
PII leak. Both are fixed and mutation-verified (§3), and the post-fix suite is **green: 5,702
passed, 5 skipped, exit 0** captured before any pipe.

**What is NOT done: the fixes have not themselves been reviewed, and there is still no way for an
operator to mark a region** (§3, "Known-remaining"). Start at §4.

---

## §1 — THE A/B FILES, IN `./ab-review/` (gitignored)

Open these first. They are the point of the exercise.

| File | What it is |
|---|---|
| `wind_00_original.mp4` | untouched source |
| `wind_01_before_current_default.mp4` | **what we ship today** (`audio_enhance=True`) |
| `wind_02_after_wind_profile.mp4` | **new** (`audio_wind=True`) |
| `redact_01_before.mp4` / `.png` | untouched |
| `redact_02_after.mp4` / `.png` | **two** regions pixelated (tablet + logo) — regenerated after the N≥2 fix |

### Wind — measured

Source `0HT_UlALdUs` ("REAL TALK ABOUT YOUR ROOF"), chosen by **measuring** sub-100 Hz energy
across three candidate clips, not by guessing which sounded windy.

| | sub-100 Hz | speech 200–4k | wind-index | LUFS |
|---|---|---|---|---|
| original | −27.2 dB | −18.5 dB | −8.7 | −14.06 |
| before (today's default) | −25.3 dB | −18.6 dB | **−6.7** | −13.93 |
| after (wind profile) | −27.9 dB | −18.4 dB | **−9.5** | −13.95 |

**The finding: the EXISTING default chain makes outdoor audio worse.** It lifts the wind band 2 dB
*closer* to speech, because `loudnorm` and `acompressor` boost rumble while `afftdn` cannot model
non-stationary wind. The new profile reverses that — **2.8 dB better than today's default** — with
speech level unchanged (−18.6 → −18.4) and loudness still on the −14 LUFS target.

🔴 **I could not listen to these. 2.8 dB is real but modest, and this clip is moderately windy, not
badly.** Jon's ear decides whether it ships. A genuinely bad-wind clip would show more.

### Redaction

**No clip I checked had a legible street number.** Rather than fabricate one, I used a better real
target from actual Perkins footage: a tablet displaying client property photos in `Cb5x0AGDtyA`.
Same mechanism, real PII.

Two things happened worth recording:
- I passed the wrong frame size (1080 when the clip is 720) and the mosaic landed off-target. With
  the true dimensions **validation caught it**: *"region 0: extends to x=1030, past the 720px
  frame."* The guard works — but R2 then found `render_job` never passed those dimensions in
  production, so the guard was dead code outside the tests. Now fixed (§3).
- My first behavioural test compared raw ffmpeg stderr, which contains the filename and encode
  speed, so it failed for the wrong reason. Rewritten to measure **PSNR per quadrant**, then
  mutation-tested: making the overlay a no-op fails it.

---

## §2 — WHAT WAS BUILT

### Phase 1 — wind (`core/audio_enhance.py`)

The module already existed and was already wired. Its `afftdn=nf=-25` is described **by its own
comment** as tuned for "HVAC/room noise" — indoor and stationary. Tim shoots outdoors.

Added `wind: bool = False`, which prepends `highpass=f=90` and softens afftdn to `-20`:

```
wind=False  afftdn=nf=-25,acompressor=...,loudnorm=...            <- byte-identical to before
wind=True   highpass=f=90,afftdn=nf=-20,acompressor=...,loudnorm=...
```

90 Hz because wind energy on a phone mic sits mostly below ~100 Hz, under the fundamental of adult
speech (~85 Hz male). `test_default_chain_is_byte_identical` pins the old string so this cannot
leak into existing renders.

### Phase 2 — PII redaction (`core/video_redact.py`, NEW)

Pure filter builder: crop → scale down → scale up (nearest) → overlay, gated by
`enable='between(t,t0,t1)'`. Pixelate, **not** inpaint. Operator-marked regions, **not** OCR.

Both choices are argued in the module docstring, and both follow `core/photo_privacy.py`'s existing
doctrine — *"a blur is a guess about how much entropy is left in the pixels"*. An operator-confirmed
box is not a guess; an OCR box is. And a visible mosaic says "this was redacted", where a clean
inpaint says "this is what the house looked like".

`RedactionError` is raised, never swallowed: a silently-dropped region is unredacted PII shipping on
a green render. `build_redact_cmd` refuses an empty list rather than emitting a passthrough that
would look like a successful redaction.

### Wiring (both, mirroring how `audio_enhance` already flows)

`api/routes/clips.py` → `ClipRenderSpec` → persisted in `parts_json` → `get_render_spec` →
`jobs/render_job.py`. Round-trip verified in a live python check; both default to off.

**Redaction is fail-LOUD** — unlike `audio_enhance`, which is non-fatal on exception. A privacy step
that fails quietly publishes the thing it was asked to remove.

---

## §3 — R2 CAME BACK: REJECT, TWO CRITICALS, BOTH NOW FIXED

The critic reproduced both against real ffmpeg. **Neither was caught by the 20 passing tests**,
and one of them was a silent PII leak. Both are fixed and mutation-verified.

### CRITICAL 1 — every 2-region render died

`[v0]` was used as both the crop input and the overlay base. An ffmpeg **internal** link feeds
exactly one input pad; `[0:v]` gets away with it only because an input-stream specifier may be
duplicated. So N=1 worked and **every N≥2 graph was rejected**:

```
Stream specifier 'v0' in filtergraph description ... matches no streams
```

Two regions is the *ordinary* case — a house number and a plate, or one number in two shots.
**Fixed** with `split` before the reuse. Mutation-verified: reverting reproduces the exact error.

`test_multiple_regions_chain_so_all_of_them_apply` **passed the whole time** — it asserted
substrings on a graph ffmpeg refused to run, and the only test that touched real ffmpeg used one
region. This repo's recorded *tests-that-re-derive-the-protocol* pattern, again.

### CRITICAL 2 — the silent one: out-of-range time window redacted nothing, reported success

`enable='between(t,t0,t1)'` runs on the **clip-local** timeline — the clip is already cut before
redaction. An operator scrubbing the *full source* video produces source-absolute timestamps that
fall entirely outside the window. ffmpeg exits **0**, and `render_job` logs
`pii redaction applied: regions=N` having redacted nothing.

Reproduced: `t0=600` on a 4-second clip → rc=0, PSNR ~27 across the whole clip (re-encode loss
only, no mosaic anywhere). Exactly the failure `RedactionError`'s docstring says this module
exists to prevent. `core/censor.py` already shifts spans for this reason; redaction had no
equivalent.

**Fixed**: `clip_duration` is validated, and both timeline and coordinate-space contracts are now
stated in `validate_regions`' docstring.

### Also fixed
- **`frame_w`/`frame_h` were never passed in production**, so the bounds guard was dead code and
  only the tests exercised it. `render_job` now probes and passes width, height **and** duration.
- Docstring said `-vf`; the graph carries labels and is only valid as `-filter_complex`.

### Verified CLEAN by the reviewer — including my own worry
🟢 **§5's question is answered: redaction SURVIVES the render.** The reviewer traced every stage —
`_apply_track_a_engines` chains `current` through speech_cleanup → censor → reframe → captions →
broll, `render_job:1004` rebinds `clip_path`, fuse consumes it, and the aspect/platform exports
read `reel_path`. **Nothing re-derives from `src_path` after the cut.** Pixelation is destructive,
so reframe's crop cannot restore detail — the mosaic travels with the pixels. **I was worried
about the wrong thing.**

Also clean: Phase 1's default path is byte-identical (no risk to existing renders); the `enable`
escaping is correct; API wiring is complete; failure handling is fail-loud so a redaction crash
cannot publish; out-of-frame regions clamp and still mosaic (not a leak); 0 and 1 region behave.

### Known-remaining, NOT fixed
🔴 **There is no marking UI.** `grep -rn redact_regions` hits only the five feature files —
nothing produces a region. The module's doctrine is that an operator confirms the box, and no
operator can. Today the only path is a hand-computed `PUT /clips/{id}/render_spec`. **Either build
the frame-scrub tool or mark the field unreachable-by-design**, because it currently reads as
shipped. (`reachability is THE Perkins defect` — here the reader exists and the writer does not.)

🟡 `audio_wind: true` with `audio_enhance: false` is a silent no-op — worth one `logger.warning`.
🟡 `DEFAULT_BLOCK = 16` is an absolute pixel count. On 4K footage a house number may still be
legible under 16px blocks. **Unmeasured** — worth one test on real Perkins footage.
🟡 `redact_regions` is unvalidated at the API boundary, so a malformed region is a render-time
crash in a Cloud Run job rather than a 422.
🟡 No audit trail that a clip *was* redacted, or with what regions. For a privacy control that is
the record a client's lawyer would ask for.

---

## §4 — DO THIS FIRST ON RESUME

1. **Re-run R2** on the post-fix code. The previous review was REJECT; the two CRITICALs are
   fixed and the suite is green, but **the fixes have not themselves been reviewed**. Focus on
   the `split`-based filtergraph and the new `clip_duration` guard.
2. **Decide the marking-UI question** (§3, "Known-remaining") — it is what makes Phase 2 real
   rather than latent. Build the frame-scrub tool, or mark the field unreachable-by-design.
3. **Fix the estimate-inputs grid** (§5B) — small, separate commit, verify in a browser.
4. Everything through 566fccc is committed and pushed. Suite green at 5,702 passed.

---

## §5 — JON'S TWO QUESTIONS (2026-08-12, answered — one needs work)

### A. The "show me the formulas" option ALREADY EXISTS — nothing to build

Jon wants every formula and variable in the proposal output so he and Tim can reconcile the
pricing once and for all. **That feature is already shipped.**

**Where:** Quoting → proposal options, directly under *"Include contract FAQ"*.
Checkbox: **"Show how this price was built"** (`web/src/pages/Quoting.tsx:3445`).
Ticking it reveals a radio pair:

| Mode | Label | Use |
|---|---|---|
| **Internal** | *"days × daily rate, profit shown"* | **This is the one for the Tim reconciliation** |
| Customer | *"one price per square, no margin shown"* | what a homeowner sees |

`core/proposal_render.py:669 calc_lines_from_estimate` substitutes ACTUAL VALUES into each
formula, so the page reads `35 sq × $783.88` and `5 days tile × $745 + 3 days demo`, not an
abstract expression. Internal mode prints every line plus overhead build-up and profit.

**Two conditions that will otherwise waste an afternoon:**
1. 🔴 **The user must hold `estimating_manage`.** The `debug=true` flag is gated on it
   (`Quoting.tsx:1451` always sends it; the API strips `explain` for anyone without the role). A
   `sales` user's proposal arrives with no `explain` on any line and the section then
   **suppresses itself** — `proposals.py:1109` fails closed on the SOURCE carrying no
   derivation, deliberately, rather than printing rows that build up nothing. So if the section
   is missing from the PDF, check the role first.
2. The rows are **frozen at create time**, not rebuilt at render (`_freeze_calc_breakdown`,
   `proposals.py:1073`), so a proposal re-renders exactly as sent and cannot silently restate an
   old quote when prices move. Re-create the draft after changing inputs.

UI warns: *"This prints your profit. Only send it to Perkins staff."*

### B. 🟡 The estimate-inputs panel is visually broken — DIAGNOSED, NOT FIXED

Jon's screenshot: the three-column block renders badly. "WATERFRONT / SALT EXPOSED" wraps to
three lines, "Include the Coastal package" wraps **one word per line**, the salt-water distance
text stacks vertically down the column, and the "Roof cuts" / "Project kind" selects are squeezed
to roughly half the width of their neighbours.

**Cause (inference, not yet verified in a browser):** `web/src/pages/Quoting.tsx:2473`

```js
<div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
```

`1fr` is `minmax(auto, 1fr)`, so a grid item whose content has a large min-content width (the long
bold "50,373.4 ft to salt water (CORAL GABLES CANAL (EAST))" string, and the long placeholder
"e.g. 45 — hand-load, no truck access") refuses to shrink and steals width from its siblings.

**Likely one-line fix:** `gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr)"`,
plus `minWidth: 0` on the offending child and a `title=` on the truncated placeholder. Check
`:608` and `:2446` too — same pattern, same latent bug.

**NOT DONE.** It is outside the two phases in flight and was raised at a handoff point. It wants a
browser check, not a blind CSS edit.

---

## §6 — STILL OPEN FROM EARLIER TODAY (unchanged)

1. 🔴 **Wendy could erase 183 staging articles** with one live→staging sync. Jon owns this.
2. 🟡 7 `held` scheduled_content rows (prod-targeted) — Jon's call to release.
3. 🟡 Tim/Marco/Josh reply on the metal uplift page. **No page edits until then.**
4. #460 — 57 engineering tasks, zero client-visible milestones. These two features are the
   first candidates for a "Tim sees X working" demo.
5. #456 cutover gates · #408 Wendy+Eli invite (promised 7/20, unsent) · #444 GCP budget.

---

## Archive directive

When writing the next continuation doc: move the **oldest** top-level `CONTINUATION-*.md` into
`docs/continuations/`, keeping only the latest 3 at top level; fix every inbound link to the moved
file; refresh the README's "most recent" pointer; and update related docs.

**Performed this session:** `CONTINUATION-2026-08-11-pm.md` → `docs/continuations/`. Top level now
holds 08-11-eve, 08-12, 08-12-pm.
