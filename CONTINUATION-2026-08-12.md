# 2026-08-12 — the publish queue was a dead end, and the uplift number was right all along

Picks up from [CONTINUATION-2026-08-11-eve.md](CONTINUATION-2026-08-11-eve.md).

**Everything from that session shipped.** Prod is on `api-00259-c4s` (`:955e9a5`), migrations 0057
and 0058 applied, 5,668 tests green. Six commits pushed today, all deployed.

---

## §1 — WHAT I GOT WRONG TODAY, AND HOW

Read this before trusting anything below. I corrected myself **five times** in one session, and
Jon caught three of them. The pattern was identical every time: **I stated an inference with the
same confidence as a thing I had verified.**

| I claimed | Truth | What I did wrong |
|---|---|---|
| "−218.8 is untraced / unsupported" | It is **FL31653.03-R5**, Approved, HVHZ, live to 2029 | Treated *"I could not find it"* as *"it does not exist"* |
| "Metal Alliance holds no approvals, they only supply coil" | They hold **12** approvals under FBC 2023 | Concluded from absence of search hits |
| "26ga at 218.8 is implausible — thinner than 24ga" | 26ga Grade 80 out-rating 24ga Grade 50 is **normal**; and here it is connection-controlled anyway | Asserted a physics constraint that was an assumption |
| "The supplier sheet is *physically impossible*" | A genuine comparability **warning**, not a proof | Overreached on wording; two reviewers said so |
| "Our approval expired" | The **24ga** NOA expired. The **26ga** panel the page cites is live to 2029 | Conflated two different products |

**The habit that fixed it:** Jon pushed back three times ("we're missing something", "you've been
wrong a lot"), and each push was right. Adversarial review by Grok + GPT-5.6 caught the wording
overreach; a **headless-browser query of the actual database** caught the rest.

**Rule going forward, applied in the doc:** every finding is labelled *verified from document* or
*inference*. Do not merge the two.

⚠️ **Also:** a task-notification saying "completed (exit code 0)" reports the **wrapper's** exit,
not the command's. `EXIT=0` was captured in a file before any pipe and read back — one full suite
had actually failed 3 tests while the notification said 0. Always capture the code yourself.

---

## §2 — THE METAL UPLIFT INVESTIGATION (resolved; awaiting client reply)

Tim answered the NOA question with two links. Chasing them properly took the whole afternoon and
**ended by vindicating his number.**

**Verified from primary documents, all archived in `docs/noa/`:**

| Row | Approval | Pressure | Clips | Seam | Status |
|---|---|---|---|---|---|
| **Metal Alliance (ours)** | **FL31653.03-R5** | **−218.8** | **12" o.c.** | 90° | **Approved → 05/06/2029, HVHZ** |
| Gulf Coast VersaLoc | NOA 19-0814.04 | −189.25 | 8" o.c. | **180°** | **EXPIRED 10/02/24** |
| Englert 1300 | NOA 25-0528.08 | −165.00 | 12" o.c. | 90° | Current → 06/26/2030 |

FL31653.03-R5 verbatim: *(2) #10 × 1" fasteners per 2" clip, 12" o.c., 90°, −218.8 PSF, factor of
safety 2*, Intertek report J6368.26-450-44 R0, TAS 125 / UL 580 / UL 1897, and *"approved for
installation in Miami-Dade & Broward counties."*

**How it was found:** the Florida BCIS search is an ASP.NET postback form — curl cannot touch it.
`scripts/bcis_lookup.py` drives it with Playwright. **Metal Alliance Inc. is vendor id 12519.**
Perplexity found the Miami-Dade NOA that two rounds of web search missed; Metal Alliance's own
site publishes **zero** approval numbers across all 14 of its PDFs.

**What is actually left on the page** (3 edits, not the teardown I first described):
1. Gulf Coast row — expired NOA + undisclosed 180° seam. Drop or annotate.
2. "More clips is not a stronger roof" → **"strength comes from the tested assembly, not the clip
   count."** Within one assembly more clips *do* carry more load (FL38763.02: 24"→86 … 6"→176).
3. State Englert at matched spacing — *at the same 12", −218.8 vs −165*. Better for Perkins than
   what is published.

📧 **Email sent 2026-08-12 18:07 UTC** to Tim, cc Marco + Josh, with 3 approval PDFs attached,
proposing a–d and asking for approval **before** any change. **Nothing on the page has been
touched.** Full reference: `docs/metal-uplift-noa-reference.md`.

---

## §3 — THE PUBLISH QUEUE WAS A TERMINAL STATE

Jon asked why scheduled articles never published. The cron was **fine** — `/internal/promote` ran
every 15 min returning 200 the whole time.

`error` was a **dead end**: `core/scheduler.py::due` and the row-claim both required
`status == "scheduled"`, and the exception handler set `status = "error"`. One transient failure
removed an article from the system's attention permanently.

Cause: WordPress auth — **401** on 7/27–28, then **403** on 8/4–8/7. Both had cleared. Proof:
`attempts` finished at **0 across all 434 rows** — nothing needed a second try. Every one of those
277 would have published on any run after 8/7 if anything had looked again.

**Fixed** (migration 0058 + `PROMOTE_MAX_ATTEMPTS=5`), and the queue drained live:

```
before:  157 published · 277 error · 0 pending
after:   427 published ·   0 error · 7 held
```

**Sequencing trap that was caught in time:** `--repush` only targeted `status == "published"`, but
`promote_job` only flips STATUS — it never sends the body. Draining first would have published
Wendy's exact duplicate-related-links defect onto 262 pages. `--repush-scheduled` pushes those
bodies with `status=None` (WordPress leaves the status alone — sending `"future"` without a `date`
**publishes immediately**).

🔴 **7 articles are `held`** (ids 12, 18–23, prod-targeted, scheduled 7/17–7/28). `held` is a new
non-claimable status meaning *a human chose not to publish this*, deliberately distinct from
`error`. **Releasing is a one-word status flip to `scheduled`.** They were held because Wendy is
rebuilding prod and Jon had not ruled on publishing to the client's live site.

---

## §4 — ALSO SHIPPED

- **CompanyCam publish tags** (`3fe722b`) — `raw.get("tags")` read a key that does not exist, so
  `tags` was `[]` for ~156k photos. **R2 caught a CRITICAL in my first version**: stamping tags
  inside the per-project crawl put them behind the incremental `needs_media` gate, which a
  finished roof never trips — galleries would have emptied permanently on a green job. Rebuilt as
  an **account-wide** pass (~4 requests vs ~14,700). Building 77: **312 → 9 photos, 22 → 2 videos**,
  verified live.
- **JSON-LD full graph** (`a605c6a`) — `build_article`/`organization`/`person`/`breadcrumb_list`
  had **zero call sites**; WebSite/WebPage did not exist. Behind `PUBLISH_FULL_GRAPH`, **off** —
  turning it on while Rank Math is live duplicates six node types.
- **Wendy's related-links fix** (`87645e3`) — Jon's own working-tree work, committed separately so
  his commit contains only his changes. 183/183 articles had 2–4 blocks; 465 repaired, 473 bodies
  repushed, live pages verified at **1 block**.

---

## §5 — NEXT: AUTOPILOT PHASES 1 AND 2 (the reason for `prompt.txt`)

Research established (both Perplexity and GPT-5.6, plus GCP docs read directly):

- **OpusClip does NOT do PII redaction.** No address/plate/signage blurring. That is our opening.
- We already have the rest of its feature set: `reframe`, `captions`, `captions_emoji`,
  `clip_select`, `clip_fx`, `broll`, `censor`, `speaker_track`, `hook_overlay`, `scene_detect`.
- **`core/audio_enhance.py` already exists and is fully wired** (`render_spec` → `render_job:366`
  → `api/routes/clips.py:874`), default `False`. Its `afftdn=nf=-25` is tuned by its own comment
  for *"HVAC/room noise"* — indoor and stationary. **Wind is low-frequency and non-stationary, and
  nothing in the chain high-passes.**
- **GPU is not needed for either phase.** Verified: Cloud Run offers **RTX PRO 6000 Blackwell
  (96 GB)** and L4 with **scale-to-zero, per-second billing, "no reservations needed"**, and Cloud
  Run **Jobs** support GPU. 5 h/week = **$23/mo (L4)** or **$69/mo (Blackwell)**. Keep that in the
  back pocket; neither phase below requires it.

See `prompt.txt` for the executable task. **Both phases must end with an A/B artifact Jon can
judge by eye and ear without reading code.**

---

## §6 — OPEN, IN PRIORITY ORDER

1. 🔴 **Wendy could erase 183 staging articles.** Staging has 593 posts; prod has 120, newest
   2026-07-02. The articles and `/metal-roofing-warranty/` exist **only on staging** — one
   live→staging sync deletes them, and she is editing prod in the opposite direction. **Jon said
   he would handle this personally. Still the highest-risk open item.**
2. 🟡 **7 held articles** — awaiting Jon's call (§3).
3. 🟡 **Tim/Marco/Josh reply** on the metal page (§2). No page edits until then.
4. 🟡 **#460** — *"57 open tasks and not one is 'Tim sees X working on date Y'."* Still true. The
   autopilot phases exist partly to fix that.
5. **#456** WordPress production cutover — 11 unchecked gates, no owner.
6. **#408** Wendy + Eli webadmin invite — promised 7/20, **still unsent**.
7. **#444** GCP budget + alerts — do before any GPU spend.
8. ~12 unanswered Tim pricing questions (#426, #428, #431, #441, #448, #451, #454, #455, #492).

---

## §7 — THINGS THAT WILL BITE THE NEXT SESSION

- **`pyproject.toml` sets `addopts = "-q"`.** Passing `-q` again makes it `-qq` and **suppresses
  the summary line** — a green run looks truncated. Not a failure.
- **`pkill -f "<pattern>"` matches its own wrapper shell** if the pattern appears in the command
  line. It killed two suite runs this way. Use `TaskStop`.
- **Grepping JSON for `class="related-links"` fails** — quotes are backslash-escaped in JSON.
  Parse it.
- **`scripts/apply_migrations_adc.py` has no ledger and replays from 0013.** Never put an
  unguarded `UPDATE` in a migration. 0057/0058 were applied by running their `ALTER` directly.
- **`adapters.wordpress.update(status=None)`** leaves WP status untouched. Passing `"future"`
  without a `date` **publishes immediately**.
- **gmail-enhanced attachments** need `{"type": "file", "path": ...}` — omitting `type` throws a
  bare `'type'` KeyError.
- **Florida BCIS cannot be curl'd.** Use `scripts/bcis_lookup.py`.

---

## Archive directive

When writing the next continuation doc: move the **oldest** top-level `CONTINUATION-*.md` into
`docs/continuations/`, keeping only the latest 3 at top level; fix every inbound link to the moved
file; refresh the README's "most recent" pointer; and update related docs.

**Performed this session:** `CONTINUATION-2026-08-11.md` → `docs/continuations/`. Inbound links
updated in `README.md` and `CONTINUATION-2026-08-11-pm.md`. Top level now holds 08-11-pm,
08-11-eve, 08-12.
