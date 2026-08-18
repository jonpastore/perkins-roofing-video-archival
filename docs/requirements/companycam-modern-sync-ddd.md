# DDD: CompanyCam modern sync

Status: **done**

## Bounded contexts
- **Fetch** (`adapters/companycam.py`): HTTP, unwrap, normalize. No DB.
- **Mirror** (`core/companycam/mirror.py`): hash-gated upsert; single writer of `tags`.
- **Orchestration** (`jobs/companycam_sync.py`): crawl then tag pass; advisory lock 8274126.
- **Ingress** (`api/routes/companycam.py`): HMAC webhook → same normalize + upsert.

## Domain
- A **publish tag** is not a CompanyCam payload field. It is the membership of an account-wide
  filtered index, stamped onto our row.
- **needs_media** is a project-timestamp comparison, not a tag signal.

## Decisions
- Application Key over user OAuth (key dies with the app, not a person).
- Fail closed on unknown tag ids (CompanyCam filter fails open).
- Tag pass upserts first (stamp-only missed 7 of 42 photos on 2026-08-18).
