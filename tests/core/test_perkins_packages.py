"""Unit tests for core/perkins_packages.py — pure sell-price table."""
from decimal import Decimal

import pytest

from core.perkins_packages import (
    METAL,
    SHINGLE,
    TILE,
    package_prices_snapshot,
    sell_price_per_sq,
)


def test_protector_returns_base():
    assert sell_price_per_sq("shingle", "PROTECTOR") == SHINGLE["PROTECTOR"]
    assert sell_price_per_sq("tile", "PROTECTOR") == TILE["PROTECTOR"]


def test_additive_tier_is_base_plus_adder():
    assert sell_price_per_sq("shingle", "COASTAL") == SHINGLE["PROTECTOR"] + SHINGLE["COASTAL"]
    assert sell_price_per_sq("tile", "PREFERRED") == TILE["PROTECTOR"] + TILE["PREFERRED"]


def test_standalone_bases_are_not_additive():
    # PROLONG (flat) and CARIBBEAN (metal) are independent full-price bases.
    from core.perkins_packages import FLAT
    assert sell_price_per_sq("flat", "PROLONG") == FLAT["PROLONG"]
    assert sell_price_per_sq("metal", "CARIBBEAN") == METAL["CARIBBEAN"]


def test_coastal_caribbean_is_adder_on_caribbean_not_protector():
    expected = METAL["CARIBBEAN"] + METAL["COASTAL_CARIBBEAN"]
    assert sell_price_per_sq("metal", "COASTAL_CARIBBEAN") == expected


def test_case_insensitive_system():
    assert sell_price_per_sq("SHINGLE", "PROTECTOR") == SHINGLE["PROTECTOR"]


def test_unknown_system_or_tier_raises():
    with pytest.raises(KeyError):
        sell_price_per_sq("thatch", "PROTECTOR")
    with pytest.raises(KeyError):
        sell_price_per_sq("shingle", "NOPE")


def test_package_prices_snapshot_is_fixed_point_strings():
    snap = package_prices_snapshot("shingle")
    assert set(snap) == set(SHINGLE)
    assert snap["PROTECTOR"] == format(SHINGLE["PROTECTOR"], "f")
    # every value round-trips to the original Decimal
    assert all(Decimal(v) == SHINGLE[k] for k, v in snap.items())
