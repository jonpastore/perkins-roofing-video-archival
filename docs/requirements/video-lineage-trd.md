# TRD: Video lineage

Status: **implemented-local**

## Data model
- `videos.longform_reprocessed_at`, `videos.longform_note` (0062).
- `videos.parent_video_id`, `videos.derived_urls JSONB default []` (0063).
- ORM: `app.models.Video`.

## Interfaces
- `core.video_lineage.youtube_id_from_url` / `ids_from_urls` / `attach_derived_urls` /
  `derived_ids_from_db` / `parent_index_from_db`.
- `POST /archive/...` longform-reprocessed + derived_urls (see `api/routes/archive.py`).
- `GET /archive/{id}/edit-plan` — `core.edit_plan.plan` on segments + topic stamps.
- Status queue uses `min_length=900` (15 min).
- Skip `parent_video_id` in `app/ingest.py`, `jobs/ingest_worker.py`,
  `jobs/aggregate_topics.py`, `core/suggestion_counts.py`, `api/routes/topics.py`.
- `jobs/enumerate_channel.py` stamps parent when a listed child appears.

## Tests
- `tests/core/test_video_lineage.py` — id parse, attach, skip-set.
- `tests/api/test_archive_kpis.py` — longform endpoint.
- Must fail if a parented video is counted as a topic/FAQ source.
