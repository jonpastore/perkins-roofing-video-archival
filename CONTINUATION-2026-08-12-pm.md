# 2026-08-12 pm — wind cleanup and PII redaction built; A/B ready to judge

Picks up from [CONTINUATION-2026-08-12.md](CONTINUATION-2026-08-12.md), which has the day's
earlier work (publish queue, metal uplift, CompanyCam tags) and §1 "what I got wrong today".

**⚠️ NOTHING IS COMMITTED. The full suite and the R2 critic review were still running when this
was written.** First task on resume is §4.

---

## §1 — THE A/B FILES, IN `./ab-review/` (gitignored)

Open these first. They are the point of the exercise.

| File | What it is |
|---|---|
| `wind_00_original.mp4` | untouched source |
| `wind_01_before_current_default.mp4` | **what we ship today** (`audio_enhance=True`) |
| `wind_02_after_wind_profile.mp4` | **new** (`audio_wind=True`) |
| `redact_01_before.mp4` / `.png` | untouched |
| `redact_02_after.mp4` / `.png` | client property photos pixelated |

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
  frame."* The guard works, and it works because the caller passes real dimensions — see §5.
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

## §3 — TEST STATUS AT TIME OF WRITING

- `tests/core/test_video_redact.py` — **20 passed**, incl. a PSNR behavioural test that was
  mutation-verified
- `tests/core/test_audio_enhance.py` — **43 passed** (7 new)
- ruff clean on every touched file
- ⚠️ **Full suite: NOT CONFIRMED.** Two runs were in flight. **Re-run it.**
- ⚠️ **R2 critic review: NOT READ.** Launched, never returned before the session ended.

---

## §4 — DO THIS FIRST ON RESUME

1. **Re-run the full suite** and capture the code before any pipe:
   `.venv/bin/python -m pytest tests -p no:warnings > /tmp/s.log 2>&1; echo "EXIT=$?" > /tmp/s.exit`
   (`pyproject` sets `addopts="-q"` — do NOT add `-q` or the summary line vanishes.)
2. **Re-run the R2 review** (architect + critic) on `core/video_redact.py`,
   `core/audio_enhance.py`, `core/render_spec.py`, `jobs/render_job.py`, `api/routes/clips.py`.
3. **Answer the open question in §5 before committing.** It is the one that decides whether Phase 2
   is safe.
4. Only then commit — Phase 1 and Phase 2 as separate commits.

---

## §5 — THE OPEN QUESTION I DID NOT RESOLVE

🔴 **Does a later render stage move the mosaic off the PII?**

`render_job` applies redaction early, then `speech_cleanup`, `reframe`, captions and `fuse` run
afterwards. `reframe` **crops and repositions the frame**. The redaction is applied at fixed pixel
coordinates in the *source* frame.

If reframe crops to a 9:16 window, the mosaic moves with the pixels it covers — which is fine — but
I did not verify that, and I did not verify that reframe cannot scale/pan such that the PII re-enters
frame from outside the redacted box. **A redaction a later stage undoes is worse than none**, because
the operator believes it worked.

This was the main question put to the R2 reviewer. Resolve it before this ships. The cheap proof is
an end-to-end render with `reframe=True` and a redact region, then eyeball the output.

Related, unverified: `redact_regions` coordinates are in **source-frame pixels**. Nothing yet
records what resolution the operator marked them against. If the UI marks on a preview of a
different size, every box is wrong — that is exactly the mistake I made by hand in §1, and it only
surfaced because validation had the true frame size. **Consider storing `frame_w`/`frame_h`
alongside the regions and passing them to `build_redact_cmd`, which already accepts them.**

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
