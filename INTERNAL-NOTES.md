# Perkins Video Platform — INTERNAL Notes (do NOT send to client)

Companion to the client-facing `Perkins-Roofing-Proposal.md`. Jarvis project #225.

## Pricing / economics
- **Rate: $200/hr.** Single fixed-fee offer: **$8,600 build + $1,500/mo** (tiers eliminated).
- **Build timeboxed to ~43 hrs** ($8,600 ÷ $200). Hold scope to the timebox; anything beyond
  = change order at $200/hr.
- **DECIDED (2026-06-09, post-council): keep $8,600, narrow to CORE v1.** Council (Grok+GPT5)
  pegged true production v1 at ~80–140h / $12–18k and said sell the core + defer the rest.
  We're selling the core at $8,600 and rolling everything else out on the $1,500/mo service.
- **CORE v1 build ($8,600):** GCP project setup + schema; media archive (download/store full
  catalog + access UI); ingest + transcription pipeline; Content Graph; pgvector hybrid
  retriever + semantic timecoded search; grounded "Ask Tim" (citations + abstention); GCP
  deploy; backfill QA + demo. (Foundation exists in `app/`, dev-verified.)
- **Delivered/operated via the $1,500/mo retainer (NOT in the build):** FAQ bank, automated
  clip factory (title+outro), multi-platform publisher/cascade, sales-enablement clips +
  objection library, lead attribution, engagement analytics, ad-boost optimization, competitor
  intelligence, comment-bot poster (opt-in), SEO blog engine, educational series, dashboards,
  monthly reports. Rolls out over the following weeks as managed service.
- **Reality check:** $8,600 = ~43h at $200/hr but core v1 is realistically more like 55–75h →
  this is now partly relationship-priced. Acceptable to win the client; margin lives in the retainer.

## Commercial model (REVISED 2026-06-09 — dropped the $1,500/mo retainer)
- **Phase 1 — core platform: $8,600 one-time.** Deploy the core in Tim's GCP.
- **Phase 2 — feature build-out: $2,500/mo × 2 months = $5,000 (CAPEX, optional, 30–60 days
  after Phase 1).** Framed as *development capital*, not a subscription — we build the deferred
  features (FAQ, clip factory, publisher, competitor intel, engagement, ad-boost, SEO, series,
  reporting) INTO his solution; after 2 months they're his with no ongoing build fee. At $200/hr
  that's ~25 hrs total to ship the feature set — tight but acceptable to win + it's bounded.
- **Support/tuning/strategy (optional, ongoing): $1,000/mo for 5 hrs ($200/hr) OR pure hourly
  at $200/hr.** Replaces the retainer. Covers monitoring, tuning, new-content processing,
  campaign guidance, monthly strategy.
- **Cloud:** Tim pays Google directly (~$150–300/mo), no markup, not our line item.
- Total to Tim if he takes everything: $8,600 + $5,000 (2mo) + ongoing $1,000/mo support.
- Margin note: revenue front-loaded into Phase 1+2 build capital; recurring is now the lighter
  $1k/5hr support. Cleaner than open-ended managed-service scope.

## Architecture change: cerberus REMOVED
- cerberus (our RTX 5090) is OUT of the client architecture — that's our system, not theirs.
- Client gets **their own cloud compute** in their own GCP project:
  - Transcription: Google Speech-to-Text v2 (sentence+word+confidence) primary; large
    back-catalog backfill can run on a temporary GCP GPU VM (L4) to cut per-minute cost.
  - Embeddings + LLM extraction/RAG: cloud (Vertex AI / Anthropic API on their account).
  - No "free GPU offload" margin story anymore — transcription/LLM are real cloud costs,
    billed to the client directly.
- We may still use cerberus internally for our own prototyping/dev, but nothing the client
  depends on touches it.

## Open items before build
- Confirm channel ID + video count sign-off.
- Stand up client GCP account/billing.
- Record Tim's written comment-bot opt-in (ToS ack) before enabling that flag.
- Confirm whether Tim upgrades OpusClip to an API-eligible plan (else own renderer only).
- Measure actual library size/hours → firm one-time backfill transcription estimate.

## Council validation (2026-06-09, Grok-4 + GPT-5 + web)
- Core platform doable/low-risk. OpusClip API confirmed real (closed-beta, Business/large-
  annual; Pro $40-50/mo excluded; 30 req/min; Scheduler API).
- Unanimous red flag: automated competitor commenting violates YouTube ToS; human cadence +
  real-browser UA = evasion, not compliance; ban risk lands on Tim's channel. Client accepts
  knowingly → flagged-off + recorded opt-in.
- Treat YouTube-derived data as derived analysis; refresh/honor deletion; don't cache raw.
