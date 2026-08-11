#!/usr/bin/env python3
"""Mutation-test the warranty layer's gates: break the thing each one guards, prove it FAILS.

A passing test suite says nothing about whether the suite would notice a regression. This repo has
already shipped two gates that could not fail — a checker.js check that was a spelling check
(2026-08-01) and `2400 PGA Blvd` pinned as "Tim's client" when it was a stand-in nobody had
verified (2026-08-07). Both were green the whole time.

So each mutation below damages the asset or the source in the specific way a gate claims to catch,
runs ONLY that gate, and asserts it goes red. A mutation that leaves the suite green is a gate that
is decorative, and it is reported as SURVIVED.

Every mutation is applied to a backup-and-restore copy of the real file; the tree is left byte
identical. Verified by hashing before and after.

Usage: .venv/bin/python scripts/mutate_tidal_gates.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "wp-plugin/perkins-metal-warranty/assets"
TIDAL = ASSETS / "tidal.geojson"
CHECKER = ASSETS / "checker.js"
PHP = ROOT / "wp-plugin/perkins-metal-warranty/perkins-metal-warranty.php"
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-x"]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---- mutations: each takes the parsed/raw content and returns the damaged version -------------

def m_drop_nhd(doc: dict) -> dict:
    """Delete every NHD-sourced reach — i.e. rebuild the pre-2026-08-07 coverage hole."""
    doc["geometries"] = [g for g in doc["geometries"] if g.get("nhd_ftype") is None]
    return doc


def m_demote_mapped(doc: dict) -> dict:
    """Relabel every `mapped` reach `inferred`: correct geometry, no longer moves a verdict."""
    for g in doc["geometries"]:
        if g.get("confidence") == "mapped":
            g["confidence"] = "inferred"
    return doc


def m_drag_mapped_inland(doc: dict) -> dict:
    """Drag one mapped reach 0.5 deg west — out of its marine polygon, deep inland."""
    for g in doc["geometries"]:
        if g.get("confidence") == "mapped" and len(g["coordinates"]) > 3:
            g["coordinates"] = [[x - 0.5, y] for x, y in g["coordinates"]]
            return doc
    raise AssertionError("no mapped reach to drag")


def m_salt_at_golden_gate(doc: dict) -> dict:
    """Plant verdict-moving water 200 ft from the Golden Gate Estates false-VOID pin."""
    doc["geometries"].append({
        "type": "LineString", "confidence": "mapped",
        "coordinates": [[-81.6431, 26.1876], [-81.6425, 26.1882]],
        "wbid": {"wbid": "0000", "name": "PLANTED", "water_class": "3M", "water_type": "ESTUARY"}})
    return doc


def m_close_a_ring(doc: dict) -> dict:
    """Emit a closed ring (a pond outline) as verdict-moving geometry."""
    for g in doc["geometries"]:
        if g.get("confidence") == "mapped" and len(g["coordinates"]) > 3:
            g["coordinates"] = g["coordinates"] + [list(g["coordinates"][0])]
            return doc
    raise AssertionError("no mapped reach to close")


def m_strip_measurement(doc: dict) -> dict:
    """Drop the station citation from a `measured` reach — the number with nothing behind it."""
    for g in doc["geometries"]:
        if g.get("confidence") == "measured" and g.get("measurement"):
            del g["measurement"]
            return doc
    raise AssertionError("no measured reach to strip")


def m_checker_drops_mapped(js: str) -> str:
    """checker.js keeps the literal 'mapped' but routes it to the caveat bucket.

    This is the mutation the OLD regex-based test could not see, and the reason that test was
    rewritten to execute flatten() instead.
    """
    return js.replace(
        "var verdictMoving = g.confidence === 'measured' || g.confidence === 'tagged'",
        "var verdictMoving = false || g.confidence === 'measured' || g.confidence === 'tagged'"
    ).replace("|| g.confidence === 'mapped'", "|| (g.confidence === 'mapped' && false)")


def m_unmemoise_gmaps(js: str) -> str:
    """Undo the loadGmaps latch — the double Maps injection that hung the tool."""
    return js.replace("\t\tif (gmapsReady) return gmapsReady;\n", "")


def m_version_drift(php: str) -> str:
    """Bump the constant, forget the header — exactly what shipped as 1.6.0.

    Matched by pattern, not by the literal version: pinning the string here meant that bumping the
    plugin turned this mutation into a silent no-op, and a mutation that changes nothing reports
    its gate as decorative when the gate is fine. (It did, at 1.7.0.)
    """
    out, n = re.subn(r"(define\(\s*'PERKINS_MWC_VERSION',\s*')[^']+(')",
                     r"\g<1>9.9.9\g<2>", php)
    if n != 1:
        raise SystemExit("m_version_drift matched the version constant "
                         f"{n} times, expected exactly 1 — the mutation is not doing anything.")
    return out


MUTATIONS = [
    (TIDAL, "json", m_drop_nhd, "tests/jobs/test_tidal_asset_invariants.py",
     "test_verdict_moving_water_reaches_the_waterfront_pins",
     "the NHD coverage hole: waterfront houses read warranty-safe"),
    (TIDAL, "json", m_demote_mapped, "tests/jobs/test_tidal_asset_invariants.py",
     "test_the_asset_actually_contains_mapped_geometry",
     "FDEP classification silently absent"),
    (TIDAL, "json", m_drag_mapped_inland, "tests/jobs/test_tidal_asset_invariants.py",
     "test_no_mapped_geometry_lies_outside_a_marine_polygon",
     "mapped water dragged outside the polygon that authorises it"),
    (TIDAL, "json", m_salt_at_golden_gate, "tests/jobs/test_tidal_asset_invariants.py",
     "test_no_verdict_moving_water_within_a_mile_of_the_inland_pins",
     "false VOID planted at Golden Gate Estates"),
    (TIDAL, "json", m_close_a_ring, "tests/jobs/test_tidal_asset_invariants.py",
     "test_no_closed_rings_are_emitted_as_verdict_moving_geometry",
     "a pond outline emitted as a channel"),
    (TIDAL, "json", m_strip_measurement, "tests/jobs/test_tidal_asset_invariants.py",
     "test_every_measured_reach_cites_a_station",
     "a measured reading with no station behind it"),
    (CHECKER, "text", m_checker_drops_mapped, "tests/jobs/test_tidal_asset_invariants.py",
     "test_checker_js_moves_verdicts_on_exactly_the_python_classes",
     "checker.js stops letting `mapped` move a verdict"),
    (CHECKER, "text", m_unmemoise_gmaps, "tests/jobs/test_tidal_asset_invariants.py",
     "test_loadgmaps_injects_the_maps_api_once",
     "the double Maps injection that hung on 'Finding the address'"),
    (PHP, "text", m_version_drift, "tests/test_wp_metal_warranty_guide.py",
     "test_the_plugin_declares_one_version_twice_and_they_agree",
     "plugin header and constant drift apart"),
]


def main() -> None:
    results = []
    for path, kind, mutate, test_file, test_name, what in MUTATIONS:
        before = _sha(path)
        backup = path.with_suffix(path.suffix + ".mutbak")
        shutil.copy2(path, backup)
        try:
            if kind == "json":
                doc = json.loads(path.read_text())
                path.write_text(json.dumps(mutate(doc), separators=(",", ":")))
            else:
                path.write_text(mutate(path.read_text()))
            if _sha(path) == before:
                results.append(("NO-OP", test_name, what))
                continue
            proc = subprocess.run(PYTEST + [test_file, "-k", test_name],
                                  cwd=ROOT, capture_output=True, text=True, timeout=1800)
            # returncode 1 == a test failed, which is the PASS condition here. 5 == none collected,
            # which means the -k selector matched nothing: a gate that does not exist cannot fail,
            # and that must not read as success.
            if proc.returncode == 5 or "no tests ran" in proc.stdout:
                results.append(("NO SUCH TEST", test_name, what))
            elif proc.returncode == 0:
                results.append(("SURVIVED", test_name, what))
            else:
                results.append(("caught", test_name, what))
        finally:
            shutil.move(str(backup), str(path))
            assert _sha(path) == before, f"failed to restore {path}"

    print(f"\n{'=' * 92}\nMUTATION RESULTS — 'caught' means the gate went red, which is what we want\n")
    bad = 0
    for status, test, what in results:
        flag = "  ok  " if status == "caught" else "**BAD**"
        if status != "caught":
            bad += 1
        print(f" {flag} [{status:<12}] {what}\n           gate: {test}")
    print(f"\n{len(results) - bad}/{len(results)} gates caught their mutation.")
    if bad:
        print("A gate that stays green while the thing it guards is broken is decorative.")
        raise SystemExit(1)
    print("Every gate is load-bearing.")


if __name__ == "__main__":
    main()
