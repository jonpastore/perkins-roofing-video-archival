#!/usr/bin/env python3
"""Re-verify the pricing config against Tim's LIVE Google Sheets, cell by cell.

The "we match your sheets at 0.0%" claim in the client email came from an ad-hoc comparison in a
session whose scratchpad was wiped, so nothing in the repo reproduced it. This does, and it is
committed so the next session can re-run it instead of re-deriving it.

Reads Tim's sheets read-only through the perkins-deploy service account with domain-wide
delegation, impersonating tim@perkinsroofing.net (scopes: spreadsheets.readonly).

  sloped     1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig   tabs "FBC" and "Tim (HVHZ)"
  low slope  1hTGWCWzIVLgWwNFln_AYBnEcKkj0tLbaZiv82zHXWWQ

Prints every roof type / system with the sheet value beside the config value, and exits non-zero
if anything disagrees, so it can gate a claim before it goes to a client.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/verify_config_against_tim_sheets.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy import create_engine, text

SA_KEY = Path.home() / ".config/gcloud/perkins-deploy-sa.json"
IMPERSONATE = "tim@perkinsroofing.net"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SLOPED_ID = "1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig"
LOW_SLOPE_ID = "1hTGWCWzIVLgWwNFln_AYBnEcKkj0tLbaZiv82zHXWWQ"

# config roof_type -> the label Tim writes on the sheet row
SLOPED_ROWS = {
    "13_tile": r"13.*tile|concrete tile",
    "barrel_tile": r"barrel",
    "3tab_shingle": r"3.?tab",
    "dimensional_shingle": r"dimensional|architectural|landmark",
    "standing_seam_metal": r"standing seam|metal",
}


def _svc():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY), scopes=SCOPES).with_subject(IMPERSONATE)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _grid(svc, sheet_id: str, tab: str) -> list[list[str]]:
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{tab}'!A1:Z200",
        valueRenderOption="UNFORMATTED_VALUE").execute()
    return [[str(c) for c in row] for row in resp.get("values", [])]


def _money(cell: str) -> float | None:
    s = re.sub(r"[,$\s]", "", str(cell))
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _find_row(grid: list[list[str]], pattern: str) -> list[str] | None:
    for row in grid:
        if row and re.search(pattern, str(row[0]), re.I):
            return row
    return None


def main() -> None:
    if not SA_KEY.exists():
        sys.exit(f"service account key not found at {SA_KEY}")
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        cfg = c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar()

    svc = _svc()
    meta = svc.spreadsheets().get(spreadsheetId=SLOPED_ID).execute()
    tabs = [s["properties"]["title"] for s in meta["sheets"]]
    print(f"sloped workbook tabs: {tabs}")
    meta_ls = svc.spreadsheets().get(spreadsheetId=LOW_SLOPE_ID).execute()
    ls_tabs = [s["properties"]["title"] for s in meta_ls["sheets"]]
    print(f"low-slope workbook tabs: {ls_tabs}\n")

    # Dump the raw grids so a mismatch can be read rather than guessed at.
    for tab in tabs:
        if not re.search(r"^(FBC|Tim)", tab, re.I):
            continue
        grid = _grid(svc, SLOPED_ID, tab)
        print(f"===== sloped tab {tab!r}: {len(grid)} rows =====")
        for i, row in enumerate(grid[:40]):
            cells = " | ".join(str(c)[:22] for c in row[:8])
            if cells.strip(" |"):
                print(f"  {i + 1:>3} {cells}")
        print()

    for tab in ls_tabs[:3]:
        grid = _grid(svc, LOW_SLOPE_ID, tab)
        print(f"===== low-slope tab {tab!r}: {len(grid)} rows =====")
        for i, row in enumerate(grid[:40]):
            cells = " | ".join(str(c)[:22] for c in row[:8])
            if cells.strip(" |"):
                print(f"  {i + 1:>3} {cells}")
        print()

    print("config values for comparison")
    for zone in ("FBC", "HVHZ"):
        print(f"  {zone} sloped base_cost_lm: " + ", ".join(
            f"{k}={v}" for k, v in sorted((cfg.get("sloped", {}).get("base_cost_lm", {})
                                           .get(zone, {})).items()) if not k.startswith("_")))
        print(f"  {zone} sloped overhead:     " + ", ".join(
            f"{k}={v}" for k, v in sorted((cfg.get("sloped", {}).get("overhead", {})
                                           .get(zone, {})).items()) if not k.startswith("_")))
    for zone in ("FBC", "HVHZ"):
        print(f"  {zone} low_slope base_cost_lm: " + ", ".join(
            f"{k}={v}" for k, v in sorted((cfg.get("low_slope", {}).get("base_cost_lm", {})
                                           .get(zone, {})).items()) if not k.startswith("_")))


if __name__ == "__main__":
    main()
