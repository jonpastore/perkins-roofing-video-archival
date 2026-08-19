# Plan: Perkins growth stack

Master plan for the Tim meeting. Spend/who/where: `docs/marketing/SEM-STRATEGY.md`.
Proposal: `DeGenito-Perkins-Partnership-Proposal-2026-08.pdf`.

## The picture

```
YouTube / CompanyCam / Knowify
        → THIS REPO (factory: score, write, clip, quote, Tim inbox)
        → published row + JSON-LD + GCS
        → Astro on Cloudflare (slim chrome, deep articles, SEM landers)
        → form / call → GHL + CallRail
        → QA-flip follow-up (Maria) → shown appointment ($100)
        → sold → project-close drip → review + doorhanger QR on the block
```

Paid traffic (their cards) hits the same landers, then PearlDiver resolves visitors back into Google/Meta Customer Match.

## Phases

### P0 — this week (meeting)
- Tim YouTube **owner** OAuth (comments.insert + Shorts). Cited peer: [@AastroRoofing](https://www.youtube.com/@AastroRoofing) — same years/video count, Shorts-driven 3.87M subs. See SEM-STRATEGY YouTube table.
- Show Topic Graph, Opportunities, competitor scan, 15-min cut plan.
- CONTENT_GEN_MODE visible On/Off (dump = on). Leave on.
- Walk Broward-first metal A/B + Bing import + ChatGPT Ads apply.

### P1 — this repo (support the stack)
Already shipped: topic graph, scored inbox, social/film queues, competitor SERP scan, edit-plan 15/30, Comments draft+two-step post.
**This wave:** daily-articles switch; Tim inbox for PAA/peer questions (same Comments surface); score a competitor page with our SEO/AIO rubric; plan docs; weekly 5-action queue; Heat-ranked Clip Studio edit-down; Aastro package gate; score chips + help on marketing surfaces.
**Next in-repo:** Astro publish adapter (replace WP REST); persist last competitor scan; lander brief from a genre; doorhanger QR payload. ffmpeg/DeepFilterNet/vid.stab for cleanup — not ComfyUI.

### P2 — not this repo
- Astro site (new CF project). Slugs 301. Rank Math dies.
- DeGenito SEM engine (`seo-aio`): Google + Microsoft Ads. MCC 176-468-2400.
- ChatGPT Ads account at ads.openai.com.
- PearlDiver pixel on Astro. Datavalidator on install-neighborhood lists.
- GHL QA-flip + Maria dash. Introduce Varro as optional insights.
- Meta ads configure (creative from Clip Studio).
- Doorhangers during install.

### P3 — after shown-appointment CPA exists
- Scale Broward metal winner.
- Naples ads only after CallRail pool.
- AdRoll only if native retarget saturates.
- Hidden AIO corpus (~50%) on Astro, one entity per URL.

## In this repo vs not

| Work | Here? | Status |
|---|---|---|
| Topic Graph / Opportunities / genres | Yes | Shipped |
| Daily article dump, keyword coverage, drafts only | Yes | Shipped; switch this wave |
| Cut for social / film next / 15-min edit plan | Yes | Shipped |
| Competitor SERP scan (5 FL queries) | Yes | Shipped |
| Score competitor HTML with our rubric | Yes | This wave |
| Tim inbox: YT + PAA + peer (draft, not bot) | Yes | This wave (reuse `comment_drafts`) |
| YouTube OAuth / Shorts upload | Yes | Waiting on Tim login |
| Clip Studio → social tokens | Yes | #319 empty until grant |
| Astro publish (JSON-LD in page, GCS media) | Yes, later | WP adapter today |
| SEM landers (Astro routes) | Content from here; pages in Astro | P2 |
| Google/Bing/ChatGPT/Meta ads | seo-aio + Ads Manager | P2 |
| PearlDiver / Datavalidator / GHL / Varro | External | P2 |
| Public site chrome | Astro | P2 |

## Risks / rollback
- Dump left on generates drafts only — unpublishable until someone promotes. Rollback = flip switch Off.
- PearlDiver misuse (cold SMS) is a legal problem — never wire phones from the identity graph into this app.
- Astro publish must 301 old slugs; do not index staging.
- Two retarget platforms bidding the same visitor wastes their card — native first.

## Rollback
CONTENT_GEN Off. Competitor scan is on-demand. Inbox rows are `comment_drafts` (dismissible). No schema migrate in this wave if we reuse that table.
