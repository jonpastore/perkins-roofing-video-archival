# Spec: Video lineage (long-form → chopped clips)

Status: **implemented-local** (migrations applied to Cloud SQL; app code not on `origin/main`)

## Why
Sliced YouTube uploads look like new catalogue videos. Without a parent link they are
ingested, mined for topics/FAQs, and generate duplicate articles.

## What
- Long video stores `derived_urls` (clip URLs / ids) and optional `longform_*` bookkeeping.
- Children get `parent_video_id`. Ingest, topic aggregation, FAQ/suggestion counts skip them.
- Status long-form queue can record clip URLs against a >15 min parent.
- Under 30 min, Analyze cut recommends tighten (drop fluff) or split (topic changes).

## Non-goals
- Actually chopping or uploading clips (YouTube upload is still mock).
- Changing CompanyCam media.
