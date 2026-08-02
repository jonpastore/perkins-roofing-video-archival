# Perkins — execution plan, 2026-08-02

Built from a full verification sweep of every open Perkins task in Jarvis. **Not** from the task
text: each code-checkable claim was checked against the repo, and several tasks said the opposite
of what the code showed in both directions.

---

## What the sweep changed

**Six project records became one.** Jarvis carried `perkins-buildout-2026-07`, `Perkins v2
platform`, `perkins-roofing-video-archival`, `perkins-video-archival`, `Perkins Roofing video
platform` and `Perkins Roofing - Video Intelligence Platform` — 64 open tasks for one client in six
buckets, several with next-actions describing work finished days earlier. All 21 stranded tasks were
re-filed into `perkins-buildout-2026-07` **keeping their task numbers** (idempotent upsert on
`external_id`), and the five empty records are archived.

**Ten tasks were closed as already done**, each verified against the code:

| | | proof |
|---|---|---|
| #430 / #449 | multi-building project | four slices shipped, `platform:2d37cc9`, served bundle verified |
| #418 | commission zone-vs-salesperson | Tim answered; 15% gross / 50% net shipped |
| #385 / #386 | estimator repair mode + roof-type options | `95de3cf`, `/repair-quote`, selector live |
| #320 | Track A engines → Clip Studio | `ClipStudio.tsx` carries broll/captions/music/reframe/transitions |
| #383 | thumbnail gallery | `/articles/{slug}` gallery endpoint + candidate extraction |
| #445 | drone/exterior article frames | `drone_timecodes()` + suggested aerials + extract-frame |
| #350 | CompanyCam connector | adapter + migration 0043 + HMAC webhook |
| #351 | B9 QuickBooks scaffold | migration 0044 + `qb_client_for_branch` + tests |
| #374 | gutter downspout split | `downspout_lf` itemised separately from the gutter rate |
| #377 | article generation loop | local draft → Vertex grounding validation + subscribe footer |
| #440 | R2 on the 7/27 wave | `docs/R2-2026-07-27.md`, titled "(Jarvis #440)", covers both items |
| #376 | analyse the 07-20 Zoom | its output *is* tasks #382–#402 |
| #325 | music catalog | duplicate of #345, which carries the remainder |

**Eight were verified PARTIAL** and now carry an honest percentage rather than 0: #436 (75), #359
(66), #387 (50), #326 (50), #384 (40), #345 (30), #429 (25), #313/#314 (20).

**Two greps lied and were caught.** `#331` matched "solar" in `core/claims.py` — that is *solar
panels as a roof feature*, not the Google Solar API, so the task is correctly still open. `#410`
matched "placeholder" in `core/article_prompt.py` — that is prompt text telling the model not to
emit placeholders, not the generation-side guard the task asks for. **A keyword hit is not a done
task**; every close above rests on reading the thing.

**54 open, one project.**

---

## The shape of what's left

Of 54: **19 are waiting on a person** (13 of those on Tim), **9 are decisions only Jon can make**,
and **26 are buildable now**. The binding constraint is not engineering capacity — it is that
thirteen separate questions are queued for one roofer.

---

## Wave 0 — unblock the humans (days, mostly not code)

**0.1 — ONE consolidated letter to Tim.** Ten open tasks are all "ask Tim", drafted across five
separate documents over three weeks: #415, #414, #426, #428, #431, #441, #446, #448, #422, #451.
That is why none are answered. Merge them into a single prioritised document — money-moving first,
config-filling last — with each question carrying its dollar consequence, and stop sending
one-question emails.

    #451  does General Conditions reach the client, and is it commissionable?   $36,570 / ~$2,385
    #431  the margin squeeze: material +8% YoY, realised price -24%             his own data
    #426  is the daily overhead rate your COST or your CHARGE?                  x2.04 discrepancy
    #414  which overhead mode is authoritative?                                 up to -$243/sq
    #428  which flat system on a mixed roof?                                    9 of his 30 homes
    #422  is the $2,500 floor before or after commission?                       now $5,000 at 50%
    #441  seven unanswered pricing questions                                    1 blocks quoting
    #446  three from the R2 audit    #448  two from the OI sweep    #415  the estimator email

**0.2 — the promises we owe.** #408 Wendy+Eli webadmin invite, promised 7/20 and still unsent.
#442 the 11 GHL message bodies. #443 Crypt Keepers (~$2,000/mo to unwind).

**0.3 — credentials with lead time.** #439 Tim's Knowify login, #315 Josh's social creds + Tucows,
#317 Tim's intro/outro clips.

## Wave 1 — start the long pole NOW (external, 2–4 weeks of waiting)

**#319 social platform dev-app registrations.** TikTok, IG, YouTube, Facebook, LinkedIn, X. The
work is forms; the cost is *calendar*, and nothing about distribution ships until review clears. It
has sat at priority 1 and 0% since it was filed. Starting it costs an afternoon and buys back a
month. Depends on #315 (Josh's creds) for two of the six — start the four that don't.

## Wave 2 — money correctness (code, unblocked)

1. **#429 backfill the pitched/flat split** — 890 sold contracts are provably mixed, 36% of the
   book. `measurements.total_sq` is ambiguous for anything entered before 2026-07-26, so every
   historical comparison is quietly wrong until this runs. Script scaffolding exists (25%).
2. **#436 day model 83% → 95%** — feed Stories + Pitch + Accessibility into the fit and re-measure
   against his 27 actual prices. All three are in his 7/27 sheet (75%).
3. **#417 low-slope: 13 audited gaps unimplemented** — silicone insurance adder, coatings 25-sq
   basis, Stockmeier T&M floor, trash-chute per-story, cover-board OH.
4. **#452 commission on a multi-building bid** — currently zero. Plumbing is buildable now; the
   *base* waits on #451.

## Wave 3 — platform hardening

#359 tenant-2 seams (66% — `strict=True` and `require_role_db` are in, the branch FK is not) ·
#360 CompanyCam reader (the mirror is write-only) · #409 eight hanging tests · #410 the real
generation-side video-id guard · #342 the offline eval harness · #444 the GCP budget.

## Wave 4 — growth surface

#378 metal-first topic mining · #379 prep-for-cutover · #382 metal warranty page + WP plugin
(and #402's aluminum link) · #384 project posting UI (40%) · #407 Wendy's candidate projects ·
#313/#314 the B1/B2 automations, both scoped and unbuilt.

## Wave 5 — decisions, then the long tail

**Overdue:** #339 MTA-STS, due 2026-07-21. Decidable *today* on evidence — read the TLS-RPT reports
landing in dmarc@; zero real failures means drop it and close.
**Jon's calls:** #323/#329 Ez-Bids build-vs-buy · #327 Google Earth Premium · #363 four B6 infra
decisions · #352 B10 (held on Stripe Connect) · #328 1Password rollout · #400 team GitHub org ·
`estimating_view` on a writing endpoint.
**Deferred by size:** #331 SquareQuote rebuild on the Google Solar API — a project, not a task.
**Tail:** #387 #388 #389 #345 #326 #375 #397 #88.

---

## Sequencing, in one line

Send Tim one letter and start the social registrations **this week** — both are pure calendar and
everything else is downstream of them. Then Wave 2, because a pricing engine that is quietly wrong
about 36% of the historical book is the only thing here that can lose money.
