# 2026-08-12 eve — R2 re-verified by execution, marking UI decided, two UI fixes shipped

Picks up from [CONTINUATION-2026-08-12-pm.md](CONTINUATION-2026-08-12-pm.md), which has the A/B
numbers (§1), what was built (§2), and the two R2 CRITICALs and their fixes (§3).

**STATUS: the R2 fixes are verified by direct execution, not by review opinion. The marking-UI
question is DECIDED (unreachable-by-design, with reasons). Jon's grid bug is fixed and verified in
a browser. Jon's "the debug option is not obvious" ask is built.**

---

## §1 — R2 RE-RUN: HOW IT ACTUALLY WENT (read this before trusting §2)

⚠️ **Both R2 subagents — `architect` and `critic` — were spawned and NEVER REPORTED.** Six
escalating requests each. They emitted only `idle_notification` objects, never prose. **The
failure is FOREGROUND vs BACKGROUND, not the agent type** — see §4d. A `general-purpose` agent
given the identical brief in the FOREGROUND returned a full review in four minutes; the same type
in the background idled out exactly like these two.

**That review found a HIGH defect I had already committed** (§4a). So the lesson is not "the
panel is optional because execution evidence is better" — my execution evidence was real and
still missed this, because it tested the redaction engine and the bug was in the proposal write
path. **Re-spawn in the foreground; do not substitute your own verification and call the review
done.**

The redaction findings below stand on direct execution evidence gathered first-hand, which is
stronger than a review opinion for the things it covers — and narrower than an R2 panel.

What was verified, and how:

### CRITICAL 1 (`split` filtergraph) — **VERIFIED FIXED BY EXECUTION**

Generated a 640x480 / 6s clip with `testsrc2`, ran the real `build_redact_cmd` output through real
ffmpeg for N = 1, 2, 3, 4 regions, and measured PSNR per box against the source:

```
 N |  rc | per-box PSNR (low = mosaicked)   | control (unmarked centre)
 1 |   0 | [21.1]                           | 50.9
 2 |   0 | [21.1, 23.1]                     | 51.0
 3 |   0 | [21.1, 23.1, 21.1]               | 50.8
 4 |   0 | [21.1, 23.1, 21.1, 21.2]         | 50.8
```

Every marked box is mosaicked; the unmarked centre is untouched. **Mutation-verified**: reverting
the `split` back to reusing the label reproduces the original signature exactly — N=1 passes,
N>=2 dies with `Error initializing complex filters`. So the fix is real and load-bearing, not a
change that merely satisfies the substring assertions that let the bug through the first time.

### CRITICAL 2 (`clip_duration` guard) — **VERIFIED, with one residual that CANNOT be closed here**

Against a 6s clip: `t0=600` (wholly past end) **rejected**; `t0==t1` **rejected**; negative `t0`
**rejected**. A *partially* overlapping window (`t0=5.5, t1=99`) is **ACCEPTED** — correctly, since
it does redact 5.5→6.0.

🔴 **But that residual is the whole reason for §2's decision.** If an operator marks
source-absolute `t0=5.5` meaning 5.5s into a 40-minute source, and the clip happens to be 6s long,
the region applies to clip-local 5.5–6.0 — *the wrong half-second, reported as success*. No guard
can tell "operator meant clip-local 5.5" from "operator meant source-absolute 5.5" when both are
in range. **The guard can only ever catch wholly-out-of-range.** The rest has to be prevented by
the thing that produces the timestamps.

---

## §2 — THE MARKING-UI QUESTION: DECIDED — **unreachable-by-design**

`redact_regions` is now documented as **read-only in practice** in `core/render_spec.py`, with the
reasoning, not just a label. The decision is pinned by two tests in `tests/core/test_render_spec.py`
— including one that greps `web/src` and **fails if a UI writer ever appears**, telling whoever
adds it what the two contracts are before they ship a leak.

**Why not just wire a quick box tool** (this is the load-bearing part, VERIFIED FROM CODE):

* `x/y/w/h` are SOURCE-FRAME pixels; `t0/t1` are CLIP-LOCAL seconds. So the operator must draw on
  a video that is **cut but not yet rendered**.
* That artifact does not exist. ClipStudio has exactly two video states and neither is it:
  `ClipStudio.tsx:1411` mounts the render-options panel **only when `!isRendered`** (nothing to
  scrub), and `:1395` mounts the preview player **only when `isRendered`** (already rendered, and
  already reframed — too late).
* Marking against either one produces the §1 residual: a window that silently redacts the wrong
  moment, or nothing, on a green render.

**To make it real, in order:** (1) emit and store a cut-but-unrendered preview MP4 per part,
(2) draw the box against it, converting preview px → source px with the probed frame size,
(3) take `t0/t1` from that preview's own `currentTime`, which is already clip-local. **Until (1)
exists a marking UI cannot be correct**, so there is none. This is written into the field's
docstring so the next reader does not take it as shipped.

### Also closed while here

- 🟢 **`audio_wind` had a reader but no writer.** `jobs/render_job.py:375-376` does read it and
  pass `wind=` to `build_enhance_cmd` (verified), but nothing in the UI could set it. Added the
  checkbox to ClipStudio's render-options panel, nested under Audio enhance and **disabled when
  Audio enhance is off** — which also kills the documented 🟡 "silent no-op" item at the UI.
- 🟢 The same no-op now emits a `logger.warning` in `render_job` for the hand-written-PUT path.
- 🟢 **`redact_regions` was unvalidated at the API boundary** (🟡 in the last doc). It now runs
  `validate_regions` in `save_render_spec_route` → **422 instead of a render-time crash inside a
  Cloud Run job**. Frame size and duration are unknown there, so this catches shape/sign errors
  only — the exact class a hand-computed PUT produces.

Still open (unchanged, all 🟡): `DEFAULT_BLOCK = 16` is absolute pixels and unmeasured on 4K; there
is no audit trail of what was redacted.

---

## §3 — JON'S GRID BUG: FIXED, AND THE DIAGNOSIS NEEDED CHECKING

Committed separately as `a3767bf`. The previous session's cause was labelled an inference, and it
was **right about the mechanism but wrong about when it fires** — which only showed up because the
fix was checked in a real browser (Chromium via Playwright) instead of being declared.

**At a wide card the bug does not exist.** Measured column widths at 760px are `[244, 244, 244]`
before AND after — identical. It only bites below ~680px:

```
 card width   before (cols 1-3)   after              grid overflow before/after
    760px     [244, 244, 244]     [244, 244, 244]         0 / 0
    600px     [207, 158, 207]     [191, 191, 191]         0 / 0
    540px     [207,  98, 207]     [171, 171, 171]         0 / 0
    480px     [207,  81, 207]     [151, 151, 151]        43px / 0
    380px     [207,  81, 207]     [117, 117, 117]       143px / 0
```

The middle column collapses to 39% of its neighbours and below 480px the grid **overflows its own
card by up to 143px** — the third column's input runs off the panel edge. That reproduces Jon's
screenshot exactly, including "Include the Coastal package" at 4 wrapped lines (2 after).

Fix: `repeat(3, minmax(0, 1fr))` plus `width: 100%` on the three inputs that used bare
`inputStyle` (which carries no width, so an `<input>` keeps its ~20-character intrinsic width and
refuses to shrink inside a grid cell). Applied to the two sibling grids at `:608` and `:2446` too.
`inputStyle` itself deliberately unchanged — it is shared app-wide.

Other grids in that file still use bare `1fr` (`:423, :480, :2069, :2758, :2776, :2782, :3355,
:3512`). None was reported, none was verified, none was swept blind.

---

## §4 — JON'S ASK: "the debug option is not obvious — put a checkbox next to the button that
generates it"

Jon chose **the Proposals tab's PDF button**, not the Quoting page. Built there:
**`Show how this price was built`, next to `View PDF`** (`Proposals.tsx:890`), which renders
`GET /quoting/proposals/{id}/pdf?explain=1`.

**The thing that made this more than a checkbox** (VERIFIED FROM CODE): `_freeze_calc_breakdown`
strips `explain` and `calculation_trace` from the snapshot **unconditionally at create time**
(`proposals.py:1100, 1130-1136`). So by the time you are standing on the Proposals tab, the
derivation the breakdown is built from **is already gone and cannot be recovered**. A checkbox that
just flipped `include_calc_breakdown` there would fail closed at `:1114` and **silently untick
itself** — precisely the bug the `debug: true` comment in `Quoting.tsx:1443-1450` describes.

So the internal rows are now frozen at create time **regardless of what the sender opted into**.
That creates a privacy problem and it is handled explicitly:

- `calc_lines_internal` **prints profit**, and every proposal read is gated on `quoting_view`,
  which **`sales` holds** while not holding `estimating_manage` (verified: `proposals.py:1385-1388`
  returns `quote_snapshot`).
- So the rows are **dropped in the serializer** (`_proposal_row`), not filtered per-role — a new
  read path cannot leak by forgetting a check it does not have to make. The SPA gets a boolean,
  `calc_breakdown_available`, which is all the checkbox needs.
- The rows leave **only as a PDF**, via `?explain=1`, which is gated on `estimating_manage` on top
  of the route's `quoting_view`, and is **never served from or written to the GCS cache** (the
  cache is keyed by proposal id alone, so caching it would hand profit to the next reader of the
  ordinary PDF URL).
- Proposals with no frozen build-up return **409 with an actionable message**, not a PDF with an
  empty section.

🔴 **A bug I introduced and caught before committing:** the SPA edits a draft by spreading the
snapshot it *read* and PUTting it back (`Proposals.tsx:433→510`, and the notes path at
`:1006→1013`). Since the read path strips the rows, **saving a note would have silently deleted the
frozen build-up** and the checkbox would have vanished with nothing to explain it. Fixed with
`_carry_internal_calc`, applied at both write sites (`update_proposal` and the revise path), with
a test that reproduces the exact read → spread → PUT round-trip.

**Not verified:** the rendered explain PDF itself. Gotenberg is not running locally, so the seam is
covered by a test that captures the real `ProposalRenderContext` and asserts `calc_lines`,
`calc_audience` and the no-cache guard — **both mutation-verified**. The actual PDF has not been
looked at by a human. That is the first thing to do with a live environment.

⚠️ **A testing note worth keeping.** The no-cache assertion originally **passed against a mutant
with the guard deleted** — `_media_bucket()` throws on a fake row inside the same `try/except` that
swallows upload failures, so the upload was unreachable either way and the test proved nothing.
It only became real after stubbing `_media_bucket` and `_proposal_pdf_key`. *A green assertion on
an unreachable line is this repo's recurring test failure, in a new costume.*

### §4a — WHAT THE LATE R2 CAUGHT (fixed in `eced8b0`)

🔴 **HIGH, and mine.** `_freeze_calc_breakdown` runs at **create only** (`:1215`, `:1371`) — not on
`update_proposal`, not on revise. So nothing rebuilt the rows on an edit, while the SPA's edit path
**re-quotes and PUTs a new `total`/`tiers`/`estimate_result`** (`Proposals.tsx:449-495`). The
carry-forward I added in §4 then re-attached the old rows regardless.

Repro: create from a $43,075 estimate → edit the total to $38,000 → tick the box → the explain PDF
prints the **$43,075 derivation under a $38,000 document**. Line items that do not add up to the
price beside them, in the one report whose entire purpose is that they do.

Fixed by dropping the rows when `total` or `estimate_result` moved. Dropped, not recomputed — the
derivation is genuinely gone. Dropping hides the checkbox, which is honest: *a missing breakdown
asks a question, a stale one answers it wrongly.*

**Two more from the same review — verified, PRE-EXISTING, deliberately NOT fixed:**

1. 🔴 **HIGH — profit is already on the wire.** `api/routes/estimator.py:95` strips only
   `calculation_trace` and per-line `explain`. `core/estimator.py:818` emits
   `"profit_dollars": round(self.profit_dollars, 2)`, and `Proposals.tsx:442` reads it back out of
   the stored snapshot — which proves it survives the read path. **A `sales` user can
   `GET /quoting/proposals/{id}` and read `.quote_snapshot.estimate_result.profit_dollars` today.**
   This weakens §4's whole rationale: I hardened the FORMULAS while the NUMBER was already
   readable. Not fixed because it predates this work and the SPA uses `oldProfit` to hold margin
   flat across a revision, so changing it is **Jon's call, not a silent edit**.
2. 🟡 **MEDIUM — retention.** `Proposal` is in `AUDITED_MODELS` (`core/audit_orm.py:31`) and
   `api/audit_mw.py:73` deliberately bypasses `redact` for `changes` to keep the trail
   revert-capable, so `calc_lines_internal` is kept in `audit_log` permanently. Not a role break
   (that read needs `manage_config`), and narrowing it would break revert.

---

## §4b — JON: "why is estimator stripping my debug if I turned debug on" (`e7f4177`)

**He was right, and the stated reason for the strip is false.**

The response never lost the trace (`:811` returns the full `result`); only the **persisted** row was
stripped. So debug worked for one HTTP response and the evidence was then gone — out of the saved
estimate and out of any proposal built from it.

`_audit_payload`'s docstring claimed it protected `profit_scale`, `pm_incentive`, office burn and
daily rates from `sales`. **Verified field by field, everything it named is already served to that
exact role:**

| what `calculation_trace` / `explain` embeds | already exposed by |
|---|---|
| `profit_scale` | `/rates:profit_scale` — gated `estimating_view` |
| `pm_incentive` | `/rates`, **and** `to_dict()` unconditionally |
| `office_daily_overhead`, `office_men` | `/rates` (`:54`, `:55`) |
| `{series}_rate` daily overhead | `/rates:daily_overhead_rates` (`:50`) |
| `profit_dollars`, `oh_dollars`, `eligible_base`, `commission` | `to_dict()` **unconditionally** |

Only `calculation_trace` and per-line `explain` are debug-gated at all. **The strip removed the
explanation and left every number it explained.** The file already said as much at `:384` — "NOT a
confidentiality boundary" — three hundred lines from the docstring asserting the opposite.

Fixed: `_audit_payload(result, *, debug=False)`, with the quote route passing **`q.debug`** — the
role-gated value from `:387`, so a `sales` caller sending `debug=true` still persists a stripped
row. Default `False` keeps context-free callers (notably `_freeze_calc_breakdown`) unchanged.

⚠️ The first test pass was inadequate in the now-familiar way: helper-level tests left
`debug=q.debug` **deletable at the persist site with everything green**. The test that bites POSTs a
real quote and reads the row back out of the database.

### §4c — CAN `_freeze_calc_breakdown` NOW BE DELETED? **NO — KEEP IT**

The obvious follow-on: if the trace persists, why freeze a copy? Three independent reasons, each
verified:

1. **Project proposals have no estimate to read.** `proposals.py:1383` sets `estimate_id=None` **on
   purpose** ("a project covers N estimates and pointing at one would be the same category error"),
   while still calling the freeze at `:1386`. Every multi-building proposal would lose its
   breakdown outright.
2. **The link moves forward on edit.** `Proposals.tsx:471` relinks to the NEW estimate and PUTs it
   at `:510`, so the proposal points at the newest estimate, not the one it was **sent** with.
   Reading through `estimate_id` would show revised numbers on an old document — the exact defect
   `eced8b0` just fixed from the other direction.
3. **A `sales`-run quote has no derivation at all** (`estimator.py:387` gates debug on the role), so
   there would be nothing to read back for precisely the users who lack `estimating_manage`.

The freeze is also the *narrower* door: `_proposal_row` strips the rows and the explain PDF needs
`estimating_manage`, whereas `GET /estimator/estimates` (`estimator.py:1203`) serves `result_json`
to `estimating_view`.

### §4d — THE AGENT LESSON, WHICH COST REAL TIME TODAY

**Background subagents in this session return `idle_notification` objects and their prose never
arrives. Foreground ones (`run_in_background: false`) return their report as the tool result.**
Eight agents idled out across four spawns — `architect`, `critic` and `code-reviewer` types AND
`general-purpose` — while every foreground `general-purpose` agent returned a full review in under
a minute, including the one that found the HIGH in §4a and the one that settled §4c.

It is **not the agent type**, as I wrote earlier in this file. It is foreground vs background. If a
review matters, run it in the foreground.

## §5 — STATE

Commits this session, in order:

| SHA | What |
|---|---|
| `a3767bf` | `fix(quoting)` — the estimate-inputs grid (§3), its own commit as instructed |
| `f713388` | `feat(audio)` — Phase 1 wind profile + the ClipStudio checkbox that can set it |
| `6b8776c` | `feat(redact)` — Phase 2 API-boundary validation + the unreachable-by-design decision |
| `35f4b7c` | `feat(quoting)` — "Show how this price was built" next to View PDF (§4) |
| `37239ef` | `test(proposals)` — pins the public accept page as an allowlist (snapshot-leak audit) |
| `eced8b0` | `fix(quoting)` — **the HIGH the late R2 caught**: stale build-up under a new price (§4a) |
| `e7f4177` | `fix(estimator)` — **honour debug=true when persisting** (§4b), Jon's request |

⚠️ The archive rename (`CONTINUATION-2026-08-11-eve.md` → `docs/continuations/`) was staged by
`git mv` before the first feature commit and got swept into **`f713388`**, whose message does not
mention it. Content-identical 100% rename, no edits — but if you go looking for it in the docs
commit, it is not there.

Suite at the final commit: **5,713 passed, 5 skipped, exit 0**, captured to a file before any pipe on
a clean collection. `./ab-review/` untouched and still gitignored.

Rules honoured: no deploy, no metal-warranty page edits, no release of the 7 `held`
`scheduled_content` rows.

### Do this first on resume

1. 🔴 **PRE-PRODUCTION GATE — profit is readable by `quoting_view`/`estimating_view` and that is
   ACCEPTED FOR NOW.** Jon, 2026-08-12: *"profit dollar ok for now we will hide debug option when
   we clear to production. right now we need to validate data and only high level people are
   looking."* So this is a DEFERRAL, not a dismissal, and it is the thing most likely to be
   forgotten. **Three separate exposures must all be closed before the tool reaches anyone
   outside the current small internal group:**
   - `estimate_result.profit_dollars` — `estimator.py:95` strips only `calculation_trace` and
     per-line `explain`; `core/estimator.py:818` emits the number. Read via
     `GET /quoting/proposals/{id}`.
   - `calc_lines` with the **internal** audience — `_freeze_calc_breakdown` stores those rows
     under the unstripped key, so ticking "Show how this price was built → Internal" writes profit
     rows that `_snapshot_without_internal_calc` does NOT remove. Only `calc_lines_internal` is
     stripped.
   - the debug trace now persisted by `e7f4177`, served by `GET /estimator/estimates` to
     `estimating_view`. Harmless *today* only because `/rates` already serves the same fields to
     the same role — so closing this one means closing `/rates` too, or it achieves nothing.

   ⚠️ Note the trap: hiding the debug OPTION does not hide the DATA. Two of the three above are
   emitted with no debug flag involved at all.
2. **Look at an explain PDF in a live environment** (§4) — the only part of Jon's ask that has not
   been seen working end to end. Gotenberg is not running locally.
3. **The redaction work has still had no second pair of eyes** beyond my own execution evidence.
   Re-spawn a reviewer **in the foreground** (§4d) — that is the whole trick, and it is cheap.
3. **Jon's ear on the A/B wind files** in `./ab-review/` — still the gate on Phase 1 shipping.
   If the 2.8 dB is too small to matter, the next lever is DeepFilterNet3 behind the same `wind`
   flag, and that dependency needs his go-ahead.

### Still open from earlier (unchanged)

1. 🔴 Wendy could erase 183 staging articles with one live→staging sync. Jon owns this.
2. 🟡 7 `held` `scheduled_content` rows (prod-targeted) — Jon's call to release.
3. 🟡 Tim/Marco/Josh reply on the metal uplift page. No page edits until then.
4. #460 — 57 engineering tasks, zero client-visible milestones.
5. #456 cutover gates · #408 Wendy+Eli invite (promised 7/20, unsent) · #444 GCP budget.

---

## Archive directive

When writing the next continuation doc: move the **oldest** top-level `CONTINUATION-*.md` into
`docs/continuations/`, keeping only the latest 3 at top level; fix every inbound link to the moved
file; refresh the README's "most recent" pointer; and update related docs.

**Performed this session:** `CONTINUATION-2026-08-11-eve.md` → `docs/continuations/`; the two
inbound links (README.md:120 and CONTINUATION-2026-08-12.md:3) repointed; README's "most recent"
pointer refreshed to this file. Top level now holds 08-12, 08-12-pm, 08-12-eve.
