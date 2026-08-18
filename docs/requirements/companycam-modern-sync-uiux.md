# UI/UX: CompanyCam modern sync

Status: **done**

## Surfaces
- Status → Data sources → CompanyCam: badge only. No Log in. No Request login.
  Help: Application Key in `companycam-pat`; rotate under Connections.
- Connections: `oauth: false`, `secret_reenter: true` for the Application Key.
- Portfolio: gallery still reads `companycam_photos.tags` / `companycam_videos.tags`.

## States
- Healthy: probe `ping` 200.
- Broken: nightly job red (OOM/URLError) — not a missing login.
- Unconfigured: `COMPANYCAM_PAT` unset (should not happen in prod).

## Copy
Do not tell anyone to “log in to CompanyCam.” That path is gone on purpose.
