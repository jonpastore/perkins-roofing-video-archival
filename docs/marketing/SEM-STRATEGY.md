# Perkins SEM / SEO / AIO / social — who, where, spend

Status: draft for the Tim meeting (due 2026-08-20). Sources: `DeGenito-Perkins-Partnership-Proposal-2026-08.pdf`, Tim/Amber/Marco mail on jon@degenito.ai, live `core.seo` + `core.article_criteria`, DeGenito Ads API (`degenito/seo-aio`, MCC 176-468-2400), and the marketing-flow diagram Jon attached.

This is not a content mill plan. Ads land on Astro service/branch pages. Articles exist to earn citations and feed those pages.

## Targeting Tim already said

| Who | Where he said it | What to do |
|---|---|---|
| Tim | Proposal App. A (Aug 10) | **Broward first**: Weston, Coral Springs, SW Ranches, Davie, Ft Lauderdale east of US-1, Wilton Manors. Miami-Dade waits. |
| Tim | Proposal §5 | A/B **brand vs metal**. Each office's own ad card. We do not hold spend. |
| Tim | 2026-07-30 email (portfolio / Wendy) | Use **area / town / city / HOA** names to boost Maps. He already does this in videos. |
| Tim | Same thread | Every project has client permission in the contract. |
| Tim | Pricing mail Jul–Aug | Mid-premium. Not cheapest. Margin of error on quotes still bothers him — marketing must not sell "cheap and fast." |
| Amber | Signature + Aug 18 | Marketing Manager. Jupiter + Miami addresses. Include her on campaign copy and GBP. |
| Marco / Josh / Chris | Proposal + Aug 18 review thread | Office principals: Jupiter (Tim), Miami (Marco/Josh), Naples opening (Chris). **One company invoice** — do not bill offices. |

## Decided 2026-08-19 evening (Jon) — Thursday surprise

Commercial sheet: `DeGenito-Perkins-Marketing-Management-2026-08.pdf`. Bring it with the 15 August partnership. **Do not amend the emailed partnership PDF.**

- **$1,000 / mo Marketing Management, one company invoice.** New addendum. Does not replace anything already emailed.
- **$200 / mo / branch AI SEM stays exactly as the partnership** (three-office subtotal $600). That is the engine IP. Do not convert it to /company. Do not fold it into the $1,000.
- **Socials stay inside $999.** This repo already runs them. Desk does not rebill posting.
- **$799 factory stays.** Pages feed ChatGPT/Maps citations; desk buys the paid seats.
- **DeGenito FB campaign = $100 / shown.** Already in the partnership. Separate from the $1,000.
- **Graduated spend, first ads ever.** Google + Bing low, then **$30–50 / day** reel boosts (IG/TT/YT/FB). Target 3–5 shown/wk is year-one exit, not week one, not Christmas week.
- **Seasonal media + growth.** Y1 Dec trough ~$900–$1,200. Y2 media $70–95k only if a second market is earned (PE-aware Miami CPC). Do not write a no-growth calendar.
- **Five-year sellable plan.** 15–25% more shown/year, gated on crew. Buyer multiple 3× founder vs 5.5–8× owner-light systems. PE 6–9× only at $3M+ EBITDA.
- **Prioritize ChatGPT Ads + GBP/Maps.** People ask AI who to hire. Apply ChatGPT week one (verification queue).
- **Analytics / A/B / Friday report live in this app.** One tool. Customer for life.
- **No percent of spend.** Agency 10–20% incentivizes the budget (and a loud December), not the chair.

## Decided 2026-08-19 (Jon)

- **$4,500** is DeGenito's campaign-setup + ad-creative fee (already paid). Media on the **company** card (not a card per office). GHL is already stood up.
- **UMMG** is out. Do not put it on the Perkins flow.
- **PearlDiver** is in: identify site visitors so we can retarget. Pixel on Astro + SEM landers. Lists go to Customer Match / Meta / GHL — not cold-call.
- **Datavalidator** is in: skip-trace / address hygiene before direct mail and install-neighborhood drops.
- **Meta ads** we configure (not a product configurator).
- **Doorhangers / canvasser / A-frame** happen **during install**, around the sold job — QR to the branch lander.
- **Varro** is optional: introduce for appointment insights. No call-center pitch.
- **QA flip** = appointment follow-up. Automate GHL so Maria's dash stays clean.
- **ChatGPT Ads** = apply and test (self-serve is open to US businesses as of May 2026).
- **Bing / Microsoft Ads** = yes, cheap, import Google campaigns. Extend the SEM engine; do not build a second brain.
- **AdRoll** = optional third display layer. Native Google remarketing + Meta retargeting first so we are not paying a reseller to bid against ourselves.

## Who owns what

| Motion | Owner | Where it lives | Spend |
|---|---|---|---|
| Public site (Astro, Cloudflare) | Jon / DeGenito | New repo (not this one). Staging first: `staging.perkinsroofing.net`. Cutover only on Tim's written go. | $0 in the proposal (gift). CF free until volume. |
| Content factory (articles, FAQ, clips, archive) | This app | `app.perkinsroofing.net` → publishes **to Astro**, not WordPress | Inside $999/mo app mgmt |
| Article cadence | Jon flips; Tim reviews drafts | Platform Settings `CONTENT_GEN_MODE` = `dump` \| `off`. Cron 09:10 CT. Persist **drafts only**. | Vertex, already on GCP card |
| SEO / AIO scoring | Our tool, not Rank Math | `core/seo.py`, `core/article_criteria.py`, `core/jsonld.py`. Astro renders JSON-LD in the page. | Inside $799/mo SEO/AIO |
| Semrush (we manage, they pay list) | Jon | Semrush Starter | $199/mo ($165.17 annual) |
| AI SEM (partnership, unchanged) | DeGenito Ads / seo-aio SEM engine | MCC `176-468-2400`. | **$200 / mo / branch** as emailed. |
| Marketing Management — ChatGPT + Maps + boosts + seasonal/growth caps + reporting | This app | app.perkinsroofing.net | **$1,000 / mo, one company.** New addendum. |
| Shown appointments — Meta/social | Apex / GHL | FB (then IG/YT/TT) we drive. He pays boost/media. | **$100 / show** to the office that received it. |
| Microsoft Ads (Bing) | Same SEM engine | Import Google Search campaigns, Broward geo, 10–15% of Google budget to start | Their cards. CPC often 30–50% under Google on roofing. |
| ChatGPT Ads | Jon applies at ads.openai.com | Conversational intent tests. Same Astro landers. | Their cards. $10–20/day test after verification. |
| PearlDiver | Jon (agency plan) | Pixel on Astro + landers. ~25% of humans resolved (their claim). Filter bots. | DeGenito tool cost, not Perkins media. |
| Meta retargeting | Same $4,500 creative | Site visitors + PearlDiver Customer Match. Before/after, crew, HOA-finished. | Their cards. |
| Google remarketing | Same | Display + RLSA on search. First retarget layer. | Their cards. |
| AdRoll | Only if Google+Meta leave unused frequency | Do not double-bid the same visitor. | Optional. |
| Datavalidator | Direct mail / doorhanger lists | Hygiene before mail. Install-neighborhood only. | Per drop. |
| GHL / Maria | Amber + Jon | Automate set / confirm / QA-flip / no-show. Varro optional for insights. | Included with campaigns. |
| Shown appointments | Apex / GHL | `crm.perkinsroofing.net` | $100 / show to the office that received it |
| YouTube | Tim (owner login) | `@perkinsroofingcorp` · ~3.3k subs · ~877 videos | $0 media. Needs Tim OAuth in ~2 days. |
| Clip Studio → social | This app | Tokens still empty (#319) until Tim/Amber grant | $0 until tokens exist |
| CallRail | Perkins pays | Number pool per branch | ~$170–$345/mo |
| GBP / citations | Amber + Jon | Jupiter + Miami listings. Naples when Chris is live. | Inside $799 |
| Reviews after job close | GHL drip → Reviews | Flow diagram "Project Close Drip" | $0 extra if GHL already included |

## Paid campaigns to feed the AI Ads system

Create **per geo** on the **one company** Google Ads account. Do not share one campaign across Jupiter and Miami. Do not open a second billing file.

### Campaign 1 — Brand (exact)

- Keywords: `perkins roofing`, `perkins roofing jupiter`, `perkins roofing miami`, misspellings.
- Land: branch page (`/jupiter/`, `/miami/`), not the blog.
- Bid: exact. Protect the name from scavenger ads.
- Budget start: **$15–25/day** per live office.

### Campaign 2 — Metal (the A/B)

- Keywords: `standing seam metal roof {city}`, `metal roof replacement {city}`, `metal roof cost florida`, `salt air metal roof`.
- Negatives: DIY, jobs, salary, scrap, "how to install yourself", cheapest, coupon.
- Land: `/metal-roofing-company/` plus a **Broward metal** Astro lander (new).
- Budget start: **$40–60/day** Broward-only geos listed above.

### Campaign 3 — Repair / leak (high intent)

- Keywords: `roof leak {city}`, `emergency roof repair {city}`, `tile roof leak florida`.
- Land: `/roof-repair-services/` with click-to-call + photo upload.
- Schedule: storm windows heavier. CallRail dynamic number.
- Budget start: **$30–50/day**.

### Campaign 4 — Insurance / storm (seasonal)

- Keywords: `hurricane roof insurance claim florida`, `wind mitigation roof inspection`.
- Land: a single honest checklist page (not "we get you paid").
- Pause off-season. Do not claim outcomes.

### Do not launch yet

- Display / YouTube pre-roll (burns the $4,500 credit without shown-appointment proof).
- Competitor conquest (`advanced roofing`, `crowther`) until brand + metal have 30 days of CPA.
- Miami-Dade geos until Broward metal A/B has a winner.
- PMax until CallRail + GHL conversion import is clean (otherwise the AI optimizer chases junk).

### Feed the Ads AI (seo-aio SEM engine)

Send it these constraints, not a blank "maximize conversions":

1. Geo allow-list = the Broward set. Bid 0 elsewhere.
2. Conversion = **CallRail answered call ≥ 60s** or **GHL appointment set**, not a pageview.
3. Target CPA start: **$180–250** for a shown estimate (they already accepted $100/show to us; media CPA must sit under a sold-job margin).
4. RSA assets: license CCC1331944, 1980, Tim on camera, metal vs tile, HOA-friendly. No "cheapest."
5. Sitelines: Metal · Tile · Repair · Insurance inspection · Free estimate.
6. Call asset on. Lead form only if quality holds for 14 days.
7. Daily cap on the company account (per-geo budgets inside it). We never hold the card.

**Recommended first-90-day media spend (their cards, not ours):** Broward metal + repair **$3.5k–$5k/mo** on one office (Miami brand-only $500–800/mo to defend the name). Naples: GBP + 2 proof pages, **$0 ads** until Chris has a number pool.

## Organic / AIO (the $799)

- One URL per entity. Topic Graph + keyword coverage already skip synonyms.
- Cadence: leave `CONTENT_GEN_MODE=dump` at **1 pillar + ≤2 clusters / day**, drafts only. That *is* working with what we have. Do not 50% dump.
- Publish to Astro after Tim/Amber spot-check. Hidden AIO corpus (~50%) is in the proposal — those pages exist for citation, slim chrome, deep body.
- `llms.txt` + FAQPage + VideoObject + one RoofingContractor `@id`. Rank Math goes away with WordPress.

## YouTube (Tim, 2-day login)

He is the channel owner. Meeting goal: he signs into the dashboard OAuth so `comments.insert` and Shorts upload stop 403ing.

Until then we can still: crawl comments, draft replies, cut shorts, score heat. We cannot post.

Measured 2026-08-19. Tim cited [@AastroRoofing](https://www.youtube.com/@AastroRoofing) (Boca Raton, CCC1330967, Broward + Palm Beach).

| Channel | Since | Subs | Videos | Views | Views / video |
|---|---|---|---|---|---|
| **Perkins Roofing Corp.** | Aug 2015 | 3.29k | 878 | 2.03M | ~2.3k |
| **Aastro Roofing** (cited) | Feb 2016 | **3.87M** | 855 | **81.1M** | ~95k |
| The Metal Roofing Channel | Nov 2017 | 51.8k | 635 | 8.57M | ~13.5k |
| Roofing Insights | Apr 2017 | 150k | 3,051 | 69.1M | ~23k |
| Bigfoot Windows & Roofing | Dec 2019 | 254 | 946 | 468k | ~495 |

Aastro is the same age and almost the same video count. The gap is **format, not volume**. Last 30 days they added ~690k subs and 10.9M views (vidIQ). That is Shorts distribution, not 3.9M Boca homeowners. Channel about: “built for roofers, contractors, and entrepreneurs.”

Their outliers: free-roof story 12.1M, community help 10.3M, silicone how-to 3.4M, “Why 96% of roofing companies fail” 2.7M. Typical Shorts: 15–40s, town + problem in the title, phone in every description, 2k–125k views.

**Do not chase 3.9M.** Steal the unit of work: cut Tim’s existing 878 talks into 45–90s with town + problem in 3 seconds, a phone/Astro CTA, and a second cut aimed at other roofers (code/HOA/foam) from the same tape. Tim answers comments by hand.

## Competitor media (held-off crawl)

On-demand 5-query Serper scan is in Opportunities ("Scan what others cover"). Full-site scrapes stay off.

First human pass (not a crawl):

| Name | Why they matter | What we score later |
|---|---|---|
| Advanced Roofing (Ft Lauderdale) | Real Broward commercial/residential competitor, YouTube + site | Service pages vs blog mill |
| Crowther Roofing & Cooling | Statewide brand, Naples overlap | Thin social vs educational |
| Gulf Coast / Englert / Metal Alliance | Tim already wants product-sheet backlinks | Cite, don't clone |
| Roofing Insights | National media, not a local bid competitor | Format only (thumbnails, series) |

Score their pages with **our** `score_article` + `aio_signals`, not Rank Math. Keep a topic only if it has a named entity we do not cover and Tim can film or write a better answer.

## This app → Astro (integration)

```
CompanyCam / YouTube / Knowify
        ↓
app.perkinsroofing.net  (factory, estimator, comments inbox)
        ↓  published rows + JSON-LD + GCS media
Astro on Cloudflare     (slim chrome, deep article/project routes, SEM landers)
        ↓  forms
crm.perkinsroofing.net (GHL) + CallRail numbers on landers
        ↓
shown appointment ($100) / sold
```

Existing WP slugs 301. Generation stays here. Rank Math does not move.

## Marketing-flow diagram — mapped 2026-08-19

Keep: lander → form → GHL → set appointment → QA-flip follow-up → confirm → run estimate → sold? → CRM. Project-close drip → reviews. CallRail on the public site.

**Paid traffic we are buying, so we retarget it:**

1. Google Search / LSAs (intent)
2. Microsoft Ads (same keywords, cheaper, older/HOA-heavy)
3. Meta (creative + retarget)
4. Google Display remarketing + RLSA (first retarget layer)
5. PearlDiver (resolve ~25% of humans; Customer Match back into 2–4)
6. ChatGPT Ads (small AIO-intent test)
7. Doorhanger QR during install (Datavalidator on the block)
8. AdRoll only if 4+5 leave unused frequency

Drop from the Perkins drawing: UMMG (dead), Coach Call Center (Varro insights only), radio/programmatic until shown-appointment CPA is known.

PearlDiver legal fence: FL FIPA + TCPA. Use resolved visitors for **ads audiences and GHL known-lead match**. Do not cold-email or SMS a homeowner who only viewed a page.
