# TRD: CompanyCam modern sync

Status: **done**

## Interfaces
- Base: `https://api.companycam.com/public_api/v1` (`core/companycam/rest.py`).
- Lists: `limit` + `after`. Envelope `{data, errors, meta.has_next, meta.next_cursor}`.
- Tag filter: `tag_ids[]=` (modern also accepts `tag_ids=`). `tag_id=` 404/400.
- Auth: `Authorization: Bearer` Application Key from `core.companycam.tokens.load_bearer`
  (env `COMPANYCAM_PAT` or GSM `companycam-pat`).
- Webhook: `POST /companycam/webhook`, `X-CompanyCam-Signature` = base64(HMAC-SHA1(body)).
  `created_at` is unix seconds **or** ISO-8601.
- Connections: `companycam` is **not** in `PROVIDERS`. `SECRET_TARGETS["companycam"]` =
  `companycam-pat` (rotate key only).

## Data model
- `companycam_projects` incremental via `remote_updated_at` vs `media_synced_at`.
- `companycam_photos` / `companycam_videos`: hash-gated upsert; `tags` owned solely by
  `set_publish_tags`. Publish tag ids: `26926152` (Projects), `26926154` (ProjectsVideo),
  overridable via `COMPANYCAM_PROJECTS_TAG_ID` / `COMPANYCAM_PROJECTS_VIDEO_TAG_ID`.

## Test requirements (TDD)
- Cursor pagination, ISO timestamps, 404-on-subresource = empty.
- Tag filter spelling + account-wide URL + stamp-only-on-tagged-ids + upsert of never-crawled tagged media.
- `/oauth/companycam/start` → 404. `persist_companycam` / `save_oauth` do not exist.
- Live I/O: ping + tagged-id set equals DB (behavioral, not coverage).
