"""Four worked examples for Tim: two we land exactly, two we miss by 1.5 days.

Usage: DB_URL=... GOTENBERG_URL=... OUT=out.pdf PYTHONPATH=. .venv/bin/python \
           scripts/gen_tim_worked_examples.py

Each page shows the whole calculation from his own RoofR measurements through to the total,
using the estimate-debug trace, so he can check every number against his sheet rather than
take the total on faith. Renders to one PDF via Gotenberg.
"""
import importlib.util
import os
from pathlib import Path

from sqlalchemy import create_engine, text

from adapters.gotenberg import html_to_pdf
from core.estimator import DailyOverheadSeries, QuoteInput, derive_daily_series, estimate
from core.pricing_config import load_config

SPEC = [
    ("918 Mil Creek Drive", "spot on"), ("892 Camellia Dr.", "spot on"),
    ("1913 Flower Drive", "off by 1.5 days"), ("1081 Fairview Lane", "off by 1.5 days"),
]
LIKE = {"tile": ("13_tile", "tile"), "shingle": ("dimensional_shingle", "shingle"),
        "metal": ("standing_seam_metal", "metal")}
INSTALL = {"13_tile": "tile", "dimensional_shingle": "shingle", "standing_seam_metal": "metal"}
NAVY, BLUE = "#2A3C73", "#41B1E5"


def load_homes():
    spec = importlib.util.spec_from_file_location(
        "fitmod", Path("scripts/fit_days_from_roofr.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {h["address"]: h for h in m.load()}


def half(x):
    return max(0.5, round(x * 2) / 2)


def esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def money(x):
    return f"${x:,.2f}"


def page(h, verdict, cfg, rates):
    rt, day_key = LIKE[h["existing"]]
    sq = h["squares"]
    q = QuoteInput(code_zone="FBC", county="palm_beach", roof_type=rt, num_squares=sq,
                   project_kind="residential", demo=True, existing_roof=h["existing"],
                   overhead_mode="daily", apply_cut_calc_to_base=False, debug=True,
                   hips_lf=h["hips"], valleys_lf=h["valleys"], ridges_lf=h["ridges"],
                   rakes_lf=h["rakes"], wall_flashings_lf=h["wall_flash"],
                   eaves_lf=h["eaves"], pitch_primary=h["pitch"])
    ours = derive_daily_series(cfg, q)
    r = estimate(cfg, QuoteInput(**{**q.__dict__, "daily_series": ours}))

    our_days = sum(s.days for s in ours)
    tim_series = ([DailyOverheadSeries(series="demo_dry_in_flat", days=half(h["demo"]))]
                  if h["demo"] else [])
    if h[day_key]:
        tim_series.append(DailyOverheadSeries(series=INSTALL[rt], days=half(h[day_key])))
    tim_days = sum(s.days for s in tim_series)
    tim_oh = sum(s.days * float(rates[s.series]) for s in tim_series)
    our_oh = sum(s.days * float(rates[s.series]) for s in ours)

    ok = abs(our_days - tim_days) < 0.25
    badge = ("#1a7f37", "We match your number") if ok else ("#b3261e", f"We are {our_days - tim_days:+.1f} days off")

    meas = [("squares", sq), ("pitch", f"{h['pitch']:g}/12"), ("eaves", h["eaves"]),
            ("hips", h["hips"]), ("ridges", h["ridges"]), ("valleys", h["valleys"]),
            ("rakes", h["rakes"]), ("wall flashing", h["wall_flash"])]

    rows = "".join(
        f"<tr><td>{esc(n)}</td><td class=r>{v:,.0f}{' ft' if n not in ('squares','pitch') else ''}</td></tr>"
        if isinstance(v, (int, float)) else
        f"<tr><td>{esc(n)}</td><td class=r>{esc(v)}</td></tr>" for n, v in meas)

    days_rows = "".join(
        f"<tr><td>{esc(s.series.replace('_',' '))}</td><td class=r>{s.days:g} d</td>"
        f"<td class=r>{money(float(rates[s.series]))}/d</td>"
        f"<td class=r>{money(s.days*float(rates[s.series]))}</td></tr>" for s in ours)

    li = ""
    for i in r["line_items_detail"]:
        e = i.get("explain") or {}
        inputs = " &middot; ".join(f"{esc(k)} = {esc(v)}" for k, v in (e.get("inputs") or {}).items()
                                   if v is not None and k != "profit_scale"
                                   and k != "pm_incentive_table")
        li += (f"<tr><td><b>{esc(i['label'])}</b><div class=f>{esc(e.get('formula',''))}</div>"
               f"<div class=v>{inputs}</div></td><td class=r>{money(i['amount'])}</td></tr>")

    return f"""
<section>
  <h2>{esc(h['address'])}</h2>
  <p class=sub>{esc(h['existing'])} &middot; {sq:g} squares &middot; {esc(verdict)}</p>
  <div class=badge style="background:{badge[0]}">{esc(badge[1])}</div>

  <h3>1 &mdash; Your RoofR measurements, as we read them</h3>
  <table class=meas>{rows}</table>

  <h3>2 &mdash; Days, and the overhead they carry</h3>
  <table class=calc>
    <tr><th>phase</th><th class=r>days</th><th class=r>rate</th><th class=r>overhead</th></tr>
    {days_rows}
    <tr class=tot><td>our total</td><td class=r>{our_days:g} d</td><td></td><td class=r>{money(our_oh)}</td></tr>
    <tr class=his><td><b>your figure</b></td><td class=r><b>{tim_days:g} d</b></td><td></td>
        <td class=r><b>{money(tim_oh)}</b></td></tr>
  </table>

  <h3>3 &mdash; Every line, and how it was reached</h3>
  <table class=calc>{li}
    <tr class=tot><td><b>PROJECT TOTAL</b></td><td class=r><b>{money(r['project_total'])}</b></td></tr>
  </table>
  <p class=note>Per square: {money(r['per_square_total'])} &times; {sq:g} sq =
     {money(r['squares_subtotal'])}, plus the fixed items above.</p>
</section>"""


def main():
    homes = load_homes()
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("SET app.tenant_id='1'"))
        raw = c.execute(text("select config from pricing_configs "
                             "where is_active and branch='jupiter'")).scalar()
    cfg = load_config(raw)
    rates = cfg.daily_overhead_rates()

    body = "".join(page(homes[a], v, cfg, rates) for a, v in SPEC if a in homes)
    missing = [a for a, _ in SPEC if a not in homes]
    if missing:
        print("MISSING:", missing)

    html = f"""<!doctype html><html><head><meta charset=utf-8><style>
@page {{ size: letter; margin: 14mm; }}
body {{ font: 10.5pt/1.45 Arial, Helvetica, sans-serif; color:#111; }}
h1 {{ color:{NAVY}; font-size:19pt; margin:0 0 2px; }}
.lead {{ color:#555; margin:0 0 18px; font-size:10pt; }}
section {{ page-break-after: always; }}
section:last-child {{ page-break-after: auto; }}
h2 {{ color:{NAVY}; font-size:15pt; margin:0 0 2px; }}
.sub {{ color:#666; margin:0 0 8px; }}
.badge {{ display:inline-block; color:#fff; padding:3px 10px; border-radius:3px;
          font-size:9.5pt; margin-bottom:12px; }}
h3 {{ color:{NAVY}; font-size:11pt; margin:16px 0 6px;
      border-bottom:2px solid {BLUE}; padding-bottom:3px; }}
table {{ width:100%; border-collapse:collapse; }}
td, th {{ padding:5px 7px; border-bottom:1px solid #e2e2e2; vertical-align:top; }}
th {{ background:{NAVY}; color:#fff; font-size:9pt; text-align:left; }}
.r {{ text-align:right; white-space:nowrap; }}
.meas td {{ width:50%; }}
.f {{ color:#555; font-size:8.5pt; font-style:italic; }}
.v {{ color:#777; font-size:8pt; font-family:monospace; }}
.tot td {{ border-top:2px solid {NAVY}; background:#f4f7fb; }}
.his td {{ background:#fff8e1; }}
.note {{ color:#666; font-size:9pt; }}
</style></head><body>
<h1>How the estimator priced four of your homes</h1>
<p class=lead>Two we land on your day count exactly, two we miss by 1.5 days. Every number
below traces back to your own sheet &mdash; base costs, overhead rates, the profit sliding
scale and the fixed items are all yours. Prepared for Tim Kanak, Perkins Roofing.</p>
{body}</body></html>"""

    out = Path(os.environ.get("OUT", "tim_worked_examples.pdf"))
    out.write_bytes(html_to_pdf(html))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
