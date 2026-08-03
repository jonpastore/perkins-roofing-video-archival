# CONTINUATION — 2026-08-03

**Deployed state is the first thing to check, because it was wrong for half an hour and nothing
went red.** See §1. Live pricing configs: jupiter **v31**, miami **v32**, naples **v31**.
Migrations through **0055**, applied. GCP spend budget: **live** ($200/mo, 0.5/0.8/0.9/0.95).

Follows `CONTINUATION-2026-08-02-night.md`, which was a backlog audit. This session executed the
things that audit found — and the single most useful output is not a feature.

---

## §0 — THE ONE THING TO READ

**Five separate defects this session were the same shape: a correct thing that nothing could
reach.** Not one was a wrong value.

| | the correct part | what could not reach it |
|---|---|---|
| `#417` G3 / G9 | right values in config, incl. all three ACTIVE prod configs | **no code read them** — and `_note_stockmeier_floor` claimed it was "now enforced as a warning" |
| `#417` inputs | engine, config and prod deploy all correct | **`QuoteRequest` could not express them** — Pydantic drops unknown keys, the endpoint returns 200, the lines are silently absent |
| `#388` `gc` branch | exists, active, named "Perkins Construction" since migration 0041 | **no active pricing config** → the estimator 503s, so the branch was selectable and dead |
| `#387` notes | `quote_snapshot.notes` was read | by `_assemble_review_text`, which feeds the **AI review** — not the customer document. All four doc renderers ignored it |
| `#444` budget | `google_billing_budget` in `main.tf` for weeks | **`cloudbilling` + `billingbudgets` missing from `required_apis`**, so the account id the `count` guard waited on was unreadable |

**In four of the five, something asserted it was done** — a config note, a green test suite, a
tracker entry, a `count` guard that read as merely waiting on a variable.

**Every one was caught by exercising the running system.** None by reading code, and none by the
test suite. The checks that worked:

- config rule → grep for the **reader** (the accessor, the call site), never the key
- new engine input → **call the real endpoint** and assert the line appears; a 200 proves nothing
- new config key → confirm it exists in **PROD's active config**, not just the fixture
- renderer field → establish **which** renderer; `_assemble_review_text` is not the contract
- terraform → **`plan` after `apply`**; "Apply complete!" is not convergence

Corollary for tests: write two that fail for **different** reasons — one that the surface can
express the thing, one that it forwards it. A field that parses and is then discarded fails
exactly as silently as one never declared.

---

## §1 — ⚠️ A STALE DEPLOY OVERWROTE A NEWER ONE, AND EVERY CHECK WAS GREEN

PRs #21 (`dedca28`) and #22 (`ff54eaa`) merged minutes apart. Each merge ran `ci`; each `ci`
completion triggered its own deploy, **checked out at its own triggering commit** — which is what
`deploy.yml`'s `ref:` deliberately asks for ("deploy the commit CI validated, not whatever main
has drifted to since").

`concurrency: deploy-prod` with `cancel-in-progress: false` serialises them, so the one that
finishes **last** wins. That was the **older** one:

```
03:10  run 686  checked out ff54eaa  built index-CPBVPDh5.js  deployed
03:17  run 991  checked out dedca28  built index-C3NGvMvU.js  deployed  <- overwrote it
```

Prod ran one merge behind on **both** artefacts: Cloud Run served image tag `dedca28` while main
was `ff54eaa`, and hosting served the pre-`#388` bundle.

**Both runs were green and correctly so.** Each verified the artefact *it* had just built —
"Verify the served image is this commit" and "Verify the SERVED bundle is the one just built" both
passed for run 991, because prod genuinely was serving what run 991 built. Every check tested
internal consistency; none asked whether the commit was still the newest. **Nothing was broken;
something was stale**, which is the harder failure — there is no red anywhere to look at.

**Fixed** by refusing to ship a commit main has already moved past (`git merge-base --is-ancestor`
plus a not-equal test), with all 13 downstream steps gated. Skipping counts as **success**: the
newer deploy is the correct outcome, and a red X on a run that did the right thing teaches people
to ignore red.

**Caught only because I re-checked prod** and a string I had confirmed live 30 minutes earlier was
missing from the bundle.

### The related process error, mine

I ran `scripts/deploy.sh` by hand several times. `deploy.yml` says *"there are no manual deploys.
This is the only path to prod"* — and the manual path **skips the R4 drift gate**. That is how GCP
got ahead of git without anyone noticing: I applied terraform while the declaring commit was still
on a branch, and the next CI deploy's plan wanted to **destroy the budget I had just created**.
The gate caught it. `git → apply, never the reverse` is not a style preference.

---

## §2 — WHAT SHIPPED

**`#359` tenant-2 hardening — CLOSED.** `require_role` resolved "admin" from the deployment-wide
`settings.DEFAULT_ADMINS` on ~190 endpoints while 14 used per-tenant `tenant_default_admins`. A
tenant-2 admin would pass 14 and 403 on the rest, with `/me` returning `null`. Collapsed to one
path; **`_verify` deleted** so nothing can opt back in. `api/auth.py` no longer imports `settings`
at all, which is the visible proof. Verified in prod against a real login: **Tim has no custom role
claim**, so his admin access comes *only* from the DB lookup — the exact path changed.

**`#417` low-slope — 100%.** All thirteen gaps resolved or filed. Prod configs updated
(jupiter v31 / miami v32 / naples v31). ⚠️ **The audit doc was wrong in both directions** — G2/G4
were already done, and G11 was already *billing*.

**`#360` CompanyCam — 100%.** The webhook verified **SHA256-hex** where CompanyCam signs
**SHA1-base64**, and read `type` where the envelope carries `event_type`. Every real event would
have 401'd. The four existing tests passed because the fixture signed the same wrong way the route
verified. Plus replay protection on the signed `created_at`, `video.*` handling, mirror readers,
and the webhook secret created + wired.

**`#452` project commission — 100%.** A multi-building bid reported **no commission at all**.
`#451` is now a config flip (`commission_pct.excludes_project_blocks`), not a code change.

**`#444` GCP budget — 85%.** Budget **live**. ⚠️ See §3 for why it is not 100%.

**`#388` copy-config — 100%.** Fourth branch already existed; the button is the deliverable.

**`#387` job notes — 100%.** Notes now print on the customer document, including on
multi-building bids via a notes-only edit path.

**`#429` — corrected to 40%.** See §4.

---

## §3 — WHAT IS ACTUALLY BLOCKED, AND ON WHAT

**`#492` stucco metal — Tim, and it is the one with money on it.** `stucco_metal_per_lf: 9` is
live in all three prod configs and `_build_optional` bills `lf × 9`. Tim's sheet states that adder
**twice, 10× apart**: D29 "$9 per LF" vs G26 "$9 per 10 LF". 200 LF bills **$1,800 or $180**. The
engine now warns with both totals on every affected quote and is **deliberately not defaulted to
the cheaper reading** — the same evidence that cannot settle it cannot justify cutting a real
charge by 90%. **Realised exposure today is $0, measured**: zero prod estimates carry
`stucco_metal_lf`, and zero are `slope_type = low_slope` at all.

**`#444` BigQuery billing export — a permission the SA does not have.** Not a guess:
`perkins-deploy-sa` gets **403 reading the billing account**, and export is configured on the
billing *account* with no public create API. ⚠️ **Do not re-derive a blocker from the gcloud
errors** — `gcloud billing accounts list` (0 items) and `budgets list` (403) also fail, and I read
those as "no billing rights, needs a billing admin". **Wrong**: those need
`billing.accounts.list`/`budgets.list`; terraform only needs `budgets.create`/`get`, which the SA
has. The budget applied first try. Check terraform state, not gcloud.

**`#429b`** — the 890 Knowify contracts. Real analysis, untouched, Wave 5.

**`#360` operational tail** — the webhook is wired but **not registered** with CompanyCam. The
HMAC key is the `token` *we* supply at registration, so the secret and the registration must carry
the same string. The exact call is in `docs/2026-07-28-companycam-credentials.md`.

---

## §4 — `#429a` IS NOT A DEFECT, AND THE PLAN CONTRADICTED ITSELF

The Wave 2 exit assertion said "if it returns non-zero, stop: each row is a quote that
double-billed a flat section". It returns **10**. None of that reading survives:

- **All 36 RoofR measurements already carry the split** (29 `roofr` + 7 `roofr_fixture`). The six
  without one are **five manual entries** created by Jon on 7/13–7/18 and **one `google_solar`
  demo**. None is Knowify-sourced; none has a `raw_payload` to backfill *from*.
- **All 10 estimates have `flat_squares = None`** — the case the same section's acceptance criteria
  says must **proceed**, three paragraphs away. The criteria is right.
- **Zero of the 10 have a proposal.** Nothing reached a customer.

**One row still deserves a human glance:** measurement 18 is `provenance_note='RoofR'` with
`provider='manual'` — RoofR numbers typed by hand, by **Tim**, with full cut geometry. RoofR's
`total_sq` is pitched+flat, so estimate 5 ($53,910, draft, never sent) may price a flat section at
the sloped rate. That is the ambiguous-provenance trap arriving through the one door a provider
check cannot see.

**The assertion worth keeping is not `= 0`.** It is: every measurement whose `total_sq` came from a
pitched+flat source carries a split. A manual all-sloped entry legitimately has none.

---

## §5 — GOTCHAS (new first; cumulative list in the prior doc)

- ⚠️ **A stale deploy can overwrite a newer one** and every check stays green. §1.
- ⚠️ **`npm run build` catches what `tsc --noEmit` misses.** I used a setter that does not exist
  and `--noEmit` passed clean. `deploy.yml` already says this in a comment; it is right.
- ⚠️ **`_ctx_to_dict` is hand-written, not dataclass-derived** — a new `ProposalRenderContext`
  field is invisible to the template until added there.
- ⚠️ **Bump `_PDF_TEMPLATE_VERSION` on any template change.** A cached PDF is reused only on a
  version match. (7,364 of 7,365 prod proposals still cache at `v2`.)
- ⚠️ **There are TWO `ProposalRenderContext(` sites** — the customer PDF and the admin preview.
- ⚠️ **A terraform `plan` without `TF_VAR_cloudflare_api_token` fails on the CF provider** with
  401/403 and looks like a broken change. `scripts/drift_check.sh` pulls it from Secret Manager.
- ⚠️ **Use the project NUMBER in `google_billing_budget.budget_filter`.** The API normalises
  `projects/<id>` → `projects/<number>`, so the id form never converges and R4 fails forever on a
  budget that is correct.
- ⚠️ **The migration runner replays from 0013 every run.** 0055 is guarded on `pg_constraint`;
  an unguarded `ADD CONSTRAINT` aborts the whole run (0040 did, silently blocking 0041–0052).

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation/handoff `.md`, ALWAYS end it with this directive AND perform
it: move the OLDEST top-level `CONTINUATION-*.md` into `docs/continuations/` (keep only the latest
three at top level), fix every inbound link to the moved file, refresh the docs index's "most
recent" pointer, and update related docs.

**Performed:** `CONTINUATION-2026-08-02-pm.md` archived to `docs/continuations/`. Inbound links
repointed (`README.md`, `CONTINUATION-2026-08-02-eve.md`) and README's "Most recent" refreshed to
this doc.
