# Perkins buildout plan — 2026-07-21 (ralplan)

**Standing rule for EVERY task below: use the local/free models first to save Claude tokens.**
- Codegen/drafts → `llm -m qwen3.6-coder` (5090) or `mcp__hermes__submit_task(model_tier="cloudflare")`.
- Article generation / long reasoning → **local `gpt-oss-120b-think`** via litellm (amd-halo), **validated by Vertex (Gemini)** in GCP. Do NOT generate articles on a cloud model — cost.
- Whisper transcription → **local faster-whisper large-v3 on the RTX 2060** (installed this session; litellm has no whisper route, cerberus GPU whisper needs sudo we don't have).
- Claude (opus) = orchestration, security wiring, final verification only. Execution → sonnet subagents.
- **Article data comes ONLY from the transcripts/KB. Invent nothing. Verify everything.**

## Status of inputs gathered 2026-07-21
- 07-20 Zoom (56 min): transcribing locally (large-v3) → `.../2026-07-20…/transcript.txt`; 422 frames extracted. **This drives "the rest of the changes" — analyze when done.**
- 07-17 Zoom: transcript.txt + 381 frames already on disk.
- `assets/UPDATED Material Prices.xlsx` = ABC/Beacon supplier raw-material cost catalog (price-book source). `assets/Lumber Schedule.pdf`.
- Tile-brand rake units confirmed (Eagle 4.82 / West Lake 4.50 / Crown 4.30 / Verea "S" 5.78 / Verea Caribbean 19.14 / Other 45).
- Gutter prices = standalone Tim list (image), in `seed_gutters_config.py`; NOT in the sheets/xlsx.

## PRIORITY ORDER (do ready-to-build BEFORE articles, per Jon)

### P0 — Estimator ready-to-build (IN PROGRESS)
1. **Tile roof-cuts wiring** — hips/valleys/rakes/wall → per-sq material. Spec in `tile-roof-cuts-pricing-linkage.md`. Executor running.
2. **Gutter downspout split** — transcript (07-17): downspout LF is a SEPARATE input; our model bundles it. Add a downspout-LF input + rate ($10.50 4×5, confirm w/ Tim). Small.
3. **Low-slope per-zone deltas** — locate the two low-slope source sheets (or derive from 07-20 frames/transcript); confirm which systems differ FBC vs HVHZ beyond polyglass ($450 vs $475).

### P1 — Analyze 07-20 Zoom → change list
4. When transcription completes: extract the concrete change requests (audio) + visual context (frames). Produce a change list, ralplan each, autopilot the safe ones. This likely reshuffles the items below.

### P2 — Content pipeline (articles) — LOCAL gen + Vertex validate
5. **Article generation loop**: `gpt-oss-120b-think` (local) generates from transcripts; **Vertex (Gemini) validates** grounding/quality; regenerate on fail. Reuse existing `core/article_*`, `core/graph.py`, grounding gates. Every article ENDS WITH: "Subscribe to our youtube channel for more!" + the YouTube channel link (UChJZpBYXOuR0j1EHJugv5hg / @perkinsroofingcorp) at the bottom.
6. **Topic mining priority**: (a) **metal roofing FIRST** (exploding demand) — prioritize render + publish; (b) consumer-protection / what-to-look-out-for; (c) then SEO/AIO-optimal order. Mine from `core/topics`, KB, transcripts.
7. **Prep-for-cutover, do NOT post to staging**: have all PILLAR articles + ≥2 CLUSTER articles/pillar rendered and queued. On prod-WP cutover: bulk upload pillars + 2 clusters each, then release **10/day (1 per each of 10 pillars)**.
8. **Model advice**: `gpt-oss-120b-think` is the right local generator for grounded roofing articles; Vertex Gemini as the validator/judge keeps compute cheap. If quality falls short, the next step UP that fits amd-halo's 125GB is limited (Kimi/GLM too big) — would need a mid-size reasoning model; flag to Jon before spending. Do NOT default to a cloud generator.

### P3 — Submission system (SEO/AIO) — from ~/projects/degenito/seo-aio
9. Build daily submission of the SITE + new ARTICLES to search engines AND AI engines, modeled on `~/projects/degenito/seo-aio` (study `article-workflow`, sitemap worker, submission code). Advise gaps in how submissions currently work — they must run DAILY and on every publish.
10. **Config toggle + dashboard notice**: an on/off config option; surface at the TOP of the dashboard with the other "off" notices (like alerting). Auto-submit after the initial release and on each publish.

### P4 — New pages / tools
11. **Metal Warranty Checker page** + convert the `https://perkins-setback.web.app/` setback tool into a **WordPress plugin** for that page. Cross-reference water salinity: USGS Water-Level & Salinity Mapper (https://www.usgs.gov/tools/water-level-and-salinity-analysis-mapper) + https://salinity.oceansciences.org/maps-overview.htm. **Brackish canals COUNT** — do not measure only from the intercoastal/ocean; cross-reference the salinity sources to classify a location as brackish/fresh.
12. **Thumbnail gallery per video**: extract candidate thumbnails per YouTube video; AI picks the most beautiful one; article image = that thumbnail (same image as the video). Each gallery thumbnail links to the video at its TIMECODE for context. Selecting an article image = choosing from this gallery. (Frame-extraction infra already prototyped this session.)
13. **Project posting UI**: post projects to the project page; auto-extract from the PROPOSAL + CompanyCam to build a project gallery with a page-per-project.

## Open items needing Tim (unchanged)
Per-branch time-based overhead numbers; gutter hangers (baked-in vs separate) + downspout rate; any FBC low-slope deltas beyond polyglass; confirm the josh_proposal T&C is current.

## Execution model
Each P-item → a sonnet executor (or Hermes/qwen for drafts), opus orchestrates + verifies. Articles/submission are the token-heavy ones → keep generation LOCAL, Vertex only for the validation pass.
