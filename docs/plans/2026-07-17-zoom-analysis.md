# Zoom deep-analysis — Tim walkthrough of app.perkinsroofing.net (2026-07-17, 63.5 min)

Recording: `~/Documents/Zoom/2026-07-17 14.24.24 EXCLUSIVE! Private screening…/`
(`video1033724674.mp4`, `transcript.json` word-timestamps, `transcript.txt`, frames every 10s
in `video1033724674_frames/` — `frame_N` ≈ (N-1)×10s).

## How Tim actually estimates (the model to encode)

1. **Custom cuts calculator** [00:00–06:15, frames 7–37]: RoofR linear measurements
   (eaves/hips/ridges/valleys/rakes/wall flashings) each **round UP to 10-ft material pieces**;
   waste factors per cut type. Output = cut-adjusted base $/sq (e.g. $768 vs $770 standard —
   cuts can swing base ±20-30% [30:52–31:19]). One tile calculator reused for shingle/metal via
   **same % difference** [05:33]. → Estimator must ingest RoofR cut LFs and compute this;
   admin config needs the cuts rules section [30:41].
2. **Manual judgment adds stay manual** [02:21–05:30]: roof-cuts $ (e.g. +$45/sq hand-load
   fee for un-deliverable rear roof), roof-height (harness/crane labor), specialty tile
   (vendor quote delta, e.g. Ludowici). These are inputs, not formulas.
3. **Overhead is TIME-based, not per-sq** [09:15–12:54]: daily OH targets (demo/flat $1,050,
   tile $745, metal $850 per day — cross-check OH Metrics tabs); estimator enters days per
   phase (this job: 4 demo + 6 tile). Per-sq OH in the sheet is "a guide, not a rule".
   **Engine ALREADY supports this (v2 daily_series) — the quote-builder UI doesn't expose it.**
   This is the root cause of our $53,910 vs Tim's $51,950 PROTECTOR delta [51:14–51:35].
4. **Tier adders are flat catalog prices** [23:35–25:04, frame 148]: upgrades = squares ×
   set $/sq from the Knowify catalog (no cuts on upgrades). Verified exact vs Greener PDF:
   Caribbean $290, Mediterranean $365, Modern $485/sq. Three tile premiums = clay-tile
   aesthetic choices [51:56–52:26]. Coastal = material upgrade options in catalog (steel→
   aluminum etc.) [35:21–36:11].
5. **Profit floors** [07:03–09:15, 55:59–56:59]: show profit% + P&OH% vs minimums (13% / 33%);
   want an INPUT/slider "set profit to 15%" that reprices; plus fixed-dollar minimums
   ($2,500 per on-site week; per-job minimums on small roofs) as default rules + margin-tier
   buttons.

## Action items (owner → status)

**Fixed DURING/AFTER the call (verify Monday with Tim):**
- Property-save 500 [15:07] → max_length fix `16a662b`/`6ddaf70` ✓ (Tim saw the clean 422 at [47:17]: "that's a good error")
- `[object Object]` [26:56] → `ce6737a` ✓
- Price Book tab empty [42:45, frame 258] → seeded 171 items from Tim's 4/29 sheet ✓
- New-construction checkbox clarity [49:39–50:14] → explicit New-construction/Demo pair `f02790b` ✓
- Comments reconnect button missing [57:03–57:40] → Connect + switch-account + post-as-confirm
  shipped `8531005`; **still to do: make Admin Config → Marketing → social accounts a
  click-to-authenticate surface [58:03–58:20, frame ~349] — that's where they LOOKED first.**
- Gutters inputs [52:32–54:24] → engine+UI shipped `f02790b`; Tim emailed real prices
  ("Gutters", 19:39) → **rework schema to his style-based model** (6"/7" K, box, half-round,
  copper; DS included; 2-story per-LF adds; elbows; leaf guards; leaderheads; removal $3.85/LF;
  <100 LF +$2/LF). In progress.

**New build items (this week):**
1. **Branch management** [40:00–41:11, frame 242]: selector is hardcoded Miami/Jupiter/Naples —
   add branches admin CRUD (+ **GC branch**), branch on customers (backfill miami — only Miami
   Knowify is connected [25:41]), child assets inherit customer branch, dashboards filter by
   branch/all. Tim: "Miami's OH > Jupiter's; Naples has zero OH right now." IN PROGRESS.
2. **Time-based overhead in quote builder**: expose daily_series (demo days + install days by
   series) — closes the $2k PROTECTOR gap.
3. **Tier construction from catalog adders**: good/better/best → PROTECTOR (engine) +
   PREFERRED + 3 PREMIUMs (+ coastal options) as flat adders × squares. Preferred adder
   verified $165/sq (not our $160 — refresh from catalog).
4. **Profit slider/floor rules** (see #5 above).
5. **Demo selector**: "what are you tearing off: shingle/tile/metal(/flat)" driving demo rates
   (tile haul $65/sq vs shingle $30 [13:28–14:14]; +$25–35/sq tile-demo labor adds) — replaces
   roof-type-derived demo adds.
6. **RoofR ingestion**: no public API [18:04]; Tim pays ~$100/mo + $10/report; his website
   widget generates reports from an address [18:45–20:04]. ACTIONS: Jon on Tim's RoofR account /
   call w. RoofR [21:47]; try interfacing with the website widget's data; parse report PDFs
   into measurements+cut LFs (uploads exist already).
7. **CompanyCam**: Tim adding Jon to account [21:52–22:16] → build pull-photos integration
   (research done 7/17: REST v2 + webhooks, PAT self-serve).
8. **Duration-training dataset**: Tim will label 20–30+ RoofR reports with per-phase days +
   notes ("why"), all roof types [10:49–12:54]. SET UP FOR HIM: Drive folder + sheet template
   (columns: roofr ref, roof type, phase, days, notes). Then train duration predictor from cuts.
9. **Material↔price-cell linkage** [43:00–44:07, 55:01–55:57]: Tim maintains prices by editing
   CELL COMMENTS listing materials ("horrific"). Confirmed design: price-book materials feed
   the aggregate input boxes so he only updates material prices. Blocked on: comments live in
   Tim's ORIGINAL sheets (not the shared copies) — **ask Tim to share originals** (or use frames).
10. **Copper commodity pricing** (later): copper varies daily like a commodity [36:22–37:24];
    Jon offered index-based estimator. Needs Tim's dated copper quotes w/ LF quantities.
11. **Low-slope estimator inputs** [33:44–39:41]: deck type (wood/concrete/metal — different
    attach systems: anchor sheet / open-flame / SecuRock), coating system choices
    (acrylic/silicone/urethane), what-you're-demoing. Deck-type table exists in configs;
    quote-builder low-slope UI needs these inputs. **DONE 2026-07-18:** deck/attach-system
    selector + insulation + tapered-ISO toggles added to Quoting.tsx (shown only for low-slope
    roof_types); the coating/system choice IS the roof_type (`pb_silicone_2coat`,
    `stockmeier_polyurethane_2coat`, …). Backend boundary widened: `/estimator/quote` `roof_type`
    is now config-driven (was a stale Literal that 422'd granular exhibit_b keys) and low-slope
    routing is derived from the active config, not a hardcoded coarse set.
12. **Franchise/royalty** [41:11–42:44]: franchise advisors recommended **Qvinci** (QuickBooks
    rollup; NB transcript hears "Cuvincy" — Qvinci is the real product; a qvinci tab is open in
    Tim's browser). Royalty + marketing fee = % of revenue per franchisee. Jon proposed
    dashboard + **automated ACH collection via Stripe** (3-day notice, then draft) — Tim: yes.
    (Backlog B9/B10; QuickBooks per-branch.)

**Business/schedule:**
- Second payment approved [59:02]; Vlad regenerating the WeLeadLab invoice link.
- **Monday: demo improvements to Tim** (then "crypt keepers" — Josh/Marco — get the reveal).
- Next Friday 2pm: marketing/ads session (flows, drip campaign, emails; ad style guide from
  Amber if it exists; Tim-avatar demo from Vlad).

## Reconciliation status (Greener, 43 SQ, Jupiter)
Ours PROTECTOR $53,910 vs Tim $51,950 (+3.8%) — overhead methodology (time-based vs per-sq
guide). Better $55,953 vs his ~$59,045 (adder gap: catalog vs engine multipliers). Premium
adders already EXACT in `core/perkins_packages.py`. Fix = items 2+3 above.
