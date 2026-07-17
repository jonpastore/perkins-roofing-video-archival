# Perkins #319 — Social platform app registrations for auto-posting

**Goal:** register developer apps and pass app review on all six "Must" platforms
(TikTok, Instagram Reels, YouTube Shorts, Facebook Reels, LinkedIn, X) plus the one
"Should" platform (Pinterest), so `adapters/distribution/*` and `adapters/tiktok.py` /
`adapters/meta_ig.py` can flip from mocked scaffolds to live posting. This is the
2-4 week critical path for the distribution feature — nothing else blocks it.

**Repo state today:** every adapter under `adapters/distribution/` (Facebook, LinkedIn,
Pinterest, X, YouTube Shorts) returns a `..._mock_<uuid>` id and is explicitly marked
`SCAFFOLD: mocked — real API wiring blocked on app-review/creds` (e.g.
`adapters/distribution/facebook.py:3`). `adapters/tiktok.py` and `adapters/meta_ig.py`
already implement the real HTTP calls but read live credentials straight from
environment variables that don't exist yet in any deployed environment.

## Summary table

| Platform | Owner (must click/provide) | Lead time | Cost | Blocking dependency |
|---|---|---|---|---|
| TikTok | Josh (creates TikTok for Developers account + app) | **2–4 weeks** (audit) + domain verify first | Free | Josh must add a DNS TXT record for the GCS video-hosting domain *before* audit can pass for `PULL_FROM_URL` |
| Instagram Reels + Facebook Reels | Tim/Josh (owns the FB Page + IG professional account); Josh (Meta app + review) | **~1 week** Business Verification, then **2–4 weeks** App Review (shared Meta app, 2 screencasts) | Free | IG account must already be a Business/Creator account linked to a FB Page before OAuth test users can be added |
| LinkedIn | Josh (creates LinkedIn Company Page + app); org admin (Tim) approves app-to-org association | **1–2 weeks** Development tier, then must reach **Standard tier within 12 months** (screen recording + test creds) | Free | Needs a LinkedIn Company Page (organization), not a personal profile |
| YouTube Shorts | Josh (Google Cloud project + OAuth consent screen); Tim (owns the YouTube channel, must approve OAuth grant) | **2–3 days** brand verification; compliance audit for public (non-private) uploads has **no published SLA** — budget 2+ weeks | Free (quota increase form is free, just slow) | App created after July 2020 without a passed compliance audit can only upload **private** videos — a hard blocker for public Shorts |
| X (Twitter) | Josh (developer account) | **Days**, mostly self-serve since the Feb 2026 pricing cutover | **Pay-per-use**: $0.015/post (plain), $0.20/post with a link — no more free write tier | None structural; just needs a funded billing method on the dev account |
| Pinterest (Should) | Josh (creates app); Tim/Josh (owns Pinterest business account) | **Days to ~1 week** for Trial; a further round (screen recording) for Standard | Free | Standard access needed before pins are publicly visible (Trial pins are hidden) |

Ordered below by longest realistic lead time first — start TikTok and the Meta app
*today*, in parallel; they gate the whole 2–4 week window.

---

## 1. TikTok — Content Posting API

**Consumed by:** `adapters/tiktok.py` — reads `TIKTOK_ACCESS_TOKEN`, `TIKTOK_OPEN_ID`
(`adapters/tiktok.py:55-56`), and `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` /
`TIKTOK_REFRESH_TOKEN` for token refresh (`adapters/tiktok.py:167-169`).

### Prerequisites
- A TikTok **creator/business account** that Josh (or Tim) controls — this is the
  account videos get posted to. Personal accounts work for OAuth but Direct Post to a
  business account needs the account switched to TikTok Business.
- Ownership of the GCS bucket domain that serves `video_url` (already referenced in
  `adapters/tiktok.py:67-69`: "The GCS bucket domain must be verified via DNS TXT
  prefix verification before TikTok allows PULL_FROM_URL").

### App creation steps
1. Josh signs up at the [TikTok for Developers portal](https://developers.tiktok.com/) →
   **Manage apps** → create a new app.
2. Add the **Content Posting API** product to the app.
3. Enable the **Direct Post** setting under Content Posting API config.
4. Under domain settings, verify the GCS-served video domain via DNS TXT record
   (Josh needs DNS access to the domain — coordinate with whoever holds it).
5. Request the **`video.publish`** scope.

### API products / scopes
- `video.publish` — required for Direct Post; **requires a passed app audit before
  posts go public.** Until audited, all posts are forced to `SELF_ONLY` (private)
  visibility — matches the hardcoded `"privacy_level": "SELF_ONLY"` already in
  `adapters/tiktok.py:98` (that line will need to change to `PUBLIC_TO_EVERYONE` or
  similar once the app is audited).

### App review requirements
- Privacy policy URL, a demo video of the full OAuth + upload flow, and a description
  of data handling (TikTok's docs don't publish an exact checklist beyond this —
  confirm the current list inside the developer portal's audit form at submission
  time: `developers.tiktok.com/application/content-posting-api`).
- Audit is per-app, not per-scope; typically several rounds of feedback.

### Timeline
2–4 weeks after submission, per third-party integrator guides (TikTok doesn't publish
an official SLA). Do the DNS TXT domain verification **first** — it's a prerequisite
that can be done in parallel with waiting on account verification and costs nothing to
start immediately.

### Cost
Free.

### What Josh must do
- Own/create the TikTok for Developers account and app.
- Get DNS access (or a ticket to whoever holds it) to add the TXT record.
- Record the OAuth + Direct Post demo video for the audit submission.

Sources: [Content Posting API — Get Started](https://developers.tiktok.com/doc/content-posting-api-get-started), [TikTok for Developers](https://developers.tiktok.com/products/content-posting-api/), [Content Posting API Guide 2026 — Zernio](https://zernio.com/blog/tiktok-posting-api)

---

## 2. Instagram Reels + Facebook Reels — one shared Meta app

Both live under the same Meta for Developers app, so run them as a single workstream.

**Consumed by:** `adapters/meta_ig.py` — reads `IG_USER_ID` and
`META_SYSTEM_USER_TOKEN` (`adapters/meta_ig.py:57-58`). Facebook Reels itself is still
a scaffold (`adapters/distribution/facebook.py`) — no env vars wired yet; when built it
should read from the same Meta system-user token via the `SecretManagerOAuthStore`
convention (`tenants-{tenant_id}-facebook-access_token`, see
`adapters/distribution/oauth_store.py:94-96`) rather than a raw env var, to match how
the other `distribution/` adapters are meant to source creds in production.

### Prerequisites
- The IG account must already be a **Business or Creator (professional) account**
  linked to a Facebook Page — if Tim's IG is currently a personal account, that
  conversion + Page link has to happen before anything else.
- **Meta Business Verification** for the business entity (legal docs, ~2-5 business
  days) — do this immediately, it gates App Review.

### App creation steps
1. Josh creates an app at [developers.facebook.com/apps](https://developers.facebook.com/apps).
2. Add the **Instagram** product and the **Facebook Pages API** (Pages product) to the
   same app.
3. Add Tim's Meta Business Manager, verify the business (legal name, address, docs).
4. Create a permanent **System User** in Business Manager and generate the system-user
   token used by `META_SYSTEM_USER_TOKEN`.
5. Add the Page and connected IG account as test assets so review testers can act on
   real data.

### API products / scopes
- IG: `instagram_business_basic` + `instagram_business_content_publish` — note Meta
  renamed these; the docstring in `adapters/meta_ig.py:12-14` still says
  `instagram_content_publish` + `instagram_basic` + `pages_read_engagement`. **Verify
  the current exact permission names in the App Dashboard at submission time** — this
  is exactly the kind of naming drift that silently fails a submission.
- FB Reels: `pages_manage_posts` + `pages_manage_engagement` (dependency for Reels
  specifically), Page Access Token.

### App review requirements
- A **separate screencast per permission** showing the end-to-end OAuth + publish
  flow, in English UI (captions ok), with buttons/UI elements explained.
- Privacy policy URL and data-use explanation for Advanced Access (needed because this
  app publishes on behalf of an account it doesn't structurally "own" the same way a
  personal dev test app would).

### Timeline
Business Verification ~2-5 business days, then App Review **2-4 weeks** with typically
one revision round. Facebook's own guidance: 5-10 business days for first review,
3-5 for a second pass.

### Cost
Free.

### What Tim/Josh must do
- Tim: convert IG to a professional account if not already, link it to the FB Page,
  approve the OAuth grant to the system user, provide legal business documents for
  Business Verification.
- Josh: build the app, record both screencasts, submit and iterate on review feedback.

Sources: [Instagram Platform App Review](https://developers.facebook.com/docs/instagram-platform/app-review/), [Facebook Pages API](https://developers.facebook.com/docs/pages-api/), [Facebook Graph API Posting Guide 2026](https://postproxy.dev/blog/facebook-graph-api-posting-guide/)

---

## 3. LinkedIn — Community Management API

**Consumed by:** nothing yet — `adapters/distribution/linkedin.py` is a pure mock; no
env vars exist to grep. Real creds should follow the same `SecretManagerOAuthStore`
pattern as the other `distribution/` adapters (`tenants-{tenant_id}-linkedin-*`).

### Prerequisites
- A **LinkedIn Company Page** (organization), not a personal profile — this is who the
  API posts as. Confirm Perkins already has one; if not, someone with admin rights on
  the personal profile creates it first.
- Business email, organization's legal name, registered address, website, privacy
  policy — needed on the access-request form.

### App creation steps
1. Josh creates an app at [developer.linkedin.com](https://developer.linkedin.com/).
2. Under **Products**, add **Community Management API**.
3. Complete the access-request form (org details above).
4. An admin of the Company Page (Tim, presumably) must approve associating the app
   with the organization.

### API products / scopes
- Community Management API grants **Development tier** access first (limited call
  volume, enough to build/test).
- Must upgrade to **Standard tier within 12 months** of first access or LinkedIn
  revokes it for inactivity — this is the actual production-ready tier; treat it as
  part of this task, not a "later" item.

### App review requirements
- Standard tier upgrade needs: a completed access form, a **screen recording** of the
  app posting through the real OAuth flow, and **test credentials** shared with
  LinkedIn reviewers.
- 2026 update: previously-declined or expired requests can now be resubmitted via a
  "Reapply" button that reloads the original form instead of starting over.

### Timeline
Development tier access is comparatively fast (days to ~1-2 weeks). Standard tier
review timeline isn't published — budget similarly to Meta's 2-4 weeks since it also
requires a screencast-style review.

### Cost
Free.

### What Josh/Tim must do
- Josh: create the app, submit both tier requests, record the screencast.
- Tim (or whoever admins the Company Page): approve the app's organization
  association.

Sources: [LinkedIn Community Management API](https://developer.linkedin.com/product-catalog/marketing/community-management-api), [Increasing Access — LinkedIn Learn](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06), [Migration Guide — Community Management API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-api-migration-guide?view=li-lms-2026-06)

---

## 4. YouTube Shorts — YouTube Data API v3

**Consumed by:** `adapters/distribution/youtube_shorts.py` is currently a pure mock
(no env vars). Related-but-separate adapters already read live YouTube creds:
`adapters/youtube_comments.py` reads `YOUTUBE_OAUTH_REFRESH_TOKEN`, `OAUTH_CLIENT_ID`,
`OAUTH_CLIENT_SECRET` (`adapters/youtube_comments.py:126-136`) and both
`adapters/youtube_comments.py:40` / `adapters/youtube_stats.py:19` read
`YOUTUBE_API_KEY` (falling back to `YT_API_KEY`) for read-only calls. The Shorts
upload path will need its own OAuth client with the **`youtube.upload`** scope (the
existing OAuth client/refresh-token env vars are for comment-reply and stats calls,
not upload — don't assume they carry the right scope).

### Prerequisites
- Tim's YouTube channel account, which the OAuth grant authorizes against.
- A Google Cloud project (can reuse the one already backing `stt_gcp.py` / GCP infra
  in this repo, or a dedicated one — Josh's call).

### App creation steps
1. Josh creates/reuses a Google Cloud project, enables **YouTube Data API v3**.
2. Configure the **OAuth consent screen** (External user type), submit for **brand
   verification** (fast, 2-3 business days).
3. Create OAuth 2.0 credentials (`OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` style), add
   Tim's account as an OAuth test user during development.
4. Request the `youtube.upload` scope on the consent screen — this is a **restricted/
   sensitive scope**, requiring justification text plus a demo video of the OAuth
   grant + upload flow uploaded to YouTube Studio (Unlisted) and linked in the
   verification form.

### API products / scopes
- `https://www.googleapis.com/auth/youtube.upload` for `videos.insert`.
- **Critical blocker to flag to Josh explicitly:** apps created after July 28, 2020
  that have **not** passed Google's compliance audit can only upload videos as
  **private** — never public. That audit is separate from (and in addition to) OAuth
  scope verification. Confirm this project's audit status before assuming Shorts can
  go public once creds exist.
- Each `videos.insert` costs 1,600 quota units against a default 10,000 units/day
  budget (~6 uploads/day) — request a **quota increase via Google's form** early since
  it has no published SLA either (`adapters/distribution/youtube_shorts.py:14-15`
  already flags this).

### App review requirements
- OAuth consent screen brand verification: logo/name accuracy check, ~2-3 business
  days.
- Sensitive-scope verification for `youtube.upload`: demo video + justification, ~10
  days once a *complete* submission lands (delays come from back-and-forth on
  incomplete submissions).
- Compliance audit for public uploads: no published timeline — this is the actual
  long pole, start it immediately once the OAuth app exists.

### Timeline
Brand verification: days. Sensitive scope verification: ~10 days. Compliance audit +
quota increase: unbounded/unpublished — budget 2+ weeks and start both in parallel
with the Meta and TikTok tracks.

### Cost
Free (quota increase and verification are free; they're just not guaranteed-timeline).

### What Josh/Tim must do
- Josh: GCP project + OAuth client setup, submit verification forms, file the quota
  increase request and the compliance audit request as early as possible.
- Tim: authorize the OAuth grant against his channel; may need to be listed as a test
  user during the pre-verification phase.

Sources: [YouTube Data API — Quota and Compliance Audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits), [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification), [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

---

## 5. X (Twitter) — X API v2

**Consumed by:** `adapters/distribution/x.py` is currently a pure mock (no env vars
wired yet).

### Prerequisites
- None structural — X's Feb 2026 pricing change replaced the old approval-gated tier
  system with **pay-per-use by default**. A funded billing method on the developer
  account is the real prerequisite now.

### App creation steps
1. Josh signs up for a developer account at the [X developer portal](https://developer.x.com/).
2. Create a project + app; enable **OAuth 2.0 with PKCE** (user-context auth needed to
   post on behalf of the Perkins account, not app-only auth).
3. Attach a payment method for pay-per-use billing (or opt into a legacy Basic/Pro plan
   if Perkins already has one predating the Feb 2026 cutover — check first, since
   existing subscribers keep their old fixed-price plan).

### API products / scopes
- `tweet.write` scope via OAuth 2.0 user context, for `POST /2/tweets`.

### App review requirements
- No formal review queue for basic write access post-cutover — it's mostly self-serve
  signup plus a use-case questionnaire on account creation. (This is the lightest of
  the six "Must" platforms.)

### Timeline
Days — the fastest of the six, assuming billing is set up promptly.

### Cost
**Pay-per-use, not free**: $0.015 per plain post, $0.20 per post containing a link,
capped at 2M reads/month at $0.005/read. Legacy Basic ($200/mo) / Pro ($5,000/mo) fixed
plans only apply to pre-cutover subscribers. At Perkins' likely posting volume, confirm
with Jon/Tim whether pay-per-use or a legacy plan (if grandfathered) is cheaper —
pay-per-use wins below ~13,000 link-free posts/month per third-party analysis.

### What Josh must do
- Create the developer account + app, attach billing, confirm which pricing model
  applies.

Sources: [X API Pricing 2026 — Postproxy](https://postproxy.dev/blog/x-api-pricing-2026/), [X API pay-per-usage pricing](https://docs.x.com/x-api/getting-started/pricing), [X (Twitter) API Pricing 2026 — Blotato](https://www.blotato.com/blog/twitter-api-pricing)

---

## 6. Pinterest (Should) — Pinterest API v5

**Consumed by:** `adapters/distribution/pinterest.py` is currently a pure mock (no env
vars wired yet).

### Prerequisites
- A Pinterest **business account** for Perkins (convert if it's currently personal).

### App creation steps
1. Josh creates an app at the [Pinterest Developers portal](https://developers.pinterest.com/).
2. Submit for initial review → app receives **Trial access** automatically once
   approved (full endpoint surface, but pins created stay hidden from the public).
3. Once ready for production, submit the **Standard access** upgrade form with a
   screen recording of the app completing an OAuth + pin-creation flow.

### API products / scopes
- `pins:write`, `boards:read` (or equivalent v5 scopes for creating pins) — Trial
  access covers pins, boards, ads, catalogs, analytics, trends at per-category rate
  caps.

### App review requirements
- Standard tier: screen recording showing correct OAuth flow and confirmation that no
  sensitive information is stored improperly.

### Timeline
Trial access: days to about a week for first approval. Standard access: comparable
review cycle to the screencast-based reviews above, but Pinterest's community reports
generally faster turnaround than Meta's.

### Cost
Free at both Trial and Standard tiers.

### What Josh must do
- Create the app, submit Trial then Standard access requests, record the demo video.

Sources: [Pinterest Access Tiers](https://developers.pinterest.com/docs/key-concepts/access-tiers/), [Pinterest API Pricing 2026 — Blotato](https://www.blotato.com/blog/pinterest-api-pricing)

---

## Cross-cutting notes

- **Two different credential-sourcing patterns exist in the repo today** — worth
  reconciling before wiring real creds: `adapters/tiktok.py` and `adapters/meta_ig.py`
  read raw `os.environ[...]` values directly, while the `adapters/distribution/*`
  adapters are built against `SecretManagerOAuthStore` / `MockOAuthStore`
  (`adapters/distribution/oauth_store.py`), which stores creds per-tenant in GCP
  Secret Manager under `tenants-{tenant_id}-{platform}-{key}`. Whoever wires the new
  Facebook/LinkedIn/X/Pinterest/YouTube-Shorts creds once registrations land should
  follow the Secret Manager convention (it's already tenant-scoped and production-
  ready), not add more raw env vars — matches TRD-F5 §4 referenced in
  `adapters/distribution/oauth_store.py:1-20`.
- **Start TikTok's DNS TXT verification and the Meta Business Verification today** —
  they're free, have no dependency on anything else in this list, and are the actual
  long poles.
- **File the YouTube compliance-audit request and quota-increase form as soon as the
  GCP project exists** — both have unpublished timelines, so the earlier they're
  filed, the less they gate the rest.
- Re-verify every exact permission/scope name in each developer console at submission
  time — Meta in particular renamed IG permissions (`instagram_basic` →
  `instagram_business_basic`) since the in-repo adapter docstrings were written.
