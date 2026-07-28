# CONTINUATION 2026-07-28 pm — Wendy's review closed, CI deploys from IaC, and four files that lived on one laptop

**HEAD `ecf4deb`**, pushed. **Deployed image `platform:7688ce6`** — everything after it is NOT
deployed, because the CI deploy path is still going red on its last step (see §3).
Prod configs **jupiter v27 / miami v29 / naples v27**. Terraform state is now REMOTE.

---

## 0. Read these first

| | |
|---|---|
| `docs/knowify-price-diff-2026-07-28.md` | what Tim's catalog settles, and the 4 questions still open |
| `.claude/skills/verify-reproducible-from-git/SKILL.md` | the day's recurring defect, as a runnable pre-commit check |
| `scripts/plan_as_ci.sh` | plan as `ci-deployer`; **use this instead of pushing to find IAM gaps** |
| `~/perkins-corpus/gen99-w8-20260728-1608.log` | the 99-article run, still going |

---

## 1. Overhead flipped to Tim's model — DEPLOYED

`overhead_basis: "branch"` on all three branches: days x ONE daily burn.

| branch | config | burn | effect |
|---|---|---|---|
| jupiter | v27 | $1,400/day | +8-10% |
| miami | v29 | $4,250/day | **+46-54%** |
| naples | v27 | $1,400/day | +8-10%, **carried forward from Jupiter, NOT measured** |

Verified on the live API: 7 days x burn matches the quoted overhead line to the cent. Jon chose
Miami at $4,250 (Tim's own $85,000/20) with the +50% understood. **Nobody at Miami has been told.**

## 2. Wendy's 2026-07-28 review — all 7 validated, fixed, verified on the LIVE site

She was right on every item. It took four passes because each time I checked the RENDERED page
instead of the stored row, another shape appeared:

- **TOC had THREE shapes** — `<div class="toc">`, an H2+list, and an H2+description+list. Two
  passes shipped believing it was done.
- **"Learn more:" is stored as BARE MARKDOWN** — `_markdown_to_html` adds the `<p>` only at
  publish, so the source-side check passed while readers saw 9 dead pointers.
- **The phone links were OUR sanitizer** — `_SAFE_URI_RE` allowed `mailto:` but not `tel:`, so
  bleach stripped the href off every click-to-call link. I blamed WordPress twice before checking
  our own renderer.

**Two of her items were things our gate REQUIRED** (in-content TOC, in-content image). The
generator was doing exactly what it was told. Both reversed.

Verified against what **WordPress stored** (`context=edit`, immune to the CDN cache that made an
earlier pass look clean): **112/112 published posts** clean. All 375 rows compliant, 371 fully —
the other 4 point at pillar slugs that never existed (`metal-roof-maintenance`,
`roof-inspection-before-buying-a-house`), which the 99-run should create.

⚠️ Near-misses caught before shipping: `<a` also matches `<aside`, and with DOTALL the repair
would have swallowed every callout body across 333 articles. And `<a id="x">` is an anchor
TARGET, not a dead link — unwrapping those breaks every deep link into the page.

## 3. CI deploys from IaC — built, NOT YET GREEN

`.github/workflows/deploy.yml` + `infra/cicd.tf`. Keyless WIF, repo-pinned, main-only, deployer
holds `run.admin`/`cloudbuild`/`artifactregistry`/`storage`/`viewer` — not editor.

**Every step passes except the last two, which had never been reached:**

```
success  auth (keyless WIF)          success  Terraform drift gate
success  read CF token               failure  Deploy (build image, roll service + jobs)
```

Progress across five attempts: auth → state → permissions → dirty-tree → **Cloud Build actAs**
(granted, untested). The next run is the first with that grant. **If it fails again, do NOT push
to find out — run `bash scripts/plan_as_ci.sh` and impersonate.** Each push→CI→deploy cycle is
~10 minutes; impersonation finds every gap locally in one pass.

**The drift gate earned its keep on its first real run** — it reported `15 to DESTROY`: every
Cloudflare DNS record, MX, SPF, DKIM, DMARC and the WAF for perkinsroofing.net.

**NOT adopted: plan-on-PR.** Standard practice, but it needs an identity that can authenticate
from a non-main ref — exactly what the main-only fix closed. Needs a separate read-only SA.

## 4. ⚠️ FOUR things existed only on one laptop

This was the day's real finding, and it recurred four times:

| what | consequence |
|---|---|
| `.env` config (`WP_URL`, `WP_USER`, `OAUTH_CLIENT_ID`) | CI deploy would OVERWRITE prod config with `""` |
| `terraform.tfvars` (`cloudflare_zone_id`) | plan proposed **destroying all DNS/MX/SPF/DKIM/DMARC/WAF** |
| **terraform state** (local 337KB, 146 resources) | losing the laptop = terraform no longer knows the infra exists |
| `SQUARES_API_KEY` | shipped blank from any other machine |

All four now in git or GCS. State is in a versioned bucket (146 in, 146 out, plan clean after).
Captured as `.claude/skills/verify-reproducible-from-git`. The skill was itself gitignored on
first commit — a fifth instance of the same defect.

## 5. Knowify — Tim's tenant, scraped

MCP re-bound to **Perkins Roofing Jupiter, Company 30586 / Tenant 28403**. His catalog is **226
items to Josh's 26**. Shipped: 219 scope templates (171 reroof / 41 repair / 8 accent), a native
`<datalist>` type-ahead, and 4 accent prices into `line_items`. **tile/PREFERRED $165 is SETTLED**
— his catalog confirms ours.

⚠️ Accent items are priced but **NOT selectable in the SPA** — `extra_line_items` is API-only.

## 6. In flight when this was written

**99-article run, 8 workers, ~30/99 done**, detached (`setsid`), survives a session end.
Log `~/perkins-corpus/gen99-w8-20260728-1608.log`, report `~/perkins-corpus/gen99_report.json`.
DB at 414 articles (112 published / 301 scheduled / 1 draft).

**The "8-worker wedges on Vertex" memory did NOT reproduce** — 8 workers ran clean with one
transient 429 the retry absorbed. ~4h instead of ~16h. Cost is unchanged by worker count
(~$8.70); parallelism buys wall-clock, not money.

## 7. Still needs Tim / Jon

- **Miami +50%** — nobody there has been told
- 4 Knowify price questions (`docs/knowify-price-diff-2026-07-28.md`): ridge vent $9.79 vs his
  $12.50 · tile upgrade bundles disagree 3 ways within $5 · West Lake is tier-dependent, so a flat
  adder is the wrong SHAPE · HVHZ accent prices carried from FBC
- Naples' daily burn — carried from Jupiter, never stated
- **#430 project dimension is ON HOLD** (Jon 7/28); proposals stay 1:1
- The unsent Tim draft in Jon's DeGenito Outlook

## 8. Gotchas earned today

- **`pkill -f <pattern>` matched my own shell and killed it mid-command** — the documented trap,
  walked into anyway. Put the pattern in a FILE.
- **Verify the ARTIFACT, not the source.** Every defect that escaped lived in the gap between
  `content_md` and published HTML. Read back what WordPress STORED (`context=edit`), not the
  CDN-cached page.
- **A regex that matches more than it means.** `<a` matches `<aside`; `(?![a-z])` is load-bearing.
- **`terraform plan` resolves DATA SOURCES**, so a plan needs read access to any secret read that
  way — `secretmanager.viewer` is not enough.
- **A write-only attribute can never be verified.** Identity Platform's `client_secret` is never
  returned by the API, so it planned an update forever. `ignore_changes`, rotation escape hatch
  documented on the resource.
- **gcloud's `--impersonate-service-account` prints a WARNING to stderr** — capturing it with
  `2>&1` made a 53-char token 219 chars of prose.
- **Check `gh run list --limit 1` matches the SHA you care about.** Twice I read a previously
  completed run and reported the wrong status.
- The malformed `wordpress-app-password` (v3/v4 stored as `"…" #update vault`) broke prod's WP
  writes since 7/22. v5 is clean; v3/v4 disabled.

---

**Standing archive directive:** `CONTINUATION-2026-07-27.md` archived to `docs/continuations/`,
latest three kept at top level, README pointer refreshed.
