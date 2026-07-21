# "Pending Tim" resolution — most fields are recoverable NOW

Reviewed the admin-config "Pending Tim" fields. The large cluster is the
**Low-Slope group** (`EstimatingConfig.tsx` Group 5, `low_slope.*`), which the UI
says is "pending Tim's Exhibit B §4 values." Those values **already exist** in the
reviewed, locked document `legal/06-exhibit-B-pricing-engine-rules.pdf` §4 ("the
two reviewed low-slope sheets: HVHZ + FBC"). So they are resolvable without Tim —
transcribe Exhibit B into the config.

## RESOLVED from Exhibit B §4 → `low_slope.*` config

### §4.1 Base cost L&M ($/SQ) → `low_slope.base_cost_lm[zone][roof_type]`
| System | $/SQ |
|---|---|
| Polyglass SAV / SAP (Peel & Stick) | 475 |
| Adhered TPO | 485 |
| Mech. Attached TPO | 485 |
| PB Acrylic Coating (2 white coats, incl OH+P) | 375 |
| PB Premium Coat (Acrylic, incl OH+P) | 550 |
| PB Silicone (1 coat, incl OH+P) | 445 |
| PB Silicone (2 coats, incl OH+P) | 515 |
| Stockmeier Polyurethane (2 coats, incl OH+P) | 595 |

### §4.2 Overhead ($/SQ) → `low_slope.overhead[zone][oh_key]` (+`wood_deck_oh_adder`)
| Surface | $/SQ |
|---|---|
| Flat Roof | 155 |
| TPO Roof | 135 |
| Coatings (in-house) | 95 |
| **Wood deck adder** | **+45** (concrete is default) → `wood_deck_oh_adder = 45` |

### §4.3 Insulation ($/SQ, no profit) → `low_slope.insulation_tiers` + `tapered_cost_per_sq`
| Type | $/SQ |
|---|---|
| 1" board | 255 |
| 1½" board | 275 |
| 2" board | 310 |
| Tapered system ($100 L + $300 M, no OH/profit) | 400 → `tapered_cost_per_sq = 400` |
| Additional layers | +75/SQ per extra layer |

### §4.4 Deck type ($/SQ) → `low_slope.deck_types[deck_type]`  (fixes Quoting.tsx "Pending Tim — no deck rates configured")
| Deck | $/SQ |
|---|---|
| BUR or TPO Concrete (asphalt/TPO primer) | 15 |
| BUR Wood (WB-3000 primer; not HVHZ; 1 story) | 35 |
| BUR Wood (SA-V flashing strips; not HVHZ; plywood only) | 55 |
| BUR Wood (Elastobase, nails, tin caps) | 110 |
| TPO Wood (VersaShield Solo) | 135 |
| TPO Wood (DensDeck & ISO) | 120 |

### §4.5 Roof height ($/SQ) — 1–4 stories $0; 5+ = crane (manual); 2+ trash chute $1,500 + sections
### §4.6 Tear-off extras ($/SQ per layer) → `low_slope.tear_off_per_layer_per_sq`
Additional hauling $20 + Labor $20 + OH $35 = **$75/SQ per additional layer** (confirm whether the config field wants the $75 combined or just the $35 OH split — check `core/pricing_config.py:297 low_slope_tear_off_cost` usage).

## Also already resolved (found this session, not actually pending)
- **T&C text** (`core/tc_seed.py`, `proposal_render.py:176` "pending Tim sign-off"): the real 49-clause T&C is in GCS `gs://…-media/tenants/1/contracts/josh_proposal_terms_2026-07-11.pdf` (+ .txt). Load as the tenant TcVersion; just confirm it's the current wording.
- **Tile roof-cuts (hips/valleys/rakes/wall)**: decoded — see `tile-roof-cuts-pricing-linkage.md`.
- **Gutters**: 16/16 already tracked & correct (`seed_gutters_config.py`).

## GENUINELY needs Tim (can't derive) — with sheet references

Sloped calculator sheet (has comments + formulas):
`https://docs.google.com/spreadsheets/d/1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig/edit`
Tabs: `Tim (HVHZ)`, `FBC (Palm/Lee/St.Lucie)`, `Custom Tile Calc`, `Marco`, `Josh`, `OH Metrics`, `Jupiter`.

1. **Low-slope HVHZ-vs-FBC delta:** Exhibit B §4 gives ONE low-slope table, but the
   config is per-zone (`[zone]`) and §4 is titled "HVHZ + FBC variant." Confirm the
   FBC low-slope base costs are identical to HVHZ, or if FBC is cheaper (sloped §5.2
   is ~$10–20/SQ lower than §5.1). → Tim, or compare the two low-slope source sheets.
2. **Per-brand rake-tile unit** (tile roof-cuts): `Custom Tile Calc` cells B35/E35/B42/E42
   show $4.30 / $5.78 / $19.14 by tile brand — confirm the brand→unit mapping.
3. **Gutter hangers** (7" Alum K-Style "plus hangers") + **whether 4×5 downspouts
   ($10.50) bill separately** — not on the gutters sheet; ask Tim directly.
4. **`Jupiter` branch** low-slope/tile values if that branch differs (tab exists;
   `Custom Tile Calc` row 2 notes "Jupiter Branch (every 17.5 SQ)…").

## Seeding plan (blocked on weekly model limit — resets 6am ET)
Extend/author the low-slope seed with the §4 values above, keyed by zone
(HVHZ + FBC, pending item 1) and roof_type; verify against `core/pricing_config.py`
getters; behavioral test that a low-slope quote no longer raises ConfigError.
Route to a sonnet executor after reset.
