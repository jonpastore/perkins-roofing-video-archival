# Low-slope comment audit — Tim's 69 cell comments vs our config (2026-07-25)

**Source:** live low-slope sheet `1hTGWCWzIVLgWwNFln_AYBnEcKkj0tLbaZiv82zHXWWQ`
("**Low-Slope Roof Price Calculator", tabs Tim / Josh / Marco / Overhead Metrics / Jupiter).
Our docs cite `1SGLYoO…` — that is the *copy*, which carries zero comments. Use the id above.

**Method.** The Drive comments API returns opaque anchors (`{"type":"workbook-range","range":"1942286937"}`),
so a comment cannot be tied to a cell from that API alone. Exporting the sheet as `.xlsx`
(`files.export_media`, `…spreadsheetml.sheet`) yields `xl/threadedComments/*.xml`, which carries a real
`ref="H17"` per comment. Every comment below is anchored to a **cell**, not guessed from its quoted value —
`quotedFileContent` is a snapshot from when the comment was written and is stale on the old ones.

Artifacts: `~/perkins-corpus/tim_lowslope_comments_by_cell.json` (78 nodes incl. replies, cell + row
context + tab). The Tim/Josh/Marco tabs are three copies of one price guide — only the calculator inputs
in column A/B differ — so **there is one low-slope table, no zone split**, which confirms the fixture's
`_note_fbc_deltas`.

Config under audit: `infra/fixtures/pricing_config_exhibit_b.json` → `low_slope`, and
`core/estimator.py::_build_low_slope`.

---

## 1. Confirmed — the comments back what we already ship

Each of these is a build-up in a comment that sums to the headline we use. This is the same
"comments are the source of truth" test the sloped sheet got, and low-slope passes it.

| our config | value | comment evidence (cell) |
|---|--:|---|
| `deck_types.bur_wood_wb3000` | 35 | H13: $15 WB-3000 primer + $20 extra L = **$35** |
| `deck_types.bur_wood_sav_flashing` | 55 | H14: $26 SAV strips + $25 extra L = $51 ≈ $55 |
| `deck_types.bur_wood_elastobase` | 110 | H15: $75 elastobase + $15 nails/tin-caps + $20 L = **$110** |
| `deck_types.tpo_wood_versashield` | 135 | H16: $110 VersaShield Solo + $25 L = **$135** |
| `deck_types.tpo_wood_densdeck_iso` | 120 | H17: $98 ¼" SecuRock + $20 L = $118 ≈ $120 |
| `insulation_tiers` 1" | 255 | K15: $85 board + $70 Olybond = $155 M, +$50 L +$50 OH = **$255** |
| `insulation_tiers` 1.5" | 275 | K16: $105 + $70 = $175 M → **$275** |
| `insulation_tiers` 2" | 310 | K17: $140 + $70 = $210 M → **$310** |
| `base_cost_lm.polyglass_sav_sap` HVHZ | 475 | E25 build-up + E21–E24 column ($50 + $130 + $35 + $260) |
| `base_cost_lm.*` FBC polyglass | 450 | **F24 cell: "-$25 FBC (no FR)"** — cell-level evidence for the $25 delta |
| `pressure_cleaning.flat` | 30 | O1: $20 L/OH + $5 M + $5 P = **$30** |
| `pressure_cleaning.sloped` | 40 | O2: $30 L/OH + $5 M + $5 P = **$40** |
| TPO membrane material | 270 | H24 / I24 both build to $267–270 w/ 10% waste |
| silicone 1/2/3-coat | 445/515/645 | O22/O23/O24 material build-ups $195/$220/$300 match N-column |
| `wood_deck_oh_adder` | 50 | A10 "Wood Deck OH - add $50". ⚠ the block header G1 still reads **"add $45 OH for wood"** — the sheet contradicts itself; A10 is newer and is what we use. |

---

## 2. Gaps — in Tim's comments, absent from our engine

Ranked by exposure.

> **STATUS, updated 2026-08-02 (#417).** The original line here read *"Nothing here is
> implemented"*. That was wrong in both directions when written or shortly after, and re-reading
> the code rather than this doc is what found it:
>
> | | state | note |
> |---|---|---|
> | G2 coating basis + demo | **was already done** | both live as warnings, deliberately unpriced |
> | G4 FBC `tpo_oh` 125 | **was already done** | config carries 125 with Tim's comment cited |
> | G3 Stockmeier · G9 pressure cleaning | **done 2026-08-02** | values were already in config — *including all three ACTIVE prod configs* — and **no code read them**. `_note_stockmeier_floor` claimed it was "now enforced as a warning". It was not. |
> | G7 cover board · G8 warranty upgrades | **built 2026-08-02** | ⚠️ engine-complete but the keys are not in prod's configs yet |
> | G6 trash chute · G10 detail items · G13 silicone add-ons | **built 2026-08-02** | new inputs: `stories`, `detail_items`, `silicone_addons` |
> | G11 stucco metal | **⚠️ was NEVER "not implemented"** | see below — we bill one side of a 10× ambiguity, live |
> | G1 · G5 · G12 | **open, → Tim** | no number can be derived from the sheet |
>
> The lesson worth keeping: **a value sitting correctly in config is not an implemented rule.**
> Four of these had the right number and no reader, and two carried notes asserting they were
> already enforced. Grep for the reader, not for the key.

### HIGH

**G1. Silicone prices may be missing the 2024 insurance increase.**
N22 (Josh tab, **2024-08-01**): *"Added $25 OH on each coat thanks to insurance as of 8/1/2024."*
The headline cells still read $445 / $515 / $645, and the material-cost comments behind them
(O22–O24) are from 2018. If the +$25/coat was never rolled into the headline, the correct prices
are **$470 / $565 / $720** — we are under by $25–$75/sq on every silicone job. Cannot be resolved
from the sheet. **→ Tim.**

**G2. Coating prices assume a 25+ square job and exclude demo.**
F6: *"Coating Prices Based on 25+ squares Profit (Demo not included in price - add $100)."*
Our coating systems are `all_in_systems` — flat per-square, no size term, no demo adder. A coating
job with tear-off is under-quoted by **$100/sq**, and a 10-square coating job carries 25-square
profit density.

**G3. Stockmeier's 12-square floor is a note, not logic.**
M29: *"min. 12 SQ job (less than 12 SQ is $390 M per SQ and T&M)."* The fixture records this as
`_note_stockmeier_floor` "not engine logic v1", so an 8-square Stockmeier quote returns $595/sq
flat when Tim's rule is time-and-materials. Wrong number *and* wrong basis.

**G4. FBC TPO overhead is $125, we charge $135 in both zones.**
H3 comment: *"Tim (FBC) - $125."* The headline $135 equals neither the FBC value nor any Miami
column. `overhead.FBC.tpo_oh` should be **125**. (Flat OH is consistent: H2's comment gives
FBC $155 and the headline is $155.) Small per-square, but it is the same class of unmodelled
FBC/HVHZ delta we already honour on polyglass.

### MEDIUM

**G5. Crew-load and new-construction overhead tiers are unmodelled.**
H2 (2023-05-30): flat OH `$155 base / $135 med / $115 busy / $100 super busy / $120 new construction`.
H2 (Josh, **2024-11-27**): `$155 / $140 busy (16+ guys per day) / $135 new construction`.
H3: TPO `$125 / $110 med / $100 busy / $95 super busy / $105 new construction`.
We store one scalar per system per zone. A new-construction low-slope job should price OH at
$105–135, not $155 — a 13–35% overstatement on exactly the work Perkins wants to win.

**G6. Trash chute charges a flat $1,500 regardless of height.**
E18 cell reads *"$1,500 + sections"*; the comment: *"3 sections of trash chute per story — charge
$100 per section."* `_build_low_slope` adds `trash_chute_flat_add` (1500) for `3_5_stories` and
nothing else. A 5-story job is under-charged by the whole per-story component (~$300/story).

**G7. Cover board carries a $40 OH adder we never apply.**
H17 reply (2022-11-04): *"note, add an additional $40 OH for any cover board."* We have no
cover-board concept at all — SecuRock ¼" $98 / ½" $108 (H17) are absorbed into the DensDeck deck
type, and the OH adder is simply lost.

**G8. Polyglass warranty upgrades cannot be quoted.**
E26 Polyfresko +$80 (20 yr), E27 SAV Plus 3-ply +$175 (25 yr), E28 +$315 (30 yr), and E28's comment
adds a **$65 SAV Plus 2nd-ply upgrade** that is not even in our note. The fixture records all of
this as a `_note_polyglass_upgrades` string tagged "encode as adders when quoting (v2)". Warranty
length is a sales lever and today it is unpriceable.

**G9. `low_slope.pressure_cleaning` is dead config.**
`grep -rn pressure_clean core/ api/ web/src` returns **nothing**. The values are right (§1) and
unreachable — a pressure-cleaning-only or maintenance job cannot be quoted. Unwired code, R2 category.

**G10. Detail items and per-LF flashing OH are missing entirely.**
Both overhead tabs carry a priced detail list we do not model, and it is branch-split:

| detail | Jupiter | Miami |
|---|--:|--:|
| Penetration flashing | $70 | $75 |
| "L" metal (galv) 4×5 FBC, 10' pc | $85 | $85 |
| Term bar + counter flashing, 10' pc | $90 | $90 |
| Scupper / drain detail (2 men, 2 hrs) | $350 | $350 |
| Alum coping cap, 10' pc | $250 | $250 |
| 3rd ply SAV FR (20 yr) | $25 | $43 |
| Additional layer of demo | $35 | $35 |
| Flashing/valley metal OH per LF | $2.30 | $3.07 |

**G11. The sheet contradicts itself on stucco metal — by 10×.**
D29 (polyglass block): *"Add **$9 per LF** for stucco metal / L flashing and $75 per penetration."*
G26 (TPO block): *"Add **$9 per 10 LF** … and $75 per penetration."* Same adder, two blocks, one
order of magnitude apart. **→ Tim.**

> ⚠️ **CORRECTION 2026-08-02: "Neither is implemented" was false, and this is the most expensive
> error in this document.** `stucco_metal_per_lf: 9` is live in **all three active prod configs**
> and `_build_optional` bills `stucco_metal_lf × 9` — i.e. we have been shipping the **D29
> reading** all along. If G26 is the correct one, every stucco-metal line is **10× over**: 200 LF
> bills **$1,800** where it should bill **$180**.
>
> This is no longer a dormant question, it is live exposure, so the engine now emits
> `stucco_metal_basis_contradiction` on any quote carrying stucco metal, naming both totals. It is
> **not** defaulted to the cheaper reading — that would quietly cut a real charge by 90% on the
> same evidence that cannot settle it. Tim's answer changes a number already on sent quotes, so
> this belongs in his letter with the dollar consequence attached.

**G12. Hauling under-recovers on small roofs.**
E23 ($35/sq hauling, inside the $475 polyglass base) comment: *"$800 / 25 squares"* = $32/sq. The
$35 works at 25 squares; on a 9-square job it recovers $315 against an ~$800 job cost. Same
small-job failure mode as the repair-path profit floor already on the R2 list.

**G13. Silicone add-ons not priced.** N25 Add Granules $50 (M $20); N26 Traffic Coat 1 coat $225
(M $85); L27 note *"$100 per extra coat (L, OH & P) + M … for TPO add $25 for TPO primer."*

### LOW / informational

- **E22 sub labour rates** (2019, reply 2021): Eddie $200, Jesus $120 (+$1/LF stucco metal),
  Rocky $260 (+$1/LF), Rafa $180 — against a $130 "L (System Install)" line. Cost intelligence, not
  price; useful if we ever model subcontractor selection.
- **Systems priced in comments that we do not carry at all**: Sika 624/621 TC liquid-applied
  ($1,300–2,100/sq, "***NO TILES", E11), Tremco 350NF/951NF $675 (F11), Lucas 4700 under-tile
  $575–725 (E13/F12/F13), Modifleece recovery (G28 block), BarrierGuard (M29). Out of scope for v1;
  they exist and Tim quotes them.
- **L32 "do not use - need pricing from ABC"** and **D28 "Need Gabby pricing"** — Tim's own open items.
- **N28 reply (2020): "JOHN SAYS ABC WAS PRICING $40 over what it should be"** — a supplier dispute,
  not a rate.

---

## 3. The overhead tabs answer (part of) the branch question already in Tim's email

The email asks Tim for each office's daily overhead and which crew-size column it prices from.
For **low-slope**, the sheet already answers it — and the two branches are on different vintages:

| | Jupiter tab (**2023**) | Overhead Metrics tab (**2025**) |
|---|---|---|
| OH basis | 4 men $345 / 7 men $200 / 10 men $140 | 9 men $460 / 12 men $345 / 15 men $275 |
| TPO re-roof OH/sq | $155 / $90 / $63 | $192 / $144 / $115 |
| 2-ply BUR (concrete) OH/sq | $184 / $107 / $75 | $230 / $173 / $138 |
| Coating: primer + 2 coats | $85 / $49 / $34 | $113 / $85 / $67 |
| Coating: primer + 2 coats + fabric | $117 / $68 / $47 | $156 / $117 / $93 |
| Coating: + traffic coat | $144 / $84 / $59 | $192 / $144 / $115 |

Our config uses **one** number for both zones: `flat_oh` 155, `tpo_oh` 135. That sits inside
Jupiter's range and **below every Miami column** — Miami's cheapest 15-man TPO figure is $115 but its
9-man figure is $192, and its BUR mid-column is $173 against our $155.

This is the same shape as the sloped Miami overhead defect the R2 review caught, with the sign
reversed: there we had an unvalidated multiplier making Miami too expensive; here we have no
branch split at all, making Miami too cheap. **Do not "fix" it by scaling** — that is precisely the
move that produced the reverted 1.725× multiplier. The Jupiter tab is also two years stale, so any
branch split needs Tim to confirm the current basis and the crew-size column per office before it
ships.

---

## 4. What to do

1. **Ask Tim** (candidates for the open draft, §5 of the continuation): G1 silicone +$25/coat, G11
   stucco metal $9/LF vs $9/10LF, G4 FBC TPO $125 vs $135, and confirmation of the crew-size column
   per branch for low-slope.
2. **Ship as a wave** (R1 ≥97% on `core/`, R2 architect + critic, R4 drift check): G2 coating demo +
   size basis, G3 Stockmeier floor, G6 trash-chute sections, G7 cover-board OH, G8 warranty upgrades,
   G9 wire pressure cleaning.
3. **Backlog:** G5 crew-load tiers (needs an operational "how busy are we" input we do not have),
   G10 detail items, G12 small-job hauling minimum, G13 silicone add-ons.

Nothing in this audit has been coded. No config or prod value changed.
