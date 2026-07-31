# CONTINUATION 2026-07-29 — the video pipeline runs end to end, and "live" has meant STAGING

**HEAD `3665020`**, pushed, CI + deploy green. **Deployed `platform:3665020`.**
Prod configs jupiter v27 / miami v29 / naples v27. Terraform applied, drift gate clean.

---

## 0. Read these first

| | |
|---|---|
| `docs/2026-07-28-companycam-credentials.md` | CompanyCam is LIVE; why it's an application key, not a PAT |
| `core/wireproxy.py` | why yt-dlp goes through a userspace tunnel, with the measured exit-IP evidence |
| `.claude/skills/verify-reproducible-from-git` | now covers the IMAGE, not just deploy inputs — it missed twice today |

---

## 1. ⚠️ THE FINDING THAT OUTRANKS EVERYTHING: we publish to STAGING

`PlatformConfig.WP_URL = https://1228404.us6.myftpupload.com`, read from the prod DB.
`adapters/wordpress.resolved_wp_url()` reads that key and has **no .env fallback**, so it is
the single source of truth for every WordPress call the platform makes.

| | prod `perkinsroofing.net` | staging |
|---|---|---|
| newest post | **2026-07-02** | **2026-07-24** (`26-gauge-metal-panels` — the article Wendy critiqued) |
| published posts | 120 | 232 |
| vaulted app password | `401 rest_not_logged_in` | `200`, role **administrator** |

`docs/PRODUCTION_CUTOVER_PLAN.md:44` ("PROD WP Application Password generated + vaulted") is
still unchecked. So the 112/112 Wendy-verified posts, the 375 compliant rows and the 99-article
run are all **staging** artifacts. Nothing is wrong with the work — but every doc (and my own
summaries) saying "verified on the LIVE site" means staging. **Prod WP has had no platform
content since 2026-07-02.**

Cutover is a prod WP application password + one `PlatformConfig.WP_URL` change. Until then every
content improvement is invisible to Perkins' actual customers.

## 2. The video pipeline now runs end to end — PROVEN, not inferred

Four jobs existed as scripts nothing ever ran. Each was a separate silent failure:

| job | was | now |
|---|---|---|
| `enumerate-channel` | written, never scheduled | Cloud Run job + 07:00 ET scheduler, newest 60/tab |
| `backfill_metadata` | unbounded, manual | chained after enumerate; only rows missing dates |
| `archive` | written, never scheduled | Cloud Run job + 07:30 ET, shortest-first, `ARCHIVE_BATCH=5` |
| ingest | fine | unblocked (it was gated on `archive_uri`) |

Catalog went **841 → 856** (the 15 missing uploads, newest was 25 days stale) and
`archive_uri` is filling from Cloud Run — verified with real objects:

```
kR1yVOSf8mE  gs://video-archival-and-content-gen-media/videos/kR1yVOSf8mE.mp4
Q-sCLrtAFgw  gs://video-archival-and-content-gen-media/videos/Q-sCLrtAFgw.mp4
```

### Why archive needs a tunnel (do not undo this)

YouTube **bot-blocks datacenter egress**. From Cloud Run every download failed 15/15. Cookies do
NOT help — measured with the channel-owner jar verified loaded (`using cookie jar ... 6791
bytes`) and still 15/15 blocked. It is the IP, not the identity.

Kernel WireGuard needs TUN + `NET_ADMIN`, which Cloud Run does not grant. **wireproxy** runs
WireGuard in userspace and exposes SOCKS5 — no privileges at all. Measured exits:

```
185.159.158.164 -> 149.102.228.71   blocked 5/5
185.159.158.153 -> 79.127.160.162   ok 3/3
185.159.158.81  -> 79.127.136.197   ok 3/3
```

A blocked exit is **sticky per config** — reconnecting one config returns the same blocked IP
every time. So retrying is useless and rotating configs is the whole strategy; `adapters/yt_dlp`
rotates on bot-block only (a removed video fails on every exit, so rotating would burn the 2h
timeout). Exhaustion RAISES — never fall back to a direct connection, which looks fine on a
residential dev box and is permanently blocked in prod.

**VPN ranges get blocked over time.** When archive starts failing with "all N egress config(s)
exhausted", refresh the `wireguard-configs` secret with new Proton server configs — that is
maintenance, not a bug. `scripts/extract_youtube_cookies.py` has the sibling pattern for cookies.

⚠️ No VM was needed. `compute.googleapis.com` is still disabled and the stack is still entirely
serverless. If a VM is ever wanted, enabling GCE is `local.required_apis` in `infra/main.tf` +
apply — not a console click.

## 3. CompanyCam is LIVE

Application key (NOT a PAT — a PAT dies with the individual user), tied to registered OAuth app
**Perkins Platform (DeGenito)** id 16351, Read & Write, no expiry. Verified: `/v2/projects`,
`/projects/{id}/photos`, `/projects/{id}/videos` all 200, and `COMPANYCAM_PAT` is wired into the
deployed API. **Videos are a separate v2 resource** from photos — `list_videos` added.
⚠️ Media carries an `internal` flag; internal media must never reach a proposal or public page.

## 4. Portfolio — 9 real projects, and our publisher points at the wrong type

Perkins publishes projects as **pages under `/portfolio/`** (parent id 2358, 9 of them, May 2023).
`adapters/wordpress.publish_portfolio_post` targets the **`avada_portfolio` CPT**, which holds
**13 drafts — all ours**, created 2026-07-22 by `scripts/portfolio_publish.py`, with
`featured_media: 0` and `portfolio_category: []`. So the generated portfolio and the public one
are in different URL spaces and nobody has reconciled them.

Audit of the 9 live pages: **0/9 have JSON-LD, 0/9 embed video, 0/9 link to any service or
location page** (Sunny Isles' own city page exists and is unlinked); each has exactly 4 images
sharing ONE templated alt. That is the improvement surface.

**Blocked on Wendy** — a draft is sitting **unsent** in Jon's DeGenito Outlook asking which URL
space to use and whether she has a schema/requirements for project write-ups.
Wendy = `wendy@webpowermarketing.com` (external agency).

## 5. Articles: 474/474 compliant

The 4 clusters failing `pillar_link` are fixed. Root cause: the criterion was declared
`fixable=True` but **no repair pass ever implemented it** — `_repair_relative_links` only
REWRITES an existing dead link, never ADDS a missing one. Added `_append_pillar_link`.
No new content generated: `8-proven-tips-metal-roof-maintenance-south-florida` already existed.

99-article run finished: 99/99 generated, **compliance_rate 0.97**, 96 published, 3 correctly
blocked (2× `valid_video_ids`, 1× `seo_ranking`) and never persisted. Cost $10.97 this run;
3,000-article extrapolation $332 standard / $166 batch.

## 6. Still open

- **CUTOVER** (§1) — the highest-value item on the board
- **Wendy draft unsent**; portfolio URL-space decision blocked on her
- `youtube-cookies` secret retained but **unused** — delete once archive is proven over a few days
- 4 test files still `drop_all` at teardown (`test_embed_job`, `test_integration_health_job`,
  `test_promote_job`, `tests/adapters/test_search_indexing`). I converted them and it caused **50
  failures** — `for_each_tenant` reads `SELECT id FROM tenants WHERE status='active'`, and
  drop-vs-truncate leaves that table in different states, so `aggregate_topics` ran twice
  (`assert 6 == 3`). **Reverted.** Converting them needs that implicit tenant dependency fixed
  first; it is not a mechanical sweep.
- `o365` MCP refresh token EXPIRED (`AADSTS700082`) — `gmail-enhanced` has a working token for
  the same mailbox and was used instead
- `proposal-reminders-daily` scheduler is PAUSED with no recorded reason
- Miami **settled**: `office_daily_overhead: 4250` live and verified; editable in the config UI

## 7. Gotchas earned today

- **"Works on my laptop" failed FOUR times**: yt-dlp missing from `app/requirements.txt`, deno
  missing from the Dockerfile, downloads bot-blocked only from Cloud Run, and cookies extracted
  only from a signed-in profile. Docker on this workstation uses the HOST network, so a container
  test proves nothing about Cloud Run egress.
- **A job that catches per-item errors must not exit 0 when EVERY item failed.** `archive_job`
  reported `{'archived': 0, 'errored': 15}` and `exit(0)`; Cloud Run showed green and would have
  nightly, forever. Now exits 1 on total failure.
- **`CalledProcessError.__str__` prints only the command.** A failure logged as "returned
  non-zero exit status 1" with no reason cost a full diagnosis round. Carry stderr in the message,
  and prefer the `ERROR` lines — the tail alone surfaced a trailing WARNING instead of the cause.
- **pytest imports EVERY test module before running any test.** A `drop_all` teardown tears
  tables out from under modules that `init_db()` at import and only DELETE rows. Create-but-
  never-drop is safe both ways. Isolation bugs only exist in combination — the full suite is the
  only meaningful gate.
- **yt-dlp `--cookies` exports the ENTIRE browser jar** — 1803 cookies across 439 domains
  including `1password.com`. Filter before storing. And even filtered it is a full Google session
  (SID/SAPISID are `.google.com`-scoped, so Gmail/Drive/Cloud Console too).
- **Secrets must never linger in scratch.** A CompanyCam key, its client secret, a screenshot of
  the revealed secret and a LIVE logged-in session sat in the scratchpad for hours. Write straight
  to Secret Manager, then `shred -u`.
- **Terraform must be applied before a deploy that touches a new job** — `deploy.sh` runs
  `gcloud run jobs update <job>`, which fails if TF has not created it yet.

---

**Standing archive directive:** `CONTINUATION-2026-07-27-pm.md` archived to `docs/continuations/`,
latest three kept at top level, README pointer refreshed.
