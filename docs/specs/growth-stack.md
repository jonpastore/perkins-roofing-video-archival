# Spec: Perkins growth stack

Status: **accepted-direction** (Tim meeting 2026-08-20). YouTube peer: [@AastroRoofing](https://www.youtube.com/@AastroRoofing) (Boca, same years/~860 videos, 3.87M subs via Shorts).

## Why
WebPower ($2,295/mo) goes away. This app is already the factory (video, articles, clips, quotes). The public site becomes Astro on Cloudflare. Paid media is per-branch. Tim’s YouTube is the organic engine. Nothing ships as a content mill.

## Users
- Tim — owner, YouTube face, answers comments and PAA by hand
- Amber — marketing manager, GHL/Maria, GBP
- Marco / Josh / Chris — office principals, own ad cards
- Jon — runs the factory, SEM engine, Astro

## What
One stack: factory (this repo) → Astro → GHL + CallRail → shown appointment. Paid: Google + Bing + Meta retarget + PearlDiver match + ChatGPT Ads test. Organic: Topic Graph cadence, Shorts from existing heat, Tim inbox.

## Constraints
- Each branch pays media. $4,500 setup+creative already paid. $200/office AI SEM.
- No Rank Math. Our scorer + JSON-LD in Astro.
- Enhance Tim’s engagement; do not bot YouTube.
- PearlDiver = ads audiences, not cold SMS (FL FIPA/TCPA).
- CONTENT_GEN stays `dump` at 1 pillar/day drafts unless flipped off.
- Surface the graph: Opportunity / Heat / Coverage chips everywhere a content decision is made.
- Package Shorts like Aastro: 15–40s, town + problem in 3s and title, phone in description, one audience.

## Non-goals
- Call center / UMMG
- AdRoll as the first retarget layer
- 50% corpus dump
- WordPress cutover without Tim’s written go
- Building a second ads brain (Bing uses the existing SEM engine)
