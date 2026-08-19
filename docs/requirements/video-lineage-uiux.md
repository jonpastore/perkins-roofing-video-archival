# UI/UX: Video lineage

Status: **implemented-local** (Status.tsx long-form queue is uncommitted)

## Surfaces
- Status long-form queue: list >15 min videos; Analyze cut (tighten vs split vs chop);
  textarea for clip URLs; mark reprocessed.
- Archive KPIs expose `longform-reprocessed` + `derived_urls`.

## Copy
Clip URLs join to the longer video so sliced uploads do not spawn duplicate articles.
