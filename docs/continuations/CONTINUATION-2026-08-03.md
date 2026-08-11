# CONTINUATION — 2026-08-03

**`main` = `b3b8144`. DEPLOYED AND VERIFIED LIVE: API `platform:b3b8144` (tag matches main), SPA
bundle `/assets/index-CPfttX26.js`. Zero open PRs, clean tree.** Live pricing configs: jupiter
**v31**, miami **v32**, naples **v31**. Migrations through **0055**, applied. GCP spend budget
**live** ($200/mo, thresholds 0.5/0.8/0.9/0.95) — this project had none at all before today.

Follows `docs/continuations/CONTINUATION-2026-08-02-night.md` (a backlog audit). This session executed what that
audit found. Six tasks closed. **The most useful output is not a feature — see §0.**

---

## §0 — THE PATTERN. READ THIS BEFORE STARTING ANYTHING.

**Five separate defects were the same shape: a correct thing that nothing could reach.** Not one
was a wrong value.

| | the correct part | what could not reach it |
|---|---|---|
| `#417` G3/G9 | right values in config, incl. all three ACTIVE prod configs | **no code read them** — and `_note_stockmeier_floor` claimed it was "now enforced as a warning" |
| `#417` inputs | engine, config and prod deploy all correct | **`QuoteRequest` could not express them** — Pydantic drops unknown keys, endpoint returns **200**, lines silently absent |
| `#388` `gc` branch | exists, active, "Perkins Construction" since migration 0041 | **no active pricing config** → estimator 503s, so the branch was selectable and dead |
| `#387` notes | `quote_snapshot.notes` was read | by `_assemble_review_text`, which feeds the **AI review** — not the customer document. All four doc renderers ignored it |
| `#444` budget | `google_billing_budget` in `main.tf` for weeks | **`cloudbilling` + `billingbudgets` missing from `required_apis`**, so the account id its `count` guard waited on was unreadable |

**In four of the five, something ASSERTED it was done** — a config note, a green test suite, a
tracker entry, a `count` guard that read as merely waiting on a variable.

**Every one was caught by exercising the running system.** None by reading code. None by the test
suite. The checks that actually work:

- config rule → grep for the **reader** (accessor, call site), never the key
- new engine input → **call the real endpoint** and assert the line appears; a 200 proves nothing
- new config key → confirm it exists in **PROD's active config**, not just the fixture
- renderer field → establish **which** renderer; `_assemble_review_text` is not the contract
- terraform → **`plan` AFTER `apply`**; "Apply complete!" is not convergence

Write two tests that fail for **different** reasons — one that the surface can express the thing,
one that it forwards it. A field that parses and is discarded fails as silently as one never
declared.

---

## §1 — ⚠️ A STALE DEPLOY OVERWROTE A NEWER ONE AND EVERY CHECK WAS GREEN

PRs #21 (`dedca28`) and #22 (`ff54eaa`) merged minutes apart. Each merge ran `ci`; each `ci`
completion triggered a deploy **checked out at its own triggering commit** — what `deploy.yml`'s
`ref:` deliberately asks for. `concurrency` + `cancel-in-progress: false` serialises them, so
whichever finishes **last** wins. That was the **older** one:

```
03:10  run 686  checked out ff54eaa  built index-CPBVPDh5.js  deployed
03:17  run 991  checked out dedca28  built index-C3NGvMvU.js  deployed  <- overwrote it
```

Prod ran one merge behind on **both** artefacts. Both runs were green **and correctly so**: each
verified the artefact *it* had just built. No check asked whether the commit was still newest.
**Nothing was broken; something was stale**, which is harder — there is no red anywhere.

**Fixed**: a `Skip if this commit is already superseded on main` step (`git merge-base
--is-ancestor` + not-equal), with all 13 downstream steps gated. Skipping counts as **success** —
a red X on a run that did the right thing trains people to ignore red.

⚠️ **THE GUARD HAS NOT BEEN GENUINELY EXERCISED.** The merge that shipped it had only one deploy
in flight. **Next time two PRs merge close together, check the superseded run for the `::notice`**
rather than assuming it works.

### The related error, mine

I ran `scripts/deploy.sh` by hand several times. `deploy.yml` says *"there are no manual deploys.
This is the only path to prod"* — and the manual path **skips the R4 drift gate**. That is how GCP
got ahead of git: I applied terraform while the declaring commit was still on a branch, and the
next CI plan wanted to **destroy the budget I had just created**. `git → apply, never the reverse`
is not a style preference.

---

## §2 — CLOSED THIS SESSION (all verified live in prod)

| task | what it was | verified |
|---|---|---|
| **#359** | `require_role` resolved admin from the deployment-wide `DEFAULT_ADMINS` on ~190 endpoints vs 14 on the per-tenant DB path — a tenant-2 admin 403s nearly everywhere, `/me` returns null. Collapsed to one path, **`_verify` deleted**, `api/auth.py` no longer imports `settings` | **Tim has NO custom role claim**, so his admin access runs only through the changed lookup — and he resolves to admin in prod |
| **#360** | webhook verified **SHA256-hex** where CompanyCam signs **SHA1-base64**, and read `type` not `event_type`. Every real event would have 401'd; the four existing tests passed because the fixture signed the same wrong way the route verified | 8 tests incl. one asserting the OLD scheme is rejected |
| **#417** | all 13 low-slope gaps | Stockmeier warns · cover board $3,900 · warranty $175/sq · pressure cleaning $30/sq |
| **#452** | a multi-building bid reported **no commission at all** | commission **$1,250** where it was previously absent |
| **#387** | notes reached the AI reviewer and **never the signed contract** | notes editor in the served bundle |
| **#388** | 4th branch already existed; the copy-config button was the deliverable | panel in the served bundle |

**Prod verification recipe** (this is what caught the stale deploy — use it):

```bash
git rev-parse --short main
gcloud run services describe api --region us-central1 \
  --format='value(spec.template.spec.containers[0].image)'      # tag must equal main
B=$(curl -s https://app.perkinsroofing.net/ | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1)
curl -s "https://app.perkinsroofing.net$B" | grep -c 'Copy pricing config'   # a feature string
```

---

## §3 — WHAT IS NEXT AND NOT BLOCKED

**`#342` eval harness — the strongest unblocked item.** `evals/` is confirmed **absent**. Build
recall@k / precision@k / groundedness over the 832-video corpus, wired to CI. Supersedes #333
(`app/eval.py`, never wired, never run). This is the **missing instrument for a known-broken
thing**: memory `claim-checker-retrieval-broken` records the claim checker measured at **0/3
precision**, and every grounding fix so far shipped unmeasured. No external dependency.

**`#429b` — 890 Knowify contracts.** Real analysis, untouched, Wave 5. `scripts/
mixed_roof_sold_analysis.py:56,61` iterates `entity='deliverables'` / `ContractId`.
⚠️ **Knowify deliverables carry `ContractId`, NOT `ProjectId`** — the wrong join once returned a
clean, confident, wrong answer. Money is in **CENTS** on the MCP path, dollars on the mirror.

**`#402` aluminum link (~5 min)** and **`#382` metal warranty page / setback → WP plugin.** Both
buildable; `wp-plugin/perkins-metal-warranty/` already exists. ⚠️ Content lands on **staging**
until the WordPress cutover (`#456`, Jon's) — build them, but do not report them as customer-facing.

**`#459`** — asks to split `#429`. Half of it is already answered: see §4. Closing or re-scoping it
is a 2-minute tracker fix, not work.

---

## §4 — `#429a` IS NOT A DEFECT, AND THE PLAN CONTRADICTED ITSELF

The Wave 2 exit assertion said "if it returns non-zero, stop: each row is a quote that
double-billed a flat section." It returns **10**. None of that reading survives:

- **All 36 RoofR measurements already carry the split** (29 `roofr` + 7 `roofr_fixture`). The six
  without one are **five manual entries** created by Jon on 7/13–7/18 and **one `google_solar`
  demo**. None is Knowify-sourced; none has a `raw_payload` to backfill *from*.
- **All 10 estimates have `flat_squares = None`** — the case the same section's acceptance criteria
  says must **proceed**, three paragraphs away. The criteria is right; the assertion is wrong.
- **Zero of the 10 have a proposal.** Nothing reached a customer.

**One row deserves a human glance:** measurement 18 is `provenance_note='RoofR'` with
`provider='manual'` — RoofR numbers typed by hand, **by Tim**, with full cut geometry. RoofR's
`total_sq` is pitched+flat, so estimate 5 ($53,910, draft, never sent) may price a flat section at
the sloped rate. The ambiguous-provenance trap through the one door a provider check cannot see.

**The assertion worth keeping is not `= 0`** — it is: every measurement whose `total_sq` came from
a pitched+flat source carries a split. A manual all-sloped entry legitimately has none.

---

## §5 — BLOCKED, AND ON WHAT EXACTLY

**`#492` stucco metal — Tim. The only open item with money on it.** `stucco_metal_per_lf: 9` is
live in all three prod configs and `_build_optional` bills `lf × 9`. His sheet states the same
adder **twice, 10× apart**: D29 "$9 per LF" vs G26 "$9 per 10 LF". 200 LF bills **$1,800 or $180**.
The engine warns with both totals on every affected quote and is **deliberately not defaulted to
the cheaper reading**. **Realised exposure is $0, measured** — zero prod estimates carry
`stucco_metal_lf`, and zero are `slope_type = low_slope` at all. Cheap to settle *now*.

**`#444` (85%) BigQuery billing export — a permission the SA does not have.** `perkins-deploy-sa`
gets **403 reading the billing account**; export is configured on the billing *account* and has no
public create API. ⚠️ **DO NOT re-derive a blocker from the gcloud errors.** `gcloud billing
accounts list` (0 items) and `budgets list` (403) also fail, and I read those as "no billing rights,
needs a billing admin". **Wrong** — those need `billing.accounts.list`/`budgets.list`; terraform
only needs `budgets.create`/`get`, which the SA **has**. The budget applied first try. **Check
terraform state, not gcloud.** The card move to Marie is separately Jon's.

**`#504` register the CompanyCam webhook (~10 min, operational).** Code + secret are done and
deployed. One call to their create-webhook endpoint: `url=https://api-jnr6bsxyea-uc.a.run.app/
companycam/webhook`, `token=` the value of `companycam-webhook-secret`, scopes `photo.*` + `video.*`.
⚠️ **CompanyCam does not issue that token — we supply it**, so the secret and the registration must
carry the same string or every event 401s with a signature mismatch as the only symptom. Recipe in
`docs/2026-07-28-companycam-credentials.md`.

**`#456` WordPress cutover — Jon + Wendy.** Gates the entire content wave; prod's newest post is
still 2026-07-02.

---

## §6 — GOTCHAS (new first; the cumulative list is in the prior doc)

- ⚠️ **A stale deploy can overwrite a newer one** and every check stays green. §1.
- ⚠️ **`npm run build` catches what `tsc --noEmit` misses.** I used a setter that does not exist
  and `--noEmit` passed clean. `deploy.yml` says this in a comment; it is right.
- ⚠️ **`_ctx_to_dict` is hand-written, not dataclass-derived** — a new `ProposalRenderContext`
  field is invisible to the template until added there.
- ⚠️ **Bump `_PDF_TEMPLATE_VERSION` on ANY template change.** A cached PDF is reused only on a
  version match. (7,364 of 7,365 prod proposals still cache at `v2`.)
- ⚠️ **There are TWO `ProposalRenderContext(` sites** — the customer PDF and the admin preview.
- ⚠️ **A terraform `plan` without `TF_VAR_cloudflare_api_token` fails on the CF provider** with
  401/403 and looks like a broken change. `scripts/drift_check.sh` pulls it from Secret Manager.
- ⚠️ **Use the project NUMBER in `google_billing_budget.budget_filter`.** The API normalises
  `projects/<id>` → `projects/<number>`, so the id form never converges and R4 fails forever on a
  budget that is correct.
- ⚠️ **The migration runner replays from 0013 every run.** 0055 is guarded on `pg_constraint`; an
  unguarded `ADD CONSTRAINT` aborts the whole run (0040 did, silently blocking 0041–0052).
- ⚠️ **The commit hook needs `Refs #N <pct>%` alone on its line** — trailing prose breaks the regex.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation/handoff `.md`, ALWAYS end it with this directive AND perform
it: move the OLDEST top-level `CONTINUATION-*.md` into `docs/continuations/` (keep only the latest
three at top level), fix every inbound link to the moved file, refresh the docs index's "most
recent" pointer, and update related docs.

**Performed:** `CONTINUATION-2026-08-02-pm.md` archived to `docs/continuations/`. Inbound links
repointed in `README.md` (markdown link) and `CONTINUATION-2026-08-02-eve.md` (**prose reference**
— a different form that a link-only sweep misses). README's "Most recent" refreshed to this doc,
and every continuation link in README verified to resolve.
