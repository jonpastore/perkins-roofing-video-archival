# Typed claim-grounding — design v2

Status: **v2 design, council-reviewed (GPT-5 + Grok, independently). Building the measurement
layer first; NOTHING gates or edits until precision is measured.**

## Why this exists

Grounding in Tim's own 801 videos IS the product. General roofing knowledge is commodity his
competitors generate in an afternoon. A confirmed miss: an article presented **Solar
Reflectance Index** — an ASTM standard with **0 hits across all 14,592 chunks** — as Tim's
expertise. It was caught only because a person read a log. That is not a control.

## What is already solved (do not re-solve)

Retrieval was starved: `hybrid_search(k=4)` + `chunk.text[:300]` gave the generator ~200 words
of Tim and demanded 1800+ — measured, 45,945 published words rested on 4,564 words of source.
Topic-slice retrieval fixed it: 4.5k–19k words per article, ratio ~10x invented → 0.11–0.50x.
**That upstream fix is what actually works.** Everything here is a check on the remainder.

## What failed, and the law it produced

A vocabulary-overlap guard fed `blocker` findings to an LLM reviser. It flagged 'Costs',
'Risk', 'Value' (Title-Case headings, plural mismatch), the reviser dutifully stripped them,
articles got worse, every check reported success.

> **Token presence is not claim support.** "Tim recommends replacing all shingles every 10
> years" is 100% his vocabulary and 100% invented.

## The v1 design that review killed

v1 was: model must quote its evidence, and we verify the quote appears verbatim in the
transcript, so it cannot bluff. GPT-5 and Grok independently found the same fatal flaw:

> **A verbatim quote proves the span EXISTS, not that it SUPPORTS the claim.**

| Claim | Real span it cites | What actually happened |
|---|---|---|
| "Tim recommends X" | "Some contractors recommend X" | attribution inversion |
| "Lasts 10–15 years" | "I've seen some fail in 10 to 15 years" | force reversed |
| "Never use Y" | "I'd almost never use Y in this case" | modality inflation |
| "ASTM D226 required in HVHZ" | one span has the code, another has HVHZ | stitched support |

All four pass a string match. v1 would ship **verified hallucinations with cleaner logs** —
the same bug as the vocabulary guard, in a smarter costume.

## v2 — the load-bearing change

**Never ask the model "does this span support the claim?"** That is a judgement, and a model
judging a model is what the three critic lenses already do (they answer "clean" to everything).

**Ask the model only to EXTRACT what the span states. Compare mechanically, in code.**

    claim:  {subject: "acrylic coating", measure: lifespan, value: 10–15, unit: years,
             qualifier: typical, condition: "south florida"}
    span:   "I've seen some fail in 10 to 15 years"
    model extracts: {subject: "some", measure: time_to_failure, value: 10–15, unit: years}
    code compares:  measure lifespan != time_to_failure  ->  NOT SUPPORTED

The model reports; the comparison is code. It cannot launder what it is not asked to judge.

## Claim taxonomy (atomic, typed, with slots)

Sentence-level claims with one anchor token were the second flaw: a sentence bundling three
claims launders two on the support of one. Claims are **atomic**.

| Type | Slots | Support rule | Risk |
|---|---|---|---|
| `number` | subject, measure, value, unit, qualifier, condition | value+measure+subject must all match | high |
| `code` | code_id, applicability, requirement | exact code id + applicability | **highest** (liability) |
| `product` | brand, sku, use | exact brand/sku, use must match | high |
| `place` | jurisdiction, assertion | jurisdiction + assertion | medium |
| `attribution` | speaker, stance, proposition | speaker must be Tim, stance must match | high |
| `modal` | proposition, force (always/never/must) | force must not exceed the source's | medium |
| `comparative` | a, b, dimension, direction | direction must match | medium |
| `causal` | cause, effect | both + relation | medium |
| `scope` | proposition, quantifier (all/most/some) | quantifier must not inflate | medium |

## Verdicts (not binary — v1's binary was a flaw)

- `SUPPORTED` — slots match a verified span
- `PARTIAL` — subject/measure match, qualifier or condition missing
- `INFLATED` — source says "sometimes", article says "always" (modality/scope inflation)
- `CONTRADICTED` — corpus says the opposite
- `OUT_OF_CORPUS` — Tim has never said it anywhere (the Solar Reflectance Index case)
- `UNSUPPORTED` — in-corpus vocabulary, no supporting span found
- `UNVERIFIABLE` — retrieval found no candidates (a retrieval failure, NOT an invention —
  conflating these makes a hard gate a randomiser)

`OUT_OF_CORPUS` and `CONTRADICTED` and `UNSUPPORTED` are three different diagnoses with three
different remedies. v1 called them all "unsupported".

## Retrieval for the verifier is its own problem

The generator's retrieval being fixed does NOT mean the verifier's recall is adequate — and
once this gates, a retrieval miss becomes a false "invention". Per claim type:
- codes/brands/numbers: **exact lookup first** (`Chunk.text ILIKE`), semantic search second
- expand to a neighbouring window around any hit (support is often one sentence away)
- contradiction search: look for opposing spans, not just supporting ones

## Action policy — report only, for now

**Nothing gates. Nothing edits.** The v1 predecessor drove edits from a detector whose
precision was never measured and made articles worse. Order of remediation, when it is
eventually earned:
1. localized sentence/span deletion (the claim is isolated)
2. section regeneration from its source packet (only if the section's thesis depends on it)
3. re-verify after

Never blind term deletion. Never whole-article revision (that caused 30-minute timeouts).

## Evaluation — the gate on the gate

Wiring to a gate requires measured precision on `number`/`code`/`attribution`, not vibes.
Seeded tests flatter the system because they match my imagination of failures, so the set is
**adversarial**:
- real quote, wrong implication ("some fail in 10-15 years" → "lasts 10-15 years")
- negation/hedge dropped ("almost never" → "never")
- code mentioned but wrong applicability
- number matched to the wrong subject
- attribution inversion ("some contractors" → "Tim recommends")
- corpus contradiction (one clip says X, ten say not-X)

Metrics: precision per claim type · recall on adversarial set · false-block rate ·
unsupported-escape rate · **harmful-edit rate** (removed supported facts, introduced new
unsupported claims, changed a recommendation's meaning).

## Known limits, stated up front

- **Goodharting.** Optimising "no unsupported claims" converges on bland sludge that says
  nothing checkable. The counter-metric is **minimum supported specificity** — an article
  must carry N verified specifics, not merely zero unverified ones.
- **Corpus inconsistency.** Tim has 801 videos over years; he changes his mind and misspeaks.
  One supporting clip against ten contradicting ones is cherry-picking. Hence `CONTRADICTED`.
- **ASR noise.** Transcripts are machine-made; a valid span can fail an exact match because
  the transcript is wrong. Normalisation is defined per claim type and deliberately narrow —
  over-normalising opens laundering loopholes.
- **This is post-hoc.** Both reviewers made the same architectural point: verification after
  free generation fights entropy. The real answer is **evidence-first generation** — the
  writer emits claim + source span + prose, and the checker validates pre-attached evidence.
  v2 is a measurement layer, not the destination.

## Build order

1. `core/claims.py` — pure: atomic extraction, slot model, mechanical comparison. No I/O.
2. `core/claim_verify.py` — retrieval + structured span extraction + verdicts.
3. `scripts/eval_claims.py` — adversarial set + precision/recall over all 31 articles.
4. **Measure. Publish the numbers. Only then** discuss gating.
