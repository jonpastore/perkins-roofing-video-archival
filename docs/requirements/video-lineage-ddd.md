# DDD: Video lineage

Status: **implemented-local**

## Domain
- **Parent** = the long original (`derived_urls` lives here).
- **Child** = a YouTube id that is a slice. Identity is the 11-char id, not the watch URL.

## Decisions
- Store clip URLs on the parent (operator-facing) and stamp `parent_video_id` on children
  (query-facing). Both are required: enumerate may see C before anyone pastes URLs, or after.
- Skip generation; do not delete child Video rows.
