# Monday Demo Walkthrough — Perkins Estimating v2

*Presenter: Jon → Tim (+ Josh, Marco). Draft scaffolded by a Cloudflare free-tier agent
(Hermes 3a81dca0), completed + fact-checked against the shipped code.*

Since Friday's Zoom we wired in the **branch model, full package menu, profit slider,
time-based overhead, existing-roof demo, and the real gutter price list** — so the app
now lines up with how Perkins actually estimates and with Tim's own Greener numbers.

Everything below is **live in prod** (`app.perkinsroofing.net`). Log in as admin.

## 1. Branch management — Admin Config → Branches
- Open **Admin Config → Branches**. Show Miami / Jupiter / Naples / **GC**.
- "This new tab drives every branch selector in the app — no more hard-coded names."
- Add a throwaway branch, rename it, deactivate it (stays in history, drops from selectors).
- **Customers**: open one — it now carries a **Branch** (all are Miami today, since only
  Miami's Knowify is connected). **Dashboard**: show the branch filter (All / each branch) —
  "Miami's overhead is higher than Jupiter's; Naples runs at zero right now — now you can see
  each on its own or rolled up."

## 2. Existing-roof / demo selector — Quote builder
- Start a quote. Point at **"Existing roof (what are we tearing off?)"**:
  New construction / Shingle / Tile / Metal / Flat.
- "Friday you said demo should follow what we're tearing *off*, not what we install."
- Pick **Tile** → tile-demo rate applies **and a dumpster is added automatically** (that
  $1,200-a-load tile dump you mentioned). Switch to **Shingle** → demo drops, no dumpster.
- **New construction** → no demo at all.

## 3. Gutters — Tim's own price list
- Open the **Gutters** section. Style select: 6"/7" K-style, commercial box, half-round,
  **aluminum vs copper**. Enter linear feet.
- **2-story** toggle applies the uplift (only where you gave a 2-story rate — 6"/7" K-style —
  the box shows it disabled, so nobody quotes an uplift you didn't price).
- Elbows, **downspouts included in the per-LF rate**, standard/upgraded leaf guards,
  res/commercial leaderheads, removal & disposal — all at the exact numbers from your email.

## 4. Time-based overhead — "By time (days)" mode
- "On Friday we came in ~$2,000 light vs your Protector on Greener — this closes it."
- Overhead mode toggle → **By time (days)**. Enter demo days + install days per phase
  (Greener = 4 demo + 6 tile). Overhead now reflects your daily targets ($1,050 demo,
  $745 tile, $850 metal), not a flat per-square guess.

## 5. Full package menu — every tier, priced from your catalog
- After calculating, the result shows **all tiers as cards**: Protector base, Preferred,
  and the **three premiums (Caribbean / Mediterranean / Modern)** + Coastal — flat catalog
  adders on top of Protector.
- "These matched your Greener proposal to the dollar: Caribbean +$12,470, Mediterranean
  +$15,695, Modern +$20,855 at 43 squares."

## 6. Profit slider + floors
- Below the estimate: **target-profit presets** [Min 13%] [15%] [20%] + a min-$ floor.
  Click one → the quote re-prices instantly to hit that margin.
- Profit % and profit+OH % show **red when below your 13% / 33% floors**.

## 7. YouTube comment posting
- **Comments** page: **Connect / switch account** button, and Post now shows a
  **"Post as {channel}?"** confirmation so you always see who you're posting as.
- (Tim: click Connect once and pick the account that owns the Perkins channel — that
  finishes the reconnect and clears the 403.)

## Known gaps — mention honestly
1. **RoofR auto-measure** still needs API access — Jon to get added to the RoofR account /
   call them; today measurements are entered manually.
2. **Price-book ↔ config linkage**: needs Tim to **share the original calculator sheets**
   (the shared copies have no cell comments — the comments hold the material mapping).
3. **GC branch has no pricing config yet** — quoting GC returns "no active config" until
   Tim provides its values.
