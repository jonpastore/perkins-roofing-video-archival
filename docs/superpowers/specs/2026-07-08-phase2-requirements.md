# Perkins v2 — Phase-2 Requirements Spec

**Date:** 2026-07-08
**Source:** Perkins Roofing Zoom meeting (recap + next-steps) + tool teardowns (Opus Clip, repurpose.io) + Florida roofing competitor/SEO research.
**Status:** DRAFT — awaiting Jon's approval. Four decisions still open (see §12); defaults noted inline.

> Scope note: the meeting closed out the *current* phase. This spec covers the remaining phase-1
> polish PLUS the net-new tracks Jon requested (Clip Studio parity, media cleanup, distribution,
> AI Presenter, hybrid publishing pipeline, content-safety gate, competitor-topic mining, estimator stub).

---

## 1. Already shipped — confirm only (no build)

| Meeting item | Repo status |
|---|---|
| TinyMCE WYSIWYG email | ✅ `web/src/pages/ComposeEmail.tsx` (`@tinymce/tinymce-react`) |
| Clip Studio tool | ✅ `web/src/pages/ClipStudio.tsx` (captions, brand intro/outro) — extend for parity (Track A) |
| YouTube OAuth → post comment replies | ✅ adapter `adapters/youtube_comments.py::post_reply` (`youtube.force-ssl`) — blocked only on owner authorizing the token |
| Topic "view all" / 8-cap | ✅ pagination exists (`topicOffset`, `TOPIC_PAGE_SIZE`) — confirm archive-specific cap |
| Search / Ask | ✅ shipped |
| IG + TikTok adapters | ✅ `adapters/meta_ig.py`, `adapters/tiktok.py` |

---

## 2. Track A — Clip Studio → Opus Clip parity

Rebuild the useful 80% of Opus Clip in-house (their API is Business-only). Roofing content is
talking-head / job-site, so Opus's multimodal "ClipAnything" is overkill — transcript + LLM
segmentation (their "ClipBasic" equivalent) covers ~95%. A roofing-tuned virality scorer would
*beat* Opus's generic 6M-signal model for this niche.

| # | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| A1 | Viral-moment auto-detection | From existing transcript + content-graph, LLM scores candidate segments 0–99 on Hook/Flow/Value/Trend; returns top-N with start/end. Roofing-tuned rubric. | Must |
| A2 | 9:16 reframe + active-speaker tracking | ffmpeg crop to 9:16; auto-center on active speaker (MediaPipe/TalkNet-class) with motion smoothing; static center-crop fallback. **Biggest technical risk** — must avoid Opus's documented multi-speaker head-cut bug. | Must |
| A3 | Word-highlight (karaoke) captions | Word-level Whisper timestamps → burned-in animated captions; ≥2 brand styles; export SRT/VTT. | Must |
| A4 | Per-clip title/hashtag/description gen | Platform-tuned copy (YT/TikTok/IG) from Josh's explicit prompts. **Gated on Josh sending prompts.** | Must |
| A5 | Brand intro/outro stitching | 1–2s intro + 5–10s social promo/outro (per meeting) concatenated per clip. **✅ intro/outro in repo** — wire into Clip Studio. | Must |
| A6 | Speech cleanup (filler/stutter removal) | Detect & cut "um/uh"/stutters via transcript alignment (Opus ships this as "Speech Cleanup"). | Should |
| A7 | AI b-roll / stock b-roll | Pexels stock overlay keyed to transcript context; AI-image generation is Could — beta/hit-or-miss even at Opus (they warn "review closely"). | Could |

---

## 3. Track B — Media cleanup  *(CLOUD compute — cerberus is dev-only, not attached in prod)*

All cleanup + rendering runs on **cloud** compute (Cloud Run job, GPU where needed, or a managed
API). **Cerberus was a dev acceleration only and will NOT be attached** — no host GPU dependency;
R5's Ansible GPU work does not apply to these tracks.

| # | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| B1 | Audio cleanup | Denoise + loudness-normalize to −14 LUFS (social standard) + de-reverb. Cloud ffmpeg `afftdn`/`loudnorm` first; upgrade to a hosted model (e.g. Auphonic/Resemble API) only if quality falls short. | Must |
| B2 | Video cleanup | Upscale / stabilize / deblock on cloud GPU (Cloud Run GPU or a hosted upscaler API — e.g. Topaz/Replicate). No cerberus. | Should |

---

## 4. Track C — Multi-platform distribution — **FULL repurpose.io feature parity**

Directive: match the full repurpose.io feature set, not a subset. (`repost.io` is a dead/ambiguous
domain — reference is **repurpose.io**, which uses official platform APIs; YouTube partnered with them
for Shorts.) Every platform needs its own dev-app + **2–4 week app review** — the true critical path;
start all app registrations immediately, in parallel with build.

**Platform coverage (all destinations repurpose.io supports):**

| Platform | Official publishing API | Key approval hurdle | Priority |
|---|---|---|---|
| TikTok | Content Posting API (`video.publish`) | audit to post public; token expires 24h | Must — ✅ adapter exists |
| Instagram Reels | Graph API (`instagram_business_content_publish`) | Business acct + app review | Must — ✅ adapter exists |
| YouTube Shorts | Data API v3 (`videos.insert`) | OAuth verify; ~6 uploads/day quota (1,600 units each) | Must |
| Facebook Reels/Video | Pages API | Page admin + review | Must |
| LinkedIn | Posts API | org access via Partner Program | Must |
| X/Twitter | API v2 | paid ($200/mo Basic or pay-per-use) | Must |
| Pinterest | API v5 (`/v5/pins`) | Trial→Standard app review; multipart video upload | Should |
| Snapchat Spotlight | Marketing API | partner access (ad-oriented) | Could |
| Threads | Graph API | Meta app review | Could |

**Full feature parity (repurpose.io):**
- **C1** OAuth token store + auto-refresh per platform/account. (Must)
- **C2** Publish job queue with per-platform rate-limit + retry + status PENDING/IN_FLIGHT/PUBLISHED/FAILED. (Must)
- **C3** Public CDN/GCS signed-URL hosting for the Meta container-creation flow. (Must)
- **C4** Auto-resize/transcode to each platform's spec (9:16, H.264/AAC, per-platform length caps). (Must)
- **C5** Workflow/trigger model: one finished clip → fan out to all selected destinations, hands-off. (Must)
- **C6** Per-platform caption/hashtag customization with variable interpolation (location, product, crew). (Must)
- **C7** Content calendar view for scheduled (not just immediate) distribution. (Should)
- **C8** Watermark-free source handling (our clips are original — passthrough, no removal needed). (Should)
- **C9** Per-platform analytics pull (views/engagement/reach). (Should)
- **C10** Bulk upload → staggered distribution queue. (Should)

---

## 5. Track D — Hybrid pillar/cluster publishing pipeline

Encodes Jon's strategy: seed a % of high-value/AIO topics immediately → 10 pillars, each drips its
supporting articles → when a cluster completes, activate the next pillar. Always-full async.

| # | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| D1 | Cluster/pillar data model | `clusters` (pillar + status); `articles.cluster_id` + `role` (pillar/support) + `priority` + `scheduled_at`. | Must |
| D2 | Seed publish | On launch, publish top X% ranked high-value/AIO keywords immediately. X configurable; **default ~50–60%** (decision D3). | Must |
| D3 | Drip engine | Cloud Scheduler → Cloud Run Job drains a `publish_queue` via `SELECT … FOR UPDATE SKIP LOCKED`; keeps N articles in-flight ("always full"); pillar publishes before its supports; next cluster's pillar activates on cluster completion. | Must |
| D4 | No Redis | Postgres-as-queue (SKIP LOCKED). Cloud SQL already runs; Redis only if sub-second fan-out is ever needed (it isn't for article publishing). Round-2 review already flagged `with_for_update(skip_locked)` for double-publish safety. | Must |
| D5 | NO engagement-simulation bot | Vlad's "AI agent simulating scroll/dwell" is **rejected** — ineffective (Google doesn't rank on client-side dwell) and a spam-policy risk. Freshness = real cadence + internal linking + updated timestamps. | Must (explicit non-goal) |
| D6 | AIO answer-block + FAQ schema | Every article leads with a 40–60 word plain-declarative answer block and carries FAQPage schema (long-tail 8+ word queries are ~7× likelier to trigger an AI Overview; "near me" rarely does). Extends existing JSON-LD/FAQ. | Should |

---

## 6. Track E — Content safety / professionalism gate

Jon's requirement (the "where do roofers pee" incident — crude output must never publish).

| # | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| E1 | Pre-publish professionalism/toxicity filter | Every generated artifact (article, FAQ, clip caption, social copy, avatar script) passes a gate BEFORE publish/schedule. Two layers: (1) fast denylist/regex for crude terms; (2) LLM-judge rubric scoring professional/on-brand/safe → block + flag for human review on fail. Nothing publishes without PASS. | Must |
| E2 | Audit trail | Blocked items logged with reason; reviewable in dashboard. | Should |

---

## 7. Track F — AI Presenter (Tim avatar)  *(Tim consent ✅ confirmed)*

| # | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| F1 | Voice clone | ElevenLabs Professional Voice Clone from Tim's archived audio (consent recorded per ElevenLabs ToS). Cloud API — no cerberus. | Should (Phase-2) |
| F2 | Avatar video | Photoreal Tim avatar; **default engine HeyGen** (decision D4) — script → talking-head video via cloud API. | Should (Phase-2) |
| F3 | Topic-driven generation | Tim picks a topic → grounded script from the 841-video corpus → E1 safety gate → avatar render. | Should (Phase-2) |
| F4 | Demo seeded by competitor gap | First avatar demo targets a blue-ocean gap topic (see §9, e.g. roof-age/nonrenewal survival guide). | Could |

---

## 8. Track G — Competitor topic mining  ✅ research complete (see §9)

| # | Requirement | Acceptance criteria | Priority |
|---|---|---|---|
| G1 | Gap analysis | Delivered (§9 content gaps). Feeds pillar map + avatar demo. | Done |
| G2 | Pillar/cluster topic map | Delivered (§9). | Done |
| G3 | Keyword-volume validation | Public sources don't expose per-keyword FL volumes. One-time: pull **Google Keyword Planner geo-filtered to FL** (free w/ Google Ads acct) to finalize seed sequencing. Not a blocker. | Should |

---

## 9. Florida content strategy (from competitor research)

**Positioning:** No Florida roofing competitor runs a serious video content operation. Local
competitors max out ~1K YouTube subs; the strong ones (ABC Roofing Corp, Coastal Roofing, Rhino
Roofs) are **text blogs**. National creators (Roofing Insights 147K, Roof Strategist 72K) own the
YouTube lane nationally but **no local player does**. Perkins' 841-video archive is a structural
advantage no regional competitor can match → strategy is **land-grab, not catch-up**.

**The moat is Florida insurance/wind-mitigation law** (highest-value, most under-served):
- Citizens Insurance: 25-yr max shingle / 50-yr tile-metal-slate; RUL exception needs 5+ proven yrs.
- HVHZ = Miami-Dade + Broward **only**. Perkins' home counties (Palm Beach, Lee, St. Lucie) are
  *outside* HVHZ — a differentiator to explain (their pricing calc has both an HVHZ and an FBC sheet).
- 25% roof-replacement rule + the 2007-FBC exception (SB 2-D / §553.844(5)) — most-misunderstood rule.
- HB 1611 (Jul 2024): licensed roofing contractors can now perform RUL inspections — blue ocean.
- My Safe Florida Home grant (up to $10K); HB 293 (2024): HOAs must allow hurricane-rated roofing.

**Blue-ocean content gaps to own (ranked):** (1) roof-age/insurance-nonrenewal survival guide;
(2) wind-mitigation with *actual % discounts* by feature; (3) county-specific cost+code+permit pages;
(4) "what happens if I fail the 4-point/RUL inspection"; (5) the 25% rule × 2007-FBC exception;
(6) Class-4 vs Class-3 shingle insurance-discount; (7) outside-HVHZ positioning; (8) barrel vs concrete
tile deep comparison; (9) standing-seam vs exposed-fastener from the insurance angle;
(10) process/timeline transparency by county; (11) local YouTube video SEO (repackage 841 videos).

### Pillar → Cluster map (10 pillars, ~54 supporting; ★ = publish-first seed)

1. **Roof Replacement Cost in Florida** ★ — ★cost by material (2026) · ★tile cost · ★standing-seam metal cost · barrel-tile cost · flat-roof cost · cost by county (PB vs Lee vs St. Lucie)
2. **Roofing Materials Compared** ★ — ★tile vs shingle vs metal · ★3-tab vs architectural (wind rating) · barrel/clay vs concrete tile · standing-seam vs exposed-fastener · ★Class-4 shingle insurance-discount · best material for hurricanes
3. **Roof Insurance in Florida (nonrenewal & requirements)** ★ — ★roof-age rule (25/50) · ★Citizens requirements · RUL inspection · ★what to do when insurer won't renew · contractor RUL inspection (HB 1611) · fail the 4-point/RUL?
4. **Wind Mitigation & Hurricane Discounts** ★ — ★wind-mit inspection · ★roof features that lower insurance (% savings) · biggest wind-mit discount · secondary water resistance · hip vs gable · My Safe Florida Home grant
5. **Hurricane & Storm Damage Claims** — ★how to file a FL roof claim · post-hurricane documentation checklist · covered vs not · repair vs replace after storm · emergency tarping
6. **Florida Building Code & Permits** — ★25% rule (+2007-FBC exception) · HVHZ requirements (& "outside HVHZ") · permit process by county · 2026 FBC changes · Miami-Dade NOA vs FL Product Approval
7. **Roof Inspection & Maintenance** — ★FL inspection checklist (insurance) · 4-point inspection · how often to inspect · coastal/salt-air maintenance · signs you need a new roof
8. **Roof Financing in Florida** — options compared · PACE (lien risk, senior to mortgage) · bad-credit financing · insurance vs out-of-pocket
9. **Roofing Warranties** — coverage / what voids it · manufacturer vs workmanship · transferability at home sale · by material
10. **Roof Lifespan & ROI** — lifespan by type (salt/UV/hurricane) · 25-yr total cost of ownership · replacement ROI / resale value · repair vs replace

**Publish-first shortlist (~13):** roof replacement cost FL · tile vs shingle vs metal · standing-seam metal cost · roof-age insurance rule · Citizens requirements · insurer-won't-renew · wind-mit inspection · roof features that lower insurance (% savings) · how to file a FL roof claim · 25% rule · Class-4 shingle discount · FL inspection checklist · 3-tab vs architectural.

---

## 10. Track H — Estimator (backend engine — **STUBBED IN THIS PASS, no UI**)

Direction: **no visual/UI stub.** Instead the pricing logic from Tim's workbook is rebuilt as a
backend engine + API, ready to accept input data. A dashboard tab can be added later that POSTs to it.

| # | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| H1 | Pricing engine | `core/estimator.py` — pure, deterministic; transcribes the workbook's rate tables (HVHZ + FBC), per-square build-up, profit sliding scale, adders, project totals, margin back-check. Self-check reproduces the workbook's $20,280 example. | ✅ built (stub) |
| H2 | Estimator API | `api/routes/estimator.py` — `POST /estimator/quote` (itemized estimate) + `GET /estimator/rates` (tables for future UI pickers). Gated on new `manage_estimates` role (admin/web_admin/sales). | ✅ built (stub) |
| H3 | Tests | `tests/core/test_estimator.py` — 22 cases, 100% coverage of the engine; money path validated per R1. | ✅ |
| H4 | Verify canonical base composition | The workbook's KEY block ($430 base) vs per-type lookup ($780 tile base) must be reconciled with Tim before quoting real jobs. Engine accepts explicit overrides meanwhile. `# VERIFY` markers in code. | ⬜ needs Tim |
| H5 | Public/UI surface | Dashboard tab + optional customer-facing self-estimate. | ⬜ deferred |

**Workbook facts captured:** 1 square = 100 sqft. Per-sq = base(L&M) + overhead + profit + roof-cuts +
height + tile-pointing + specialty + pitch/demo adders. Profit is a per-square *sliding scale* by total
squares (1 sq=$400 → 30+ sq=$100). Project total adds delivery $650, "new bonus" $1,350, permit $500
(+$500 commercial), PM incentive (res $150 / comm $300); tile dumpster $300 opt-in. Region variants:
HVHZ (Miami-Dade/Broward) vs FBC (Palm/Lee/St.Lucie) carry different base/OH/solar-vent numbers.

---

## 11. External blockers (owned by others — not build tasks)

- **Josh:** Clip Studio feedback + screenshots/video · explicit title/hashtag/description prompts · IG/social creds · Two Cows (Tucows) registrar access.
- **Tim:** intro/outro clips · registrar access via Amber.
- **All social platforms:** dev-app registration + app review (2–4 wks) — **start now, critical path.**
- **YouTube reply OAuth:** channel owner must authorize the token.

---

## 12. Decisions — RESOLVED (2026-07-08)

1. **D1 — Compute:** ✅ **Cloud** for all video/audio cleanup + avatar render. Cerberus was dev-only,
   NOT attached in prod. Both audio (B1) and video (B2) cleanup run on cloud.
2. **D2 — Distribution:** ✅ **Full repurpose.io parity** — all destinations Must (TikTok, IG, YT
   Shorts, FB, LinkedIn, X); Pinterest Should; Snapchat/Threads Could.
3. **D3 — Seed %:** *[default 55% of the publish-first set immediate, rest drip — confirm or set a number]*
4. **D4 — Avatar engine:** ✅ **HeyGen** (video) + **ElevenLabs** (voice), cloud APIs.
5. **Estimator:** ✅ backend engine + API **stubbed this pass** (no UI), workbook logic rebuilt & tested.

---

## 13. Verification / done-definition (per ENGINEERING_RULES)

Each track ships under R1 (≥97% core coverage — currently enforced at 100% — + behavioral validation
for new I/O), R2 (architect + critic review, fix HIGH/critical), R3/R4 (IaC + drift-clean). **R5 no
longer applies to media tracks:** avatar render + video/audio cleanup run on **cloud** (Cloud Run/GPU
or hosted APIs), not the cerberus GPU node — that box was a dev accelerator only. Content-safety gate
(E1) is itself a behavioral-validation requirement for every generative path. The estimator engine
(H1–H3) already meets R1 (100% covered, self-check reproduces the workbook).
