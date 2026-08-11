"""How close is an address to salt water, and what does that do to the metal warranty.

This is the SAME question the public warranty checker answers, against the SAME assets
(`wp-plugin/perkins-metal-warranty/assets/`: the coastline, the tidal/brackish layer, and the
per-manufacturer setbacks in zones.json). It is here so the estimator and the proposal can ask it
too, rather than a second implementation drifting away from the one customers see — this repo's
most-repeated defect is two copies of one rule.

Geometry notes, both inherited from `checker.js` because agreeing with the public tool matters
more than any refinement:

  * distance is point-to-SEGMENT, not point-to-vertex. A house across from the middle of a long
    straight reach is near the water even when the nearest drawn vertex is a mile up the channel.
  * only `measured` / `tagged` / `mapped` reaches move a verdict. An `inferred` reach — map data
    suggesting a canal *might* connect to the ocean — raises a caveat and never moves anything.
    See docs/WARRANTY_TOOL_TIDAL_LAYER.md.

Loading is lazy and cached: ~500k segments as numpy arrays is ~20 MB and about a second, paid
once per process, against 191 MB and a 0.13s scan if the same data is held as Python tuples.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

#: Repo-relative home of the warranty assets. The plugin owns them; we read, never write.
ASSET_DIR = Path(__file__).resolve().parent.parent / "wp-plugin" / "perkins-metal-warranty" / "assets"

#: Confidence classes allowed to move a verdict — identical to checker.js's `verdictMoving`.
VERDICT_MOVING = frozenset({"measured", "tagged", "mapped", "coast"})

FT_PER_M = 3.28084

#: Distance under which an estimate should quote the Coastal package. This is the widest setback
#: any manufacturer in zones.json applies to a MATERIAL Perkins actually sells (Englert's ½ mile),
#: so the flag turns on wherever any brand's coverage is affected rather than at one brand's line.
COASTAL_TRIGGER_FT = 2640.0


@dataclass(frozen=True)
class SaltWater:
    distance_ft: float | None          # None when no mapped water is in range at all
    waterfront: bool                   # inside COASTAL_TRIGGER_FT
    confidence: str                    # measured | tagged | mapped | coast
    water_name: str | None
    materials: list[dict[str, Any]]     # per material: name + per-manufacturer verdicts
    warranty_terms: list[dict[str, Any]]  # the standard metal warranty Perkins actually sells
    note: str


def _load_segments(path: Path, keep: frozenset[str] | None) -> tuple:
    """(ax, ay, cx, cy) arrays plus per-segment confidence/name, from a GeoJSON of LineStrings."""
    doc = json.loads(path.read_text())
    geoms = (doc["geometries"] if doc.get("type") == "GeometryCollection"
             else [f["geometry"] for f in doc["features"]])
    ax, ay, cx, cy, conf, name = [], [], [], [], [], []
    for g in geoms:
        c = g.get("coordinates") or []
        k = g.get("confidence", "coast")
        if keep is not None and k not in keep:
            continue
        n = (g.get("wbid") or {}).get("name")
        for i in range(len(c) - 1):
            ax.append(c[i][0])
            ay.append(c[i][1])
            cx.append(c[i + 1][0])
            cy.append(c[i + 1][1])
            conf.append(k)
            name.append(n)
    return (np.array(ax), np.array(ay), np.array(cx), np.array(cy), conf, name)


@lru_cache(maxsize=1)
def _layers() -> dict[str, Any]:
    """Coastline + verdict-moving tidal water + the manufacturer setbacks. Cached per process."""
    coast = _load_segments(ASSET_DIR / "coastline.geojson", None)
    tidal = _load_segments(ASSET_DIR / "tidal.geojson", VERDICT_MOVING)
    zones = json.loads((ASSET_DIR / "zones.json").read_text())
    # One combined array so a single scan answers "nearest salt water of any kind".
    combined = tuple(np.concatenate([coast[i], tidal[i]]) for i in range(4)) + (
        coast[4] + tidal[4], coast[5] + tidal[5])
    return {"segments": combined, "zones": zones}


def _nearest(lat: float, lon: float, segs) -> tuple[float, str, str | None]:
    """Metres to the nearest segment, vectorised. Same maths as checker.js, point-to-segment."""
    ax, ay, cx, cy, conf, name = segs
    # Local equirectangular metres — exact enough at these distances and far cheaper than haversine.
    kx = 111320.0 * math.cos(math.radians(lat))
    ky = 110540.0
    near = (np.abs(ax - lon) <= 0.3) & (np.abs(ay - lat) <= 0.3)
    idx = np.flatnonzero(near)
    if idx.size == 0:
        return float("inf"), "", None
    axs, ays, cxs, cys = ax[idx], ay[idx], cx[idx], cy[idx]
    px, py = (lon - axs) * kx, (lat - ays) * ky
    vx, vy = (cxs - axs) * kx, (cys - ays) * ky
    l2 = vx * vx + vy * vy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.clip(np.where(l2 > 0, (px * vx + py * vy) / l2, 0.0), 0.0, 1.0)
    d = np.hypot(px - t * vx, py - t * vy)
    j = int(np.argmin(d))
    hit = int(idx[j])
    return float(d[j]), conf[hit], name[hit]


def verdict_for(provision: dict, distance_ft: float) -> tuple[str, str]:
    """(state, phrase) for ONE manufacturer at this distance. Mirrors the checker's classes."""
    void = provision.get("void_within_ft")
    cond = provision.get("conditional_within_ft")
    if void and distance_ft < float(void):
        return "void", f"No warranty within {int(void):,} ft"
    if cond and distance_ft < float(cond):
        return "cond", f"Covered, with conditions inside {int(cond):,} ft"
    return "ok", "Covered at this distance"


def _warranty_terms(layers: dict[str, Any]) -> list[dict[str, Any]]:
    """The metal warranty Perkins actually sells, from zones.json.

    Quoted from Perkins' own proposal (Tim Kanak, "Metal and Flat Re-Roof", 5/26/2026) rather
    than written here, so the number of years on a proposal and the number in the warranty data
    cannot drift apart. Returns [] when the key is absent — the section just does not print.
    """
    return list((layers["zones"].get("standard_warranty") or {}).get("terms") or [])


def check(lat: float, lon: float) -> SaltWater:
    """Distance to salt water at this point, and what every manufacturer does about it."""
    layers = _layers()
    metres, confidence, water_name = _nearest(lat, lon, layers["segments"])
    if metres == float("inf"):
        return SaltWater(None, False, "", None, [], _warranty_terms(layers),
                         "No mapped salt water near this address — tidal waterways are mapped "
                         "for South Florida only.")
    ft = metres * FT_PER_M
    materials = []
    for m in layers["zones"].get("materials", []):
        rows = []
        for p in m.get("provisions", []):
            state, phrase = verdict_for(p, ft)
            rows.append({"manufacturer": p["manufacturer"], "state": state,
                         "phrase": phrase, "note": p.get("note", "")})
        worst = ("void" if any(r["state"] == "void" for r in rows)
                 else "cond" if any(r["state"] == "cond" for r in rows) else "ok")
        materials.append({"name": m["name"], "blurb": m.get("blurb", ""),
                          "state": worst, "manufacturers": rows})
    waterfront = ft < COASTAL_TRIGGER_FT
    note = (f"{ft:,.0f} ft to mapped salt water"
            + (f" ({water_name})" if water_name else "")
            + (" — inside at least one manufacturer's setback, so the Coastal package applies."
               if waterfront else " — outside every manufacturer's published setback."))
    return SaltWater(round(ft, 1), waterfront, confidence, water_name, materials,
                     _warranty_terms(layers), note)
