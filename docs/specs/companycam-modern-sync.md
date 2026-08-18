# Spec: CompanyCam modern sync

Status: **done** (shipped `966657e` + `17b67a9`, live tag pass verified 2026-08-18)

## Why
Legacy `https://api.companycam.com/v2` sunsets 2027-09-01. The 06:00 job OOMed while
stamping publish tags (full ORM `raw` JSON) and left the public gallery empty. Browser
OAuth overwrote the never-expire Application Key with a 2-hour token.

## What
- Adapter + rest constants speak `public_api/v1` (`limit`/`after`, `{data,errors,meta}`).
- Account-wide tag pass upserts tagged media then stamps `companycam_photos.tags` /
  `companycam_videos.tags`. Publish tags are not read from photo payloads (they have none).
- Credential is Application Key in Secret Manager `companycam-pat` (`COMPANYCAM_PAT`).
  There is no user OAuth. `/oauth/companycam/start` is 404.
- Webhook 266201 stays; HMAC-SHA1+base64; ISO `created_at` accepted.

## Users
Nightly `companycam-sync` job; Portfolio curator; Status health probe.

## Constraints
- Unknown `tag_ids` fail open at CompanyCam — validate ids via `GET /tags` before write.
- Do not load `raw` JSONB for the tag pass (OOM).
- Do not click CompanyCam “Log in” (route removed).

## Non-goals
- Uploading media to CompanyCam.
- Destroying unused GSM `companycam-client-id` / `companycam-tokens` (Terraform still owns them).
