# Local model review post-mortem — 2026-08-01

What the free local fleet contributed to the R2 review of #430 slice 2, measured against what the
two Claude reviewers found on the same diff. Written to improve the fleet, not to retire it — the
operational fixes at the end are cheap and would remove most of the wasted cycles.

**Headline: on this task the local models were net-negative.** Between them they produced **1**
genuine finding and **4** fabricated ones, one of which was labelled CRITICAL with a `BLOCKED`
verdict. Verifying the fabrications cost more than the one real finding saved.

| | qwen3.6-think | gpt-oss-120b-think | Claude architect | Claude critic |
|---|---|---|---|---|
| findings reported | 6 | 12 | ~20 | ~18 |
| genuinely real | 0 | 1 | 15+ | 12+ |
| **fabricated** (cite code that does not exist) | **3** | **2** | 0 | 0 |
| CRITICAL/HIGH found | 0 real | 1 real of 4 claimed | 3 HIGH | 2 CRITICAL |
| false "verified correct" on a real defect | 1 | — | — | — |
| invocations needed | 1 | 3 | 1 | 1 |

Both CRITICALs in this wave — an alt-text injection that published un-sanitized GPS-stamped
photos past the privacy gate, and a GPS regex that missed the format the system exists to strip —
were found only by Claude. Neither local model came near either.

---

## 1. qwen3.6-think — fabricated a CRITICAL and returned BLOCKED

### What it claimed

> **Severity: Critical** — `project_quote()` … Multiple runtime crashes due to incorrect object
> attribute access:
> 1. `quote_snapshot=r.quote_snapshot` → `r` is a dict … Dicts do not support dot notation.
> 2. `sum(b.quote.num_squares for b in built)` → `built` contains `Estimate` ORM instances …
>    The `Estimate` model has `input_json` and `quote_snapshot` columns, **not** a `.quote`
>    attribute.
> 3. `zip(body.buildings, roll_up["buildings"], strict=True)` → The third unpack variable `est`
>    is immediately shadowed …
>
> **Impact:** Endpoint crashes 100% of the time on both `persist=True` and `persist=False` paths.
>
> **VERDICT: BLOCKED**

### What is actually true

| claim | reality |
|---|---|
| `r.quote_snapshot` exists in the endpoint | **The string `quote_snapshot` appears nowhere in `api/routes/estimator.py`.** Verified by grep. |
| `built` contains `Estimate` instances | `built: list[BP.Building]`, built by `built.append(BP.Building(...))`. `Building` is a dataclass with a `.quote` field. `b.quote.num_squares` is correct. |
| the `zip` has three unpack targets | `for item, priced in zip(body.buildings, roll_up["buildings"], strict=True):` — **two** targets. |
| "crashes 100% of the time" | 11 endpoint tests passed at the time, plus a live-config run against the prod pricing config. |

Three of its six findings describe code that does not exist. It then rated the composite CRITICAL
and issued a blocking verdict.

### The more dangerous failure: a false "verified correct"

Section 4 marked `_statements()` **"Severity: None (Verified Correct)"** and listed edge cases it
had "tested mentally", including `SELECT $$;$$;`. It did **not** notice that the implementation
handled only bare `$$` and would mis-split a tagged `$func$ … $func$` block — a real defect the
Claude architect found, and one that sends broken SQL fragments **to production**. Measured
against the pre-fix implementation, that case produced **4 statements instead of 2**.

A wrong "BLOCKED" costs an hour. A wrong "verified correct" on a prod-facing SQL parser is the
failure mode that actually ships.

### Prior incident

`~/.claude` memory, 2026-07-31: *"qwen3.6 passed all three review areas as 'Correct' and was wrong
twice."* Same model, same category of failure, one day apart. The pattern is now: **it does not
reliably distinguish reading code from imagining it, in both directions.**

### Credit where due

It correctly flagged that `scripts/portfolio_grant_permissions.py` was absent from its input and
said so rather than inventing a verdict on it — *"Script content is missing from the diff, so
direct verification is impossible."* That was **my** input error (I sent it the diff only, to stay
under its context ceiling), and refusing to review what it could not see is exactly right. It also
correctly confirmed the `_quote_input_from_request` extraction as behaviour-preserving, matching
both Claude reviewers.

---

## 2. gpt-oss-120b-think — 12 findings, 1 real

### The one real find (kept, fixed)

> **HIGH** … `project_quote` accepts any integer for `property_id` without verifying that the
> property belongs to the current tenant.

**Correct and non-obvious.** Postgres evaluates FK constraints with row security **bypassed**, so
RLS on `properties` never prevented a bid referencing another tenant's property — it only
prevented reading it back. Neither Claude reviewer raised it. Fixed with a `db.get(Property, …)`
check and a test. This is the whole positive contribution of the local fleet on this task, and it
is a good one.

### The fabrications

| claim | reality |
|---|---|
| `core/migration_runner.py` — `_statements()` "naively splits on ';'" | **That file does not exist.** The splitter lives in `scripts/apply_migrations_connector.py`, and the diff it was given contained the *rewritten* version that handles strings, comments and dollar-quotes. It described the pre-fix behaviour as current, citing a path it invented. |
| `_quote_input_from_request` "accepts a `claims` argument but never uses it" | Used on line 76 of that function: `debug = bool(body.debug) and can(claims.get("role"), "estimating_manage")`. |

### The mis-framings

- Rated `branch: max_length=100` a **HIGH regression** ("previously the request succeeded"). It is
  a deliberate fix for a failing meta-test; the previous behaviour was a 500 on Postgres. It read
  a fix as a defect because it had no history.
- Rated `estimating_view` on a writing endpoint **CRITICAL**. `/quote` already persists an
  `Estimate` under the same role, so it is existing precedent, not a new gap. Worth a design
  conversation; not critical.
- Re-reported per-building `config_id` as HIGH when it was already fixed in the working tree —
  **my fault**, I sent it a diff snapshot taken before that fix.

### Its usable minor findings

Duplicate building names and duplicate `project_items` keys are both unvalidated. Real, LOW,
worth doing.

---

## 3. Operational failures — these are the cheap wins

These cost three invocations and roughly 25 minutes of wall-clock before any review content
existed. All are fixable in the tooling.

### 3.1 `llm` passes the whole prompt as a curl argv

```
/home/jon/.local/bin/llm: line 36: /usr/bin/curl: Argument list too long
```

`~/.local/bin/llm:36` builds `BODY` then calls `curl … -d "$BODY"`. A 125 KB prompt exceeds
`ARG_MAX` and dies. **Fix:** write the JSON to a temp file and use `curl -d @file`. Two-line
change, removes a whole class of silent failure on exactly the large-context reviews the fleet is
best suited to.

### 3.2 The documented context ceiling is wrong for this model

`~/.claude/fleet-reference.md` / CLAUDE.md say *">40k context → amd-halo `qwen3-coder`
(65536 usable)"*. `gpt-oss-120b-think` actually reports:

```
ContextWindowExceededError: request (33028 tokens) exceeds the available context size (32768)
```

**32,768, not 65,536.** There is no preflight — you discover it with a 400 after building the
whole request. **Fix:** record the real per-model ceiling, and have `llm` estimate tokens and warn
before POSTing.

### 3.3 The empty-return trap fired twice, exactly as documented

```
finish_reason: length | content chars: 0 | reasoning_content chars: 41,242
```

With `max_tokens: 9000` the model spent the entire budget in the thinking channel and returned
empty content — no error. This is already written down in CLAUDE.md, and it still cost two
invocations because there is no guard. **Fix:** `llm` should detect `finish_reason == "length"`
with empty content and say *"thinking budget exhausted — raise max_tokens or lower
reasoning_effort"* rather than printing the generic `[empty content]` hint. Setting
`reasoning_effort: "medium"` with `max_tokens: 16000` is what finally worked (521 s).

### 3.4 No way to see the reasoning when content is empty

41 KB of reasoning existed and was discarded because `llm` prints only `message.content`. A
`--show-reasoning` flag would have salvaged the first two runs.

---

## 4. Root causes

1. **No grounding check.** Both models asserted the contents of specific lines without those lines
   existing. Nothing in the pipeline requires a finding to quote the code it describes.
2. **Confidence is uncorrelated with correctness.** qwen's fabricated finding carried the highest
   severity and a blocking verdict; its "Verified Correct" covered a genuine prod-facing bug.
3. **No history.** Both read a deliberate fix as a regression because they see a diff with no
   commit messages, no test names, no issue context.
4. **Stale input is my error, not theirs.** Two "findings" were already-fixed items because I sent
   a snapshot diff. A review harness should generate the diff at invocation time.

---

## 5. Recommendations

**Tooling (do these first — cheapest, highest value)**

1. `llm`: POST from a file (`-d @-`), not an argv. Fixes 3.1 outright.
2. `llm`: detect `finish_reason == "length"` + empty content and print an actionable message.
3. `llm`: add `--show-reasoning` so a truncated run is still worth something.
4. Record real per-model context ceilings; preflight the token estimate and fail fast.

**Prompting**

5. **Require evidence per finding**: "quote the exact line you are describing; if you cannot quote
   it, do not report it." This alone would have suppressed 4 of the 5 fabrications.
6. Ask for a **confidence** field and instruct that anything below high be labelled UNSURE. The
   review prompt used here already asked for UNSURE and neither model used it once.
7. Feed a **freshly generated** diff, plus the relevant test file, so "already fixed" cannot occur.
8. Tell the model which changes are deliberate fixes, so it stops grading them as regressions.

**Routing**

9. Keep local models for **bulk and mechanical** work — summaries, scaffolding, doc drafts,
   research first-passes — where a fabrication is visible and cheap.
10. **Never let a local model gate a decision**, and do not spend Claude cycles verifying local
    output on security- or money-critical paths — on this task, verification cost more than the
    review returned. The existing CLAUDE.md rule ("local review is a second opinion, NEVER a
    gate") held and should be tightened to: *for CRITICAL/security review, do not invoke them at
    all.*
11. Re-measure after the tooling fixes. The `property_id` find shows the capability is real when
    the plumbing works; three of four failures above were plumbing, not reasoning.

---

## Appendix — verification commands

```bash
# qwen's three fabrications
grep -n "quote_snapshot" api/routes/estimator.py          # no match
grep -n "zip(" api/routes/estimator.py                    # two targets
grep -n "built: list" api/routes/estimator.py             # list[BP.Building]

# gpt-oss's two fabrications
ls core/migration_runner.py                               # does not exist
awk '/^def _quote_input_from_request/,/^    return q,/' api/routes/estimator.py | grep claims

# gpt-oss's real find
grep -n "property_id" api/routes/estimator.py
```

Raw outputs are in the session scratchpad: `review_qwen.txt`, `review_gptoss.txt`,
`gptoss_resp.json`.

---

# Follow-up — same day, after the fixes

Every tooling recommendation above shipped, and rec #11 was executed. **The re-measure contradicts
this document's closing optimism.**

## What shipped

`llm` is no longer an unbacked script in `~/.local/bin`; it is versioned at
`deployments/litellm/llm` in morpheus-mono-repo, alongside the gateway config it talks to.

| rec | fix |
|---|---|
| 3.1 / #1 | Body POSTed on stdin (`curl -d @-`). The JSON builder had the same argv bug and was fixed too — the first attempt just moved `Argument list too long` from curl to python. A 132KB prompt now round-trips. |
| 3.2 / #4 | Dropped `curl -f`, which was discarding the 400 body. The gateway's own `ContextWindowExceededError: request (54213 tokens) exceeds the available context size (32768)` now prints verbatim. No per-model ceiling table to maintain and rot — the server already knows. |
| 3.3 / #2 | `finish_reason == "length"` with empty content now reports `thinking budget exhausted — N chars of reasoning, 0 of content`, and `$LLM_MAX_TOKENS` is settable so the advice is actionable. |
| 3.4 / #3 | `--show-reasoning`. |
| #5, #6, #8 | `--review` prepends grounding rules: `EVIDENCE: <verbatim line>` before every finding, HIGH/UNSURE labels, no verdicts, and an explicit ban on claiming code is correct. |

New: **`llmcheck`** greps every `EVIDENCE:` line against the source tree and exits 1 on any that is
not there. **The oracle is the filesystem, not the internet** — every fabrication in §1 and §2 was a
claim about this repo, which no search engine can check. Against those documented fabrications it
catches 4/4 of the ones citing non-existent code.

Two bugs found while testing it, both fixed:

- Quotes matched **this post-mortem**, which reproduces the fabrications verbatim — the fabrication
  validated itself out of the document describing it. Prose (`*.md`, `*.rst`, `*.patch`) is now excluded.
- A model emitted `EVIDENCE: <real line>` followed by a bare `HIGH` with no finding attached, and
  llmcheck passed it green. It now measures the claim, not just the citation.

## Rec #11 re-measured — the answer is negative

Re-ran the slice 2 review against `472bd78` (13.5k tokens), scored on the ground truth recorded above:

| | with `--review` + llmcheck | control, no rules |
|---|---|---|
| qwen3.6-think | `NO FINDINGS` — 0 fabricated, 0 real | 6 findings, **3 provably false**, 0 real |
| gpt-oss-120b-think | could not run — 13.5k in + 71k chars of reasoning ≫ 32768 ctx | — |
| gpt-oss-120b | `EVIDENCE:` + `HIGH` with no finding attached | — |

The control reproduces this document's original score — 6 reported, 0 real, 3 fabricated — on the
same model and the same diff. That is the result that matters: the grounding rule **suppresses**
fabrications rather than the model having had nothing to say. It generates plenty. It simply cannot
cite it, so it now declines instead.

So §5's hopeful line — *"the capability is real when the plumbing works; three of four failures were
plumbing, not reasoning"* — is **not supported**. The fixes bought speed of failure, not signal:
what cost 3 invocations, ~25 minutes and a fabricated `BLOCKED` verdict now returns nothing in one
shot at $0, and the paths that still fail say why.

Limits: n=1 diff. The two CRITICALs are not in this commit, and the `property_id` find could not be
re-tested — it was folded into `472bd78` before it landed, so no committed diff still contains that
defect. This measures fabrication rate well and recall barely.

## Standing rule

Rec #10 tightened as recommended, in `~/.claude/CLAUDE.md`: **do not invoke a local model for
CRITICAL or security review at all**, not even as a second opinion. Local review is for bulk and
mechanical passes where a fabrication is cheap and obvious. And `NO FINDINGS` from a local model
means *no information* — never "clean". It is not permitted to assert that anything is correct,
because the most dangerous failure in §1 was exactly that assertion.
