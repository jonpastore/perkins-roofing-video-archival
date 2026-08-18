# PRD: CompanyCam modern sync

Status: **done**

## Product requirements
- Public project galleries show only crew-tagged “Projects” photos and “ProjectsVideo” clips.
- Nightly sync stays incremental (thousands of finished roofs must not recrawl).
- Tagging a photo on a finished roof appears in the gallery on the next run without a
  project `updated_at` change.
- Operators rotate the Application Key under Connections; they never OAuth-login.

## User stories
- As the nightly job, I pull new media and restamp publish tags without OOMing.
- As a curator, I see the 42/10 live tagged items, not 157k tear-off frames.
- As an operator, I cannot overwrite the Application Key from the dashboard.

## Acceptance
- Live `public_api/v1` tagged set == mirrored tagged rows (measured 2026-08-18: 42 photos, 10 videos).
- Health probe uses `ping(limit=1)`, not `list_projects()`.
- Image `17b67a9` on API + `companycam-sync`.
