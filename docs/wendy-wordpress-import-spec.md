# Wendy WordPress / Rank Math Import Spec (DRAFT)

Status: **DRAFT — not reviewed by Wendy or Jon.** Buildout queue item #2.

## Grounding note (read this first)

I searched Gmail (`mcp__claude_ai_Gmail__search_threads`, queries `"Wendy"`, `"Rank Math OR
WordPress"`, `"perkinsroofing.net"`) and **found no thread with Wendy about WordPress, Rank
Math, or a deployment/import spec.** The two Wendy-adjacent hits were unrelated (a 2024 forwarded
chain email and a job-search newsletter — different Wendys, not Perkins). So there is **no
recorded requirement from Wendy herself** to ground this doc in.

Everything below is grounded in **this repo's existing, already-built integration** (the code
that talks to WordPress today, and `docs/PRODUCTION_CHANGES.md`, an existing external-config
checklist) plus the Jon/Tim 2026-07-20 Zoom transcript (`docs/meetings/2026-07-20-review-changes.md`)
for the publishing cadence. Every claim is tagged:

- **[CODE]** — verified by reading the adapter/job source, cited with file:line.
- **[DOC]** — verified by reading an existing repo doc.
- **[ZOOM]** — Tim/Jon on the 07-20 call, not Wendy.
- **[ASSUMED]** — inferred, not confirmed anywhere. Flagged as an open question below.

Nothing here is fabricated as if it came from Wendy. If a Wendy thread exists in a different
mailbox/account, re-run this search there before treating this as final.

## 1. Article fields we send to WP

Publish path: `adapters.wordpress.publish()` / `.update()`, called from
`jobs/article_job.py:generate_article()`. **[CODE]**

| Field | WP target | Source / rule |
|---|---|---|
| `title` | `wp/v2/posts.title` | LLM-generated, QA-gated | `adapters/wordpress.py:132` |
| `html` (content) | `wp/v2/posts.content` | Markdown→HTML converted (`markdownish_to_html`), then bleach-sanitized (`sanitize_html`) — allow-listed tags only, `<script>`/`on*`/`javascript:` stripped | `jobs/article_job.py:83-249` |
| `slug` | `wp/v2/posts.slug` | The article's own generated slug is passed explicitly — **not** left for WP to derive from title, because the Rank Math focus keyword is derived from that same slug (see below); letting WP invent a slug from the title would desync Rank Math's keyword-in-slug check from ours | `adapters/wordpress.py:118-122` (docstring), `publish()` payload |
| `meta_description` | `wp/v2/posts.excerpt` **and** `rank_math_description` post-meta | Clamped to 120–160 chars (`_clamp_meta`) | `jobs/article_job.py:1122-1136` |
| `focus_keyword` | `rank_math_focus_keyword` post-meta | The article's target keyword, passed through every publish/update call | `jobs/article_job.py:812,823` |
| FAQ | **not** a native WP field — folded into `_perkins_jsonld` post-meta as a `FAQPage` block; the Q&A text also appears in-page as regular HTML content the LLM writes | `core/jsonld.py:46` `build_faq_page` |
| JSON-LD (all types) | `_perkins_jsonld` post-meta (JSON string), rendered into `<head>` by a must-use plugin — WP strips `<script>` from post content, so plain content injection doesn't work | `adapters/wordpress.py:1-14` header docstring |
| `author` | `wp/v2/posts.author` | **Hardcoded to WP user id 3, policy "always Tim Kanak, never the API-credential user."** Overridable via `WP_AUTHOR_ID` env only if the WP user id ever changes | `adapters/wordpress.py:64-71` |
| `status` | `wp/v2/posts.status` | Defaults to `"draft"`. Callers must explicitly pass `status="publish"` (or `"future"`) to go live — the pipeline never auto-publishes | `jobs/article_job.py:13-14` |

Rank Math SEO title (`rank_math_title`) is also written, set equal to the article `title`
**[CODE]** (`adapters/wordpress.py:74-81`).

## 2. Schema handoff — what we emit vs. what Rank Math emits

**We emit ONLY `FAQPage` + `VideoObject`, deliberately, to avoid duplicating Rank Math's own
schema output.** Verbatim from the code comment: **[CODE]**

> "Rank Math (the live site's SEO plugin) already emits Organization/Person/Article/
> BreadcrumbList for every post... Emitting those node types again per-article would duplicate
> what Rank Math already puts on the page, so the per-post schema we inject here is scoped to
> the two node types Rank Math does NOT generate: the article's own FAQ Q&A pairs and its source
> VideoObject(s)."
> — `jobs/article_job.py:1099-1119` (`_build_article_jsonld`)

This is the function actually wired into the live publish path (`generate_scored_article`,
called at `jobs/article_job.py:1965,1989,2088`). Note there is a **second, older, unused**
JSON-LD builder inside `generate_article()` (`jobs/article_job.py:752-789`) that DOES build a
full `Organization`/`Article`/`Person` graph via `core/brand_identity.py` — it is dead code for
the live path (superseded by `_build_article_jsonld`) but still present in the file; don't let it
confuse a reviewer into thinking we duplicate Rank Math's Article schema. Worth a follow-up
cleanup ticket, out of scope here.

**`docs/PRODUCTION_CHANGES.md:33-35` (existing checklist item, [DOC]) already states this
requirement for Wendy's side:**
> "SEO plugin (P6). Confirm Yoast or RankMath. Ensure it does NOT emit a *conflicting* Article/
> FAQ schema for our posts (duplicate JSON-LD). Either let our mu-plugin own schema for
> API-posted articles, or disable the plugin's schema on those."

Since we only emit FAQ+Video, the actual ask of Wendy narrows to: **confirm Rank Math's own
FAQ block/schema feature is OFF (or non-conflicting) for these posts**, so there's exactly one
`FAQPage` node per page, not two.

## 3. Internal links + URL structure

- **No `/blog/` prefix.** WordPress permalinks must be set to **Post name** under
  Settings → Permalinks (also required for REST routes to resolve at all —
  `docs/PRODUCTION_CHANGES.md:16-17`, **[DOC]**, confirmed as the actual staging fix). Every
  post — and every SERVICES page — lives at a top-level `https://perkinsroofing.net/<slug>`.
  **[CODE]** comment: `jobs/article_job.py:760-762`.
- **Canonical URL** is computed as `{WP_URL}/{slug}` and written into the `Article.url` field
  of JSON-LD in the (currently dead-path) full-graph builder; the live `_build_article_jsonld`
  path doesn't emit an `Article` node at all, so **Rank Math owns the canonical `<link
  rel=canonical>` tag** for live posts. **[ASSUMED]** — not independently verified that Rank
  Math's canonical always resolves to the top-level slug rather than some other structure; flag
  to Wendy.
- **Internal links** are appended deterministically, never invented by the LLM
  (`_ensure_internal_links`, `jobs/article_job.py:1339-1370`, **[CODE]**):
  - Every cluster article links up to its pillar (`{WP_URL}/{pillar_slug}`).
  - Up to 3 contextual links to `core/internal_links.py` SERVICES pages, matched by keyword
    presence in the article body (never spammed onto unrelated posts).
  - **`core/internal_links.py` slugs are UNCONFIRMED against the live site** — the module's own
    header says so explicitly: *"Every url below is the obvious/expected path for its service
    based on naming convention, NOT verified against perkinsroofing.net's actual permalinks."*
    **[CODE]** `core/internal_links.py:6-11`. This is a concrete open item for Wendy/Tim (§6).
- Every article ends with a fixed YouTube channel footer link (never duplicated on regen —
  idempotency guard checks for existing footer text first). **[CODE]**
  `jobs/article_job.py:1330-1337`.

## 4. Batch / cutover process

**[ZOOM]**, from the 07-20 call (`docs/meetings/2026-07-20-review-changes.md:24`) and captured
in the current buildout plan (`docs/perkins-buildout-plan-2026-07-21.md:30`, **[DOC]** — not a
Wendy email):

> "Publish 10 articles per day, rotating clusters to maintain fresh content."

Planned process (as currently written in the buildout plan, not yet built/executed):
1. **Prep, do not post to staging.** Render and queue all PILLAR articles plus ≥2 CLUSTER
   articles per pillar (10 pillars × ≥2 clusters), all as WP drafts.
2. **On prod-WP cutover**, bulk-upload every pillar + its 2 clusters as `status="draft"`.
3. **Release 10/day, one per pillar**, rotating which cluster/pillar goes live via scheduled
   promotion.

The scheduling mechanics already exist and are wired: `app.models.ScheduledContent` rows with
a `publish_at` timestamp; `core/scheduler.due()` selects rows whose `publish_at <= now`;
`jobs/promote_job.py` (Cloud Scheduler cron target) flips the matched WP post from its current
status to `"publish"` via `adapters.wordpress.update_status()`, then best-effort submits the URL
for search-engine indexing. **[CODE]** `jobs/promote_job.py:30-81`. There is a documented and
fixed desync bug here (memory: `publish-desync-bug`) — `promote_job` is the correct/live
publisher path; `jobs/publish_job.py` is dead/orphaned code and must not be revived or pointed at
by any Wendy-facing tooling.

**Search-engine submission is separate from Rank Math and already built** [DOC]
(`docs/perkins-buildout-plan-2026-07-21.md:37-47`, `core/search_indexing.py`): IndexNow (Bing/
Yandex etc.) + Google Indexing API, fired on every promote and daily as a catch-up sweep, gated
behind `SEARCH_INDEXING_ENABLED`. **Rank Math owns `sitemap.xml` and `robots.txt`** — our
IndexNow/Indexing-API calls are a notification push on top, not a sitemap generator; Wendy should
not need to touch either file for our posts to appear correctly, but should NOT install a second
sitemap plugin that could conflict with Rank Math's.

## 5. What Wendy must configure

This list already exists as `docs/PRODUCTION_CHANGES.md` — repeated/summarized here for this
spec, **[DOC]**, not re-derived:

1. **Application Passwords enabled** (Users → Profile) for the API user — some security plugins
   (Wordfence, Solid Security, iThemes) disable this; needs re-enabling if present.
2. **Permalinks = "Post name"** (Settings → Permalinks) — required both for the no-`/blog/`
   top-level URL structure and for `/wp-json/` REST routes to resolve at all.
3. **Install the JSON-LD mu-plugin BEFORE any article is published.** Two delivery forms exist:
   `wp-mu-plugin/perkins-jsonld.php` (drop into `wp-content/mu-plugins/`, filesystem access
   needed, no activation step) or `wp-plugin/perkins-jsonld/` (zip, upload via Plugins → Add
   New → Upload, for when only wp-admin access is available). **Ordering matters**: WordPress
   silently drops writes to unregistered post-meta keys, so any article published before the
   plugin is active has no schema and must be republished.
4. **Confirm Rank Math is the active SEO plugin** and that its own FAQ/schema output doesn't
   duplicate our `FAQPage`/`VideoObject` nodes (§2).
5. **Confirm REST API isn't blocked** for Application-Password auth — GoDaddy Managed WP has
   been seen stripping the `Authorization` header (fix is a `.htaccess` `SetEnvIf` rule if hit).
6. **Confirm the active theme doesn't strip bare-URL oEmbeds** (no plugin needed otherwise —
   WordPress autoembed already renders a bare YouTube URL on its own line as a player, verified
   on staging).

## 6. Open questions for Jon / Wendy

1. **No Wendy thread found in Gmail.** Confirm the right mailbox/account was searched, or point
   me at the actual thread/doc her requirements live in — this entire draft is currently
   repo-only + Zoom-only grounding, zero input from Wendy directly.
2. **`core/internal_links.py` SERVICES page slugs are unconfirmed** against the live site
   (`/roof-repair/`, `/roof-replacement/`, `/roof-inspection/`, `/commercial-roofing/`,
   `/residential-roofing/`, `/metal-roofing/`, `/tile-roofing/`, `/flat-roofing/`) — need Wendy
   to confirm the real permalinks (and anchor-text preference) before these go live; a wrong
   slug ships a 404 internal link on every matching article.
3. **Canonical URL / Rank Math interaction** — does Rank Math's canonical tag reliably resolve to
   the top-level `/<slug>` structure we assume, or does anything on the live site (redirects,
   category prefixes) diverge from that assumption?
4. **Rank Math version/config** — which Rank Math tier (Free/Pro) is live, and is its FAQ Block
   / schema output already disabled globally or does it need disabling specifically for
   API-posted content?
5. **"10 pillars"** — the cadence text says "1 per each of 10 pillars"; confirm 10 is the actual
   planned pillar count for the initial cutover batch (not independently verified against a
   topic list in this repo).
6. **WP_AUTHOR_ID = 3 for Tim Kanak** — confirm this user id is stable on the production site
   (it's currently only verified against the staging GoDaddy temp domain
   `jhk.14f.myftpupload.com`, per `docs/PRODUCTION_CHANGES.md`).
7. **dead-code cleanup** (not blocking, flagging for Jon): `generate_article()`'s inline
   Organization/Person/Article JSON-LD block (`jobs/article_job.py:752-789`) is superseded by
   `_build_article_jsonld` and unused on the live path — worth deleting so a future reader
   doesn't think we duplicate Rank Math's Article schema.
