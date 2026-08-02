# General Conditions + commission — questions for Tim, Marco and Josh

**Status: DRAFT, not sent.** `EMAIL_SEND_MODE=test` in prod, and Jon sends anything client-facing.

Marco and Josh are on this one because question 2 is about their own commission rates.

---

## What prompted it

Jon, 2026-08-02: *"why are we using general conditions if Tim doesn't — we can't back into those
numbers in his proposals? why did we only recently start including them?"* Checked rather than
argued. Three findings:

1. **"General Conditions" is Tim's own label, not ours.** It is the header on cell `D18` of his
   Evergrene Bid Sheet, over two rows he wrote: `A19` *"General Conditions (green fence,
   telehandler)"* $22,800 and `A20` *"Full-time PM (40 days telehandler) add $225"* $9,000, with
   `D19 = SUM(B19:B20)*1.15 = $36,570`.
2. **It cannot be backed into from anything he has sent a client.** Of **26,063** mirrored Knowify
   deliverable lines, exactly **one** is called "General Conditions" — $12,000 on *Banyan House
   Re-Roof*, contract 2622543, **unsigned**, created 2023-08-09. Zero lines mention a telehandler
   or a green fence; the 14 "mobiliz*" lines are all demob/remob charges on repairs. And on his own
   sheet **`D19` is referenced by no total formula** — his stated project total
   `K42 = SUM(K35:K41)+K33` skips it. The Evergrene *proposal* is not in the corpus (the six
   Evergrene PDFs are Roofr measurement reports, not priced documents), so nothing on file says
   whether the $36,570 reached the client.
3. **We only started carrying it two days ago**, with the multi-building work — `aab47a8`
   (2026-07-31, decoding his sheet) and `1e902a4` (2026-08-01, slice 1). Before #430 a bid had no
   container for site-wide scope at all. The stated reason for adding it: the old per-building
   pricing over-charged every structure by +10% to +85% *while* omitting $116,420 of project scope,
   and the two errors masked each other into a −9% net.

### The consequence to fix once he answers

`project_total` includes `project_items`, but `tiers.good.line_items` is `[]`
(`api/routes/proposals.py:1249`), so a project proposal would show the customer **one number
silently containing $36,570 of General Conditions, with no line explaining it** — neither excluded
like his `K42` nor itemised like a quoted block.

**Nothing is exposed:** prod has 0 `bid_projects`, 0 project estimates and 0 project proposals. This
is a decision, not an incident.

Size of the question on Evergrene:

| | ours | Tim's | |
|---|--:|--:|--:|
| like-for-like, GC excluded both sides (what the benchmark reports) | $397,230 | $381,288 | +4.2% |
| all-in, **if** he charged GC separately | $433,800 | $417,858 | +3.8% |
| all-in, **if** he absorbed it | $433,800 | $381,288 | **+13.8%** |

---

## Suggested email

**To:** Tim · **Cc:** Marco, Josh
**Subject:** Two pricing questions before we quote a multi-building job

Tim — three quick things, two of them questions.

**1. General Conditions — does the client ever see it?**

Your Evergrene sheet builds it as green fence + telehandler ($22,800) and a full-time PM ($9,000),
×1.15 = **$36,570**. But that cell isn't referenced by your project total, and in ~26,000 billed
lines in Knowify we found exactly one called "General Conditions" (on an unsigned 2023 job). So we
can't tell from the paperwork whether it goes out as its own line, gets folded into the
per-building prices, or gets absorbed.

On Evergrene it's the difference between quoting **$397,230** and **$433,800**, so we'd rather ask
than assume. Which is it?

And the follow-on: **is General Conditions commissionable?** If commission is a share of net, its
markup is about $4,770 of profit, so at 50% of net the salesperson takes roughly $2,385 of it.

**2. Marco and Josh — commission rates.**

Tim, you said a salesperson takes **15% of gross or 50% of net**, and we've made those the defaults
(we were previously showing 10% of net, which was five times low — nobody was underpaid, it was the
number on our screen that was wrong).

The one thing that doesn't fit: your newest sloped sheet has Marco at **15%** and Josh at **7.5%**
on an otherwise identical price grid. Marco's 15% matches the gross option. Josh — is 7.5% a
negotiated rate for you, or an old number we should ignore? We've changed nothing about it either
way; the rate is adjustable per quote.

**3. Permits — done, and it moves against you.**

We've made it one permit per building, as you said. Worth flagging: on Evergrene that takes our
number from **+2.3% to +4.2%** against your own bid — *further* from what you actually charged,
because your Evergrene sheet only bills one permit. Your rule is what we've shipped; your sheet
disagrees with it on that job.

Jon

---

## After he answers

- GC out of the customer total, or itemised on the proposal — one line change either way.
- Josh's 7.5% either becomes a per-quote override or is dropped from the record.
- If GC is not commissionable, `price_project` needs to exclude its markup from the commission base
  (`out.profit += item.amount - item.cost` currently counts it as profit).
