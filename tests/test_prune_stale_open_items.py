"""Tests for scripts/prune_stale_open_items.py's open_items() — the pure classification
function deciding which Tim-verify items are still genuinely open. No DB, no I/O: the
script's main() touches the DB but open_items() is a plain dict -> list[str] function.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_open_items():
    path = Path(__file__).parent.parent / "scripts" / "prune_stale_open_items.py"
    spec = importlib.util.spec_from_file_location("prune_stale_open_items", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.open_items


open_items = _load_open_items()


def _codes(items: list[str]) -> set[str]:
    return {i.split(":")[0] for i in items}


# ---------------------------------------------------------------------------
# OI-3 — insulation_by_thickness is the current key; insulation_tiers no longer gates this.
# ---------------------------------------------------------------------------

def test_oi3_closed_when_insulation_by_thickness_filled():
    cfg = {"low_slope": {"insulation_by_thickness": {"1in": 255, "1_5in": 275, "2in": 310}}}
    assert "OI-3" not in _codes(open_items(cfg))


def test_oi3_open_when_insulation_by_thickness_missing():
    cfg = {"low_slope": {}}
    assert "OI-3" in _codes(open_items(cfg))


def test_oi3_open_when_insulation_by_thickness_has_a_null():
    cfg = {"low_slope": {"insulation_by_thickness": {"1in": 255, "1_5in": None, "2in": 310}}}
    assert "OI-3" in _codes(open_items(cfg))


def test_oi3_ignores_legacy_insulation_tiers():
    """A config carrying only the legacy null-breakpoint rows (the old trigger for this item)
    must still report OI-3 as open on the CURRENT key's absence, not on the legacy shape."""
    cfg = {"low_slope": {"insulation_tiers": [[None, 255], [None, 275], [None, 310]]}}
    assert "OI-3" in _codes(open_items(cfg))


# ---------------------------------------------------------------------------
# OI-5 — plywood_replacement.per_sheet is the current key; deck_types.plywood_replace no
# longer gates this (it stays null on purpose — wrong unit).
# ---------------------------------------------------------------------------

def test_oi5_closed_when_plywood_replacement_filled():
    cfg = {"plywood_replacement": {"per_sheet": {"5_8in": 120, "1_2in": 110, "3_4in": 145}}}
    assert "OI-5" not in _codes(open_items(cfg))


def test_oi5_open_when_plywood_replacement_missing():
    cfg = {}
    assert "OI-5" in _codes(open_items(cfg))


def test_oi5_open_when_a_thickness_rate_is_null():
    cfg = {"plywood_replacement": {"per_sheet": {"5_8in": 120, "1_2in": None, "3_4in": 145}}}
    assert "OI-5" in _codes(open_items(cfg))


def test_oi5_ignores_legacy_deck_types_plywood_replace():
    """deck_types.plywood_replace staying null on purpose must not reopen OI-5 once the real
    per-sheet key is filled."""
    cfg = {
        "low_slope": {"deck_types": {"existing_concrete": 0, "plywood_replace": None}},
        "plywood_replacement": {"per_sheet": {"5_8in": 120, "1_2in": 110, "3_4in": 145}},
    }
    assert "OI-5" not in _codes(open_items(cfg))
