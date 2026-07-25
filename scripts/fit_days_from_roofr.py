#!/usr/bin/env python3
"""Learn crew-days from RoofR measurement features — the exercise Tim proposed on the 2026-07-17
Zoom [10:49-12:40] and delivered the data for on 2026-07-24.

His words at [10:12]: "two houses that are both 30 squares but one got towers and all kinds of
crazy shit going on and one could just be like this up and over — this one is going to take two
days and the one with all the crazy shit going on could take five or six days ... that's why it's
very important to do things based on time". Days are therefore NOT a function of squares, which is
why a squares-only fit (docs/ROOFR_OVERHEAD_TIERS.md) tops out at R² 0.70 for tile and 0.38 for
shingle.

This fits days against the COMPLEXITY features in each home's RoofR report and reports
leave-one-out cross-validated R², so the number quoted is predictive rather than in-sample.

Usage: PYTHONPATH=. .venv/bin/python scripts/fit_days_from_roofr.py
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import openpyxl
import pypdf

CORPUS = Path.home() / "perkins-corpus/roofr-attachments"
XLSX = CORPUS / ("2026-07-24__Re_TIME_LEARNING_Overhead_for_AI_Systems__"
                 "Residential_OH_Calculator_SLOPED_ONLY_.xlsx")

FEATURES = ["squares", "pitch", "hips", "valleys", "ridges", "eaves", "rakes", "wall_flash",
            "facets", "two_story_sq"]


def _ft(text: str, label: str) -> float:
    """Parse 'Label: 134ft 10in' → feet."""
    m = re.search(rf"{label}:?\s*(\d+)\s*ft(?:\s*(\d+)\s*in)?", text, re.I)
    if not m:
        return 0.0
    return float(m.group(1)) + (float(m.group(2)) / 12 if m.group(2) else 0.0)


def parse_roofr(path: Path) -> dict:
    t = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
    pitch = re.search(r"Predominant pitch:?\s*(\d+)\s*/\s*12", t, re.I)
    facets = re.search(r"(\d+)\s*facets", t, re.I)
    two = re.search(r"story area:?\s*(\d+)\s*sqft", t, re.I)
    area = re.search(r"Total roof area:?\s*(\d+)\s*sqft", t, re.I)
    return {
        "area_sqft": float(area.group(1)) if area else 0.0,
        "pitch": float(pitch.group(1)) if pitch else 0.0,
        "hips": _ft(t, "Hips"), "valleys": _ft(t, "Valleys"), "ridges": _ft(t, "Ridges"),
        "eaves": _ft(t, "Eaves"), "rakes": _ft(t, "Rakes"),
        "wall_flash": _ft(t, "Wall flashing"),
        "facets": float(facets.group(1)) if facets else 0.0,
        "two_story_sq": (float(two.group(1)) / 100) if two else 0.0,
    }


def _norm(s: str) -> str:
    s = s.lower()
    for a, b in (("north", "n"), ("drive", "dr"), ("court", "ct"), ("street", "st"),
                 ("place", "pl"), ("circle", "cir"), ("terrace", "ter"), ("road", "rd"),
                 ("lane", "ln"), ("boulevard", "blvd"), ("avenue", "ave"), ("southwest", "sw"),
                 ("southeast", "se"), ("northeast", "ne")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def load() -> list[dict]:
    ws = openpyxl.load_workbook(XLSX, data_only=True)["Sheet1"]
    homes = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        homes.append({"address": str(r[0]).strip(), "existing": str(r[4] or "").lower(),
                      "squares": float(r[5] or 0),
                      "demo": float(r[7] or 0), "shingle": float(r[8] or 0),
                      "tile": float(r[9] or 0), "metal": float(r[10] or 0)})
    pdfs = {}
    for p in CORPUS.glob("*TIME_LEARNING*.pdf"):
        stem = p.stem.split("__")[-1]
        pdfs[_norm(re.sub(r"_(FL|fl)_\d{5}.*$", "", stem))] = p
    matched = 0
    for h in homes:
        key = _norm(re.sub(r"[.,]", "", h["address"]))
        hit = next((p for k, p in pdfs.items() if key[:14] in k or k[:14] in key), None)
        if hit:
            h.update(parse_roofr(hit)); h["pdf"] = hit.name; matched += 1
    print(f"{len(homes)} homes, {matched} matched to a RoofR report")
    return [h for h in homes if "pdf" in h]


def loo_r2(X: np.ndarray, y: np.ndarray) -> float:
    """Leave-one-out cross-validated R² — honest predictive power on 30 rows."""
    preds = []
    for i in range(len(y)):
        mask = np.ones(len(y), bool); mask[i] = False
        beta, *_ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
        preds.append(X[i] @ beta)
    preds = np.array(preds)
    sse = float(((y - preds) ** 2).sum()); sst = float(((y - y.mean()) ** 2).sum())
    return 1 - sse / sst if sst else float("nan")


def main() -> None:
    homes = load()
    if len(homes) < 10:
        print("not enough matched homes to fit"); return
    print(f"\n{'target':<9}{'model':<34}{'in-sample R2':>13}{'LOO R2':>9}")
    print("-" * 66)
    for target in ("demo", "tile", "shingle", "metal"):
        y = np.array([h[target] for h in homes], float)
        for label, cols in (("squares only", ["squares"]),
                            ("squares + pitch + facets", ["squares", "pitch", "facets"]),
                            ("squares + all cut LFs", ["squares", "hips", "valleys", "ridges",
                                                       "rakes", "wall_flash"]),
                            ("all features", FEATURES)):
            X = np.column_stack([np.ones(len(homes))] + [[h[c] for h in homes] for c in cols])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            sst = float(((y - y.mean()) ** 2).sum())
            r2 = 1 - float((resid ** 2).sum()) / sst
            print(f"{target:<9}{label:<34}{r2:>13.3f}{loo_r2(X, y):>9.3f}")
        print()


if __name__ == "__main__":
    main()
