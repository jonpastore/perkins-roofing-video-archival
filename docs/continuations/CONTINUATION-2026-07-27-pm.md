# CONTINUATION 2026-07-27 pm — the meeting answered six questions and changed the profit model

**HEAD `18b75ac`**, pushed. Deployed image `platform:d44fb51` (the two commits above it are docs
only). Prod configs **jupiter v20 / miami v21 / naples v20**. `drift_check` clean.

The Tim email went out at **16:08**. He replied three times between 20:22 and 20:36, and the 2pm
meeting is transcribed. Together they close six of the thirteen questions and **change the profit
model**. Jarvis **#432–#445** carry the work.

---

## 0. Read these three artefacts before touching the estimator

| | |
|---|---|
| `docs/meetings/2026-07-27-marketing-and-estimator.md` | answers, action items, plan |
| `docs/meetings/2026-07-27-transcript.txt` | full 69-min transcript (whisper-turbo, local, $0) |
| `~/perkins-corpus/tim30_with_actual_prices.json` | his 30 homes + stories, pitch, accessibility, **and his ACTUAL quoted prices** |

---

## 1. What Tim settled

**The week, confirmed.** *"Five, Monday through Friday… we count work days as 20 days per month."*
And *"if it was an eight day job, you want a minimum of $5,000 built in regardless, right?" —
"Yeah, pretty much."* What shipped this morning is right. **$4,000 is dead**: $2,500 at any size.

**Miami's overhead, answered by his own arithmetic.** *"My branch is like 28 grand, for their branch
is like 85 grand, and we just divide that by 20 work days."*
Jupiter $28,000/20 = **$1,400/day** (exactly our config). Miami = **$4,250/day**. Naples unstated.

**⚠️ The per-square profit scale is to be deleted.** *"That profit thing per square is an old thing I
used to use before I really nailed it down… let's not have duplicate mechanisms. I would just
eliminate it… $2,500 minimum and then use the sliding scale to figure out your percent."*
Profit becomes **operator percentage + $2,500 floor**. This also makes the 20-square band question
moot. **Jarvis #432.**

**⚠️ A defect in what shipped this morning.** *"The PM incentive is not something the customer ever
needs to see… we usually don't want to show them any of the back-end stuff."* Customer mode folds
base + overhead + profit but still prints `PM Incentive` as its own row. **Jarvis #433.**

**Repairs return cost with no profit** — he caught it live: 1 day, 1 man, $500 materials printed
**$1,685** ($1,185 + $500). Needs a profit slider, **$250 minimum profit, $500 minimum service
call**. Maintenance prices identically — relabel "Repair / Maintenance", one path. **Jarvis #434.**

**Accessibility has no fixed price** (email 20:36): *"just manual inputs for additional labor and
delivery. There isn't a set price, it all depends on SF in the area and what the delivery company or
subs will charge for handloading and/or hand-demo."* So it is a **manual $ field, not a tier**.

**His four asks** (email 20:24): accessibility input box · **Resi/Commercial button** · crane flag
for **>2.5 stories** · waterfront/salinity gate for Coastal. **Jarvis #437.** He also offered
**another 20 houses** if it would help.

---

## 2. First validation against his REAL prices

His new sheet carries actual quoted prices on 27 of 30. Engine vs his numbers, 21 like-for-like,
flat sections included:

| profit floor | median | within 5% | within 10% |
|---|--:|--:|--:|
| **weekly (shipped today)** | **+1.0%** | **12/21** | **18/21** |
| flat $2,500 (yesterday) | −0.1% | 10/21 | 17/21 |

**This morning's change moved us toward his real prices.** The 2.6% uplift was not drift.

Worst remaining: 15739 136th Terrace N **+$7,670** and 13020 152nd Rd **+$5,785** (we quote high);
1081 Fairview **−$5,714** and 451 South Juno **−$5,290** (both metal, we quote low).

⚠️ **Excel ate his pitch column as DATES.** `4/12` is stored as `2026-04-12` — the **month** is the
rise. Never read it as a number.

---

## 3. Still open

**Blocks a quote:** flat-roof plywood deck $/sq — the only one.
**Unanswered:** which price book is live · dumpster threshold (15/30/17.5) · per-person commission
rates and whether the % is of profit or contract · silicone $445/515/645 vs +$25/coat · coating
under 25 sq with tear-off · stucco metal $9/LF vs $9/10LF · Naples overhead · all of commercial ·
1141 Vintner's RoofR PDF · any 7/12+ roof. **Jarvis #441.**

**R2 never ran** (#440). Both subagents idled without reporting. I verified by hand: floor
boundaries (5.0→1wk, 5.5→2wk, no zero floor), customer-mode margin leak across four roof types
including mixed (clean), and CV leakage (0 of 29 folds saw their own target, so **83% is honest**).
**Not** done: the test-sabotage audit, and checking `docs/PRICING_RULES.md` against the shipped
config — **that PDF is in Tim's hands**, so any mismatch is client-facing.

---

## 4. Plan, ranked

1. **#432** profit model → percentage + $2,500 floor; retire the band table (keep it readable for
   old proposals).
2. **#433** fold PM incentive out of the customer view + a test that no back-end key survives.
3. **#434** repair profit slider, $250/$500 minimums, "Repair / Maintenance".
4. **#437** the four inputs — accessibility as a manual $, Resi/Commercial, crane >2.5 storeys,
   coastal gate.
5. **#436** refit the day model on stories + pitch + accessibility, measure against his 27 actual
   prices, target his 95%.
6. **#435** seed Miami $4,250/day. **#438** test the salinity tool first. **#439** scrape Tim's
   Knowify. **#440** finish R2.

---

## 5. Gotchas

- Transcribe locally and free: `ffmpeg -ac 1 -ar 16000 -b:a 32k -f segment -segment_time 600`, then
  POST each chunk to `http://cerberus-ai:4000/v1/audio/transcriptions` with `model=whisper-turbo`.
  Key: `grep '^LITELLM_MASTER_KEY=' ~/litellm/providers.env`. 69 min cost $0 and ~4 minutes.
- **`pgrep -f "pytest tests/"` matches your own waiter shell** — an until-loop on it never exits.
  Wait on the PID. Same trap killed a `deploy.sh` waiter.
- A config change is four places: fixture, prod, tests, and any seeder that could replay it.
- Cloud SQL proxy `127.0.0.1:5432`, db **`perkins`**, user **`app`**, `set app.tenant_id='1'`.
- Graph: `$search="from:…"` works, `$filter`+`$orderby` together 400s. Attachments are additive.

**Standing archive directive:** `CONTINUATION-2026-07-25-pm.md` archived to `docs/continuations/`,
latest three kept at top level, README pointer refreshed.
