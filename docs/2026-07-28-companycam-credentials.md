# CompanyCam credentials — issued 2026-07-28

The connector (`adapters/companycam.py`, `core/companycam/`, `jobs/companycam_sync.py`,
migration 0043) was built 2026-07-18 ahead of the account and sat inert because
`COMPANYCAM_PAT` was unset. It is now live.

## What was issued, and why it is not a PAT

CompanyCam offers two kinds of API credential under **Integrations → Access Tokens**:

| | tied to | dies when |
|---|---|---|
| Personal Access Token | the individual user who made it | that person leaves or is deactivated |
| **Application Key** | a registered OAuth application | the application is deleted |

We use an **Application Key**. A PAT here would have been bound to Charles Mejia's login, so
the integration would break the day that account changes — a foreseeable outage for something
the proposal and website pipelines depend on.

**Registered application** — `Perkins Platform (DeGenito)`, id **16351**:

- Permissions: **Read & Write**, deliberately *not* Full access. We pull photos/videos, and the
  roadmap includes creating CompanyCam projects from sold jobs; nothing needs **delete**.
- Confidential client (a client secret is required for code exchange).
- Redirect URI `https://api-jnr6bsxyea-uc.a.run.app/oauth/companycam/callback`, following the
  existing `{OAUTH_REDIRECT_BASE}/oauth/{platform}/callback` convention. Unused today — we call
  with a bearer token, not the authorization-code flow.

**Application key** — `perkins-platform-prod`, **no expiration**. That is a deliberate
trade-off: there is no key-rotation automation, so a 7/30/60/90-day key would expire silently
and break the sync job with nothing watching for it. Rotate by hand (see below) if the key is
ever exposed.

## Where the values live

| secret | holds | injected as |
|---|---|---|
| `companycam-pat` | the **application key** | `COMPANYCAM_PAT` (`scripts/deploy.sh`) |
| `companycam-client-id` | OAuth app client id | not injected |
| `companycam-client-secret` | OAuth app client secret | not injected |
| `companycam-webhook-secret` | — **still empty** | not injected |

⚠️ **The container name `companycam-pat` is now a misnomer** — it holds an application key. GCP
secrets cannot be renamed, and the env var is referenced in `deploy.sh` and
`adapters/companycam.py`, so the name stays and this note exists so nobody rotating it goes
looking for a PAT in the UI. It is under **Application Keys**, not Personal Access Tokens.

`companycam-webhook-secret` is intentionally NOT wired into `--set-secrets`: it has no version,
and a versionless secret in `--set-secrets` fails *every* deploy, including unrelated ones.

## The webhook signature — corrected 2026-08-02, before it was ever used

`api/routes/companycam.py` was written ahead of the account against an assumed scheme, and both
halves of the assumption were wrong. A real event would have been rejected 100% of the time, and
the tests passed because they signed the same wrong way the route verified.

| | assumed | actual ([docs](https://docs.companycam.com/docs/webhooks-1)) |
|---|---|---|
| algorithm | HMAC-**SHA256**, hex | HMAC-**SHA1**, **base64** |
| header | `X-CompanyCam-Signature` | `X-CompanyCam-Signature` ✓ |
| event key | `type` | `event_type` |
| envelope | `{type, payload}` | `{event_type, created_at, payload, webhook_id}` |

**The HMAC key is not a secret CompanyCam issues us.** It is the `token` parameter *we* supply
when calling their create-webhook endpoint. So wiring this up is: generate a value → store it as
a version of `companycam-webhook-secret` → pass that same value as `token` when registering the
webhook → add the secret to `--set-secrets` in `scripts/deploy.sh`. Storing a value CompanyCam
never saw would 401 every event, with a signature mismatch as the only symptom.

Replay protection uses the envelope's `created_at` (±5 min), not a header — CompanyCam sends no
timestamp header, and `created_at` is inside the signed body so it cannot be re-stamped by
whoever captured the request. An event without it is rejected.

Event names are lowercase-dotted (`photo.created`, `photo.updated`, `video.created`, …); the
route mirrors `photo.*` and `video.*` and acks everything else without a write.

All four containers are declared in `infra/main.tf` `local.secret_ids`. The two new ones were
created out-of-band and then `terraform import`ed, so state matches git (R3).

## Verified live

```
GET /v2/projects?per_page=3               200   (3 real projects)
GET /v2/projects/{id}/photos?per_page=1   200
GET /v2/projects/{id}/videos?per_page=1   200
```

**Videos are a separate v2 resource** — a project's clips do NOT come back from `/photos`.
`core/companycam/rest.videos_url` and `adapters/companycam.list_videos` were added for it. The
payload differs from a photo's: `playback_url` + `thumbnail_urls{large,medium,small}` rather
than `uris[{type,uri}]`, and epoch-int timestamps.

⚠️ A video/photo carries an **`internal`** flag. Crews mark media internal-only; anything
internal must never reach a proposal or a public project page. `normalize_video` carries it
through and callers must filter on it.

## Rotating

1. app.companycam.com → Integrations → **Access Tokens** → Application Keys
2. New Application Key against application *Perkins Platform (DeGenito)*, Read & Write, no expiry
3. The value is shown **once**. It is also recoverable afterwards via the row's copy button —
   the list only *displays* it masked (`3yYP……UM48`).
4. `gcloud secrets versions add companycam-pat --data-file=-`
5. Redeploy so Cloud Run picks up `:latest`.

Login credentials are in Jon's **family** 1Password account (`jpastore79@gmail.com`), Private
vault, items *Perkins CompanyCam* / *companycam.com - perkinsroofing.net* — not the DeGenito
account, and not the Perkins Roofing vault (which holds only a YouTube key).
