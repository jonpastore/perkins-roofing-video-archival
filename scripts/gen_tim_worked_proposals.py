#!/usr/bin/env python3
"""Four of Tim's homes as REAL PROPOSALS, in the shipping format, with the build-up shown.

Supersedes gen_tim_worked_examples.py, which rendered its own bespoke HTML. Tim has to be able to
compare what we send a customer against his own sheet, so this renders the actual proposal template
(the one a customer receives) with the "How this price was built" section switched on, plus a
per-home banner comparing our derived days to his.

Config source: the GIT FIXTURE, not prod. Prod still runs the pre-2026-07-26 pm_incentive shape and
charges $50 on a 35-square Palm Beach residential job where Tim's live sheet says $100. Showing him
a number we already know is wrong would waste the review; this shows what we quote once seeded.

Usage: PYTHONPATH=. .venv/bin/python scripts/gen_tim_worked_proposals.py [--out FILE.pdf]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

from core.estimator import DailyOverheadSeries, QuoteInput, derive_daily_series, estimate
from core.pricing_config import load_config
from core.proposal_render import (
    DEFAULT_TEMPLATE_HTML,
    ProposalRenderContext,
    calc_lines_from_estimate,
    render_proposal_html,
)

ROOT = Path(__file__).resolve().parent.parent
SPEC = [
    ("918 Mil Creek Drive", "we match your day count exactly"),
    ("892 Camellia Dr.", "we match your day count exactly"),
    ("1913 Flower Drive", "we are 1.5 days under yours"),
    ("1081 Fairview Lane", "we are 1.5 days under yours"),
]
LIKE = {"tile": ("13_tile", "tile"), "shingle": ("dimensional_shingle", "shingle"),
        "metal": ("standing_seam_metal", "metal")}
INSTALL = {"13_tile": "tile", "dimensional_shingle": "shingle",
           "standing_seam_metal": "metal"}
ROOF_LABEL = {"13_tile": '13" Concrete Tile', "dimensional_shingle": "Dimensional Shingle",
              "standing_seam_metal": "Standing Seam Metal"}


def _load_homes() -> dict:
    spec = importlib.util.spec_from_file_location("fitmod", ROOT / "scripts/fit_days_from_roofr.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return {h["address"]: h for h in m.load()}


def _half(x: float) -> float:
    return max(0.5, round(x * 2) / 2)


SKIP_INPUTS = {"profit_scale", "pm_incentive_table", "boundary_inclusive_lower",
               "boundary_exclusive_upper"}


def _esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _audit(home: dict, ours, tim_series, rates, result) -> str:
    """The reviewer's view: what we read, the days, and every input behind every line.

    This is Tim's checking document, not a customer's. calc_lines_from_estimate() deliberately
    strips config key names and annotations because they must never reach a homeowner — but here
    they are exactly what is being checked, so the raw explain block is shown in full alongside.
    """
    meas = [("squares", f"{home['squares']:g}"), ("pitch", f"{home['pitch']:g}/12"),
            ("eaves", f"{home['eaves']:,.0f} ft"), ("hips", f"{home['hips']:,.0f} ft"),
            ("ridges", f"{home['ridges']:,.0f} ft"), ("valleys", f"{home['valleys']:,.0f} ft"),
            ("rakes", f"{home['rakes']:,.0f} ft"),
            ("wall flashing", f"{home['wall_flash']:,.0f} ft")]
    meas_rows = "".join(
        f"<tr><td>{_esc(n)}</td><td style='text-align:right'>{_esc(v)}</td></tr>" for n, v in meas)

    def day_rows(series, label, bold=False):
        w = "font-weight:700;" if bold else ""
        return "".join(
            f"<tr style='{w}'><td>{_esc(s.series.replace('_', ' '))}</td>"
            f"<td style='text-align:right'>{s.days:g} d</td>"
            f"<td style='text-align:right'>${float(rates[s.series]):,.0f}/d</td>"
            f"<td style='text-align:right'>${s.days * float(rates[s.series]):,.2f}</td></tr>"
            for s in series) or f"<tr><td colspan=4>{label}: none</td></tr>"

    our_oh = sum(s.days * float(rates[s.series]) for s in ours)
    tim_oh = sum(s.days * float(rates[s.series]) for s in tim_series)

    line_rows = ""
    for li in result["line_items_detail"]:
        ex = li.get("explain") or {}
        inputs = " &middot; ".join(
            f"{_esc(k)} = {_esc(v)}" for k, v in (ex.get("inputs") or {}).items()
            if v is not None and k not in SKIP_INPUTS)
        line_rows += (
            f"<tr><td><b>{_esc(li['label'])}</b>"
            f"<div style='color:#475467;font-style:italic;font-size:9px'>"
            f"{_esc(ex.get('formula', 'fixed amount'))}</div>"
            f"<div style='color:#667085;font-family:monospace;font-size:8.5px'>{inputs}</div></td>"
            f"<td style='text-align:right;white-space:nowrap'>${li['amount']:,.2f}</td></tr>")

    css = ("width:100%;border-collapse:collapse;font-size:10px;margin:0 0 14px")
    td = "padding:4px 7px;border-bottom:1px solid #eaecf0;vertical-align:top"
    th = "padding:4px 7px;background:#1b2a52;color:#fff;text-align:left;font-size:9px"
    return (
        "<div style='break-before:page;page-break-before:always'>"
        "<h2>How we reached this number</h2>"
        "<h3 style='font-size:11px;color:#1b2a52;margin:12px 0 4px'>"
        "1 — Your RoofR measurements, as we read them</h3>"
        f"<table style='{css}'><tbody>{meas_rows}</tbody></table>"
        "<h3 style='font-size:11px;color:#1b2a52;margin:12px 0 4px'>"
        "2 — Days, and the overhead they carry</h3>"
        f"<table style='{css}'><thead><tr><th style='{th}'>phase</th>"
        f"<th style='{th};text-align:right'>days</th><th style='{th};text-align:right'>rate</th>"
        f"<th style='{th};text-align:right'>overhead</th></tr></thead><tbody>"
        f"{day_rows(ours, 'ours')}"
        f"<tr style='background:#f8fafc;font-weight:700'><td>our total</td>"
        f"<td style='text-align:right'>{sum(s.days for s in ours):g} d</td><td></td>"
        f"<td style='text-align:right'>${our_oh:,.2f}</td></tr>"
        f"<tr style='background:#fffbeb;font-weight:700'><td>your figure</td>"
        f"<td style='text-align:right'>{sum(s.days for s in tim_series):g} d</td><td></td>"
        f"<td style='text-align:right'>${tim_oh:,.2f}</td></tr>"
        "</tbody></table>"
        "<h3 style='font-size:11px;color:#1b2a52;margin:12px 0 4px'>"
        "3 — Every line, the rule behind it, and the values that went in</h3>"
        f"<table style='{css}'><tbody>{line_rows}"
        f"<tr style='background:#f8fafc;font-weight:800;border-top:2px solid #1b2a52'>"
        f"<td>PROJECT TOTAL</td><td style='text-align:right'>"
        f"${result['project_total']:,.2f}</td></tr></tbody></table>"
        f"<style>table td{{{td}}}</style></div>"
    )


def _banner(home: dict, our_days: float, tim_days: float, verdict: str) -> str:
    """Our days against his, stated plainly — this is the thing he is being asked to check."""
    delta = our_days - tim_days
    agree = abs(delta) < 0.25
    tone = "#1a7f37" if agree else "#b3261e"
    detail = ("Same number." if agree
              else f"{abs(delta):.1f} days {'under' if delta < 0 else 'over'} — this is the gap "
                   f"I need your read on.")
    return (
        f'<div style="margin:0 0 14px;padding:10px 14px;border-left:4px solid {tone};'
        f'background:#f8fafc;font-size:11px;">'
        f'<b>Days: we say {our_days:g}, you said {tim_days:g}.</b> {detail} '
        f'<span style="color:#667085">({verdict})</span></div>'
    )


def _proposal_for(home: dict, verdict: str, cfg) -> str:
    rt, day_key = LIKE[home["existing"]]
    sq = float(home["squares"])
    q = QuoteInput(
        code_zone="FBC", county="palm_beach", roof_type=rt, num_squares=sq,
        project_kind="residential", demo=True, existing_roof=home["existing"],
        overhead_mode="daily", apply_cut_calc_to_base=False, debug=True,
        hips_lf=home["hips"], valleys_lf=home["valleys"], ridges_lf=home["ridges"],
        rakes_lf=home["rakes"], wall_flashings_lf=home["wall_flash"],
        eaves_lf=home["eaves"], pitch_primary=home["pitch"],
    )
    ours = derive_daily_series(cfg, q)
    result = estimate(cfg, QuoteInput(**{**q.__dict__, "daily_series": ours}))

    our_days = sum(s.days for s in ours)
    tim_series = ([DailyOverheadSeries(series="demo_dry_in_flat", days=_half(home["demo"]))]
                  if home["demo"] else [])
    if home[day_key]:
        tim_series.append(DailyOverheadSeries(series=INSTALL[rt], days=_half(home[day_key])))
    tim_days = sum(s.days for s in tim_series)

    total = result["project_total"]
    ctx = ProposalRenderContext(
        proposal_title=f"{ROOF_LABEL[rt]} Re-Roof — {home['address']}",
        proposal_date="July 26, 2026",
        proposal_version=1,
        customer_name="Sample — for Tim's review",
        customer_company=None,
        property_address=home["address"],
        property_county="Palm Beach",
        property_code_zone="FBC",
        quote_roof_type=ROOF_LABEL[rt],
        quote_num_squares=sq,
        quote_good_price=f"${total:,.2f}",
        quote_better_price=f"${total * 1.09:,.2f}",
        quote_best_price=f"${total * 1.21:,.2f}",
        quote_line_items=[{
            "label": f"PERKINS PROTECTOR - {ROOF_LABEL[rt]} Re-Roof",
            "description": (
                f"Tear off the existing {home['existing']} roof and dispose of debris. "
                "Re-nail decking to current Florida Building Code. Install Polyglass TU Plus "
                "80 mil underlayment, new drip and valley metal, and new hip and ridge tiles "
                "pointed with mortar. Daily clean-up and haul-away."
            ),
            "qty_display": f"{sq:g}",
            "unit": "squares",
            "total": total,
            "price_display": f"${total:,.2f}",
        }],
        deposit_amount=f"${total * 0.30:,.2f}",
        deposit_instructions="30% on acceptance; balance per the schedule above.",
        tenant_name="Perkins Roofing Corporation",
        tenant_license="CCC1331944",
        accept_url="https://app.perkinsroofing.net/accept/sample",
        payment_draws=[
            {"sequence": 1, "label": "Acceptance / prior to permitting", "pct": "30%",
             "amount": f"${total*0.30:,.2f}"},
            {"sequence": 2, "label": "Material delivery / mobilization", "pct": "30%",
             "amount": f"${total*0.30:,.2f}"},
            {"sequence": 3, "label": "Completion of roof dry-in", "pct": "30%",
             "amount": f"${total*0.30:,.2f}"},
            {"sequence": 4, "label": "Substantial completion", "pct": "Balance",
             "amount": f"${total - round(total*0.30, 2)*3:,.2f}"},
        ],
        include_terms=False,
        include_contract_faq=False,
        calc_lines=calc_lines_from_estimate(result),
        include_calc_breakdown=True,
    )
    html = render_proposal_html(DEFAULT_TEMPLATE_HTML, ctx)
    audit = _audit(home, ours, tim_series, cfg.daily_overhead_rates(), result)
    html = html.replace("<body>", "<body>" + _banner(home, our_days, tim_days, verdict), 1)
    # Audit pages go last, after the proposal a customer would actually receive.
    return html.replace("</body>", audit + "</body>", 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "perkins-corpus/worked-examples"
                                        / "Perkins-worked-proposals-4-homes-2026-07-26.pdf"))
    args = ap.parse_args()

    cfg = load_config(json.loads(
        (ROOT / "infra/fixtures/pricing_config_exhibit_b.json").read_text()))
    homes = _load_homes()

    missing = [a for a, _ in SPEC if a not in homes]
    if missing:
        raise SystemExit(f"homes not found in the RoofR set: {missing}")

    parts = []
    with tempfile.TemporaryDirectory() as td:
        for i, (addr, verdict) in enumerate(SPEC):
            html = _proposal_for(homes[addr], verdict, cfg)
            hp = Path(td) / f"{i}.html"
            hp.write_text(html)
            pp = Path(td) / f"{i}.pdf"
            subprocess.run(
                ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
                 f"--print-to-pdf={pp}", "--no-pdf-header-footer", f"file://{hp}"],
                capture_output=True, timeout=180, check=False,
            )
            if not pp.exists():
                raise SystemExit(f"chrome produced no PDF for {addr}")
            parts.append(str(pp))
            print(f"  rendered {addr}")

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdfunite", *parts, args.out], check=True, timeout=120)

    size = Path(args.out).stat().st_size
    print(f"\n{args.out}  ({size:,} bytes)")


if __name__ == "__main__":
    main()
