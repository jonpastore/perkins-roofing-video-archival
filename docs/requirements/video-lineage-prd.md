# PRD: Video lineage

Status: **implemented-local**

## Requirements
- A long video that has been chopped must not produce a second article/FAQ cluster from each clip.
- Operators can paste clip URLs on the Status long-form queue and join them to the parent.
- The >15 min work list must not re-offer a parent already marked reprocessed.
- Videos under 30 min get a tighten-vs-split edit plan from the transcript.

## Acceptance
- Given parent P and clip C in `derived_urls` (or `C.parent_video_id = P`): C is absent from
  ingest, topic aggregation, and suggestion counts.
- Idempotent: attaching the same URL twice does not duplicate `derived_urls`.
