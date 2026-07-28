# Knowify scrape — what Tim asked for, and what the Miami baseline shows (2026-07-28)

## What Tim asked for (2026-07-27 call — Whisper renders "Knowify" as "notify")

> "Do you have templates for scopes of work that we should save?" — "**They're all in notify.**"
>
> "If it can just scrape it all through a notify, even, like, skylights, **I would use my notify**,
> because… **I update my catalog all the time, way more than Josh does.** And usually I'll even say,
> hey, copy and paste this into your notify if I change something. **Sometimes I'll even forget.**
> So I would scrape my notify just because I know it's more updated as far as, like, **accent items**.
> And then that also has **the breakdown for protector versus preferred versus premium for every
> different type of roof**… Including, like, adding a **skylight** or a **solar vent** or, like,
> doing a **chimney**… It has breakdowns of all that kind of stuff in there, which is why notify is
> nice, because **since it's already pre-written, you just type in one letter or two letters and
> it'll auto-populate the entire scope of work**. It's a drop-down menu with the different scopes."
>
> On repairs: "**you're going to put repairs when I give you the drop-down menu**… there's a shingle
> tile, metal, flat. There's all just different types of repairs on there… You still have a scope of
> work."

**Scrape list, in his words:** scope-of-work templates · accent items (skylight / solar vent /
chimney) · the PROTECTOR / PREFERRED / PREMIUM breakdown per roof type · repair scopes by type.

**Where it applies:** the scope-of-work section on BOTH re-roof and repair quotes, as a
type-ahead template drop-down — one or two letters auto-populates the whole scope.

## The connection problem

The Knowify MCP is scoped to ONE tenant per connection. It is currently bound to:

    Perkins Roofing Corporation · 575 NW 152 Street, Miami · Company 11267 · Tenant 9258

That is the Miami/Josh tenant — **the one Tim explicitly told us not to use.** Jupiter needs its own
OAuth. Switching loses Miami access, so the Miami baseline was captured first:

    ~/perkins-corpus/knowify/miami_catalog_perkins_items_2026-07-28.json
    26 PERKINS tier items · 54,307 characters of pre-written scope text · 561 catalog items total

## Evidence that Josh's catalog is stale — exactly as Tim said

**1. The catalog has not moved in three months.** Most recent `DateModified` across all 561 items is
**2026-05-07**.

**2. The accent items he named are empty placeholders**, last touched 2024-10-23:

| item | price |
|---|--:|
| Skylight / Skylights | **$0.00** |
| Chimney Cap / Chimney Repair / Chimney Restoration | **$0.00** |
| Turbine Vent Installation / Ventilation / Vent Stacks | **$0.00** |

Only the `(OPTIONAL)` variants carry real numbers: Chimney Cap Replacement $2,393.46, Solar Roof
Vent $1,339 (metal $2,995), Turbine Vent $257.50, ridge vents $9.79/ft, copper perimeter +
gooseneck upgrade $150/sq.

**3. One tier price disagrees with a sold proposal.** 21 of 22 tier prices match our config exactly.
The exception:

| | our config | Josh's Knowify |
|---|--:|--:|
| tile / PREFERRED | **$165.00** | $160.00 |

Our $165 carries the note *"verified Greener proposal 7/17: $7,095/43sq"* — which is $165.00 to the
cent. A real sold proposal says 165; Josh's catalog says 160. Tim's catalog should settle it.

## Everything else matched

shingle 650 / 42.50 / 165 / 215 · tile 1100 / 290 / 365 / 485 / 47.50 · flat 850 / 175 / 315 / 500 /
115 · metal 1125 / 115 / 115 / 430 / 365 / 1000 / 225. Also confirms tile COASTAL is **$47.50** and
shingle COASTAL is **$215** — those two were reported swapped in commit a058945; the config was
right, the commit message was wrong.

## Next, once Jupiter is connected

1. Pull the full Jupiter catalog and diff it against this Miami baseline — the diff IS Tim's
   "sometimes I'll even forget to tell Josh."
2. Take Jupiter's scope text as the source for the proposal scope library (re-roof AND repair).
3. Resolve tile/PREFERRED 160 vs 165 from Tim's side.
4. Price the accent items (skylight, solar vent, chimney) from Tim's catalog, since Josh's are $0.
