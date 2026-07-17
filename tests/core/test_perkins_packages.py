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


# ---------------------------------------------------------------------------
# package_options — full menu for the quote builder (Zoom 2026-07-17)
# ---------------------------------------------------------------------------

def test_package_options_tile_matches_greener_proposal():
    from core.perkins_packages import package_options
    opts = {o["key"]: o for o in package_options("13_tile", 43, 51950.0)}
    assert opts["PROTECTOR"]["total"] == 51950.0
    assert opts["PREFERRED"]["addl_price"] == 165 * 43            # $7,095 — Greener PDF
    assert opts["PREMIUM_CARIBBEAN"]["addl_price"] == 290 * 43    # $12,470
    assert opts["PREMIUM_MEDITERRANEAN"]["addl_price"] == 365 * 43  # $15,695
    assert opts["PREMIUM_MODERN"]["addl_price"] == 485 * 43       # $20,855
    assert opts["COASTAL"]["addl_price"] == 47.5 * 43


def test_package_options_standalone_metal_caribbean():
    from core.perkins_packages import package_options
    opts = {o["key"]: o for o in package_options("standing_seam_metal", 10, 12000.0)}
    assert opts["CARIBBEAN"]["standalone"] is True
    assert opts["CARIBBEAN"]["total"] == 1000 * 10
    assert opts["COASTAL_CARIBBEAN"]["total"] == (1000 + 225) * 10


def test_package_options_unknown_roof_type_empty():
    from core.perkins_packages import package_options
    assert package_options("mystery", 10, 1000.0) == []


def test_package_options_standalone_reflects_discount():
    """Standalone bases (metal CARIBBEAN, flat PROLONG) must subtract the resolved
    discount too — else a discounted quote loses its discount on those tiers."""
    from core.perkins_packages import package_options
    # metal: PROTECTOR total already post-discount ($200 off a $12,000 base)
    opts = {o["key"]: o for o in package_options("standing_seam_metal", 10, 11800.0, discount_total=200.0)}
    # CARIBBEAN standalone = 1000*10 - 200 discount = 9800 (not 10000)
    assert opts["CARIBBEAN"]["total"] == 1000 * 10 - 200
    # COASTAL_CARIBBEAN = (1000+225)*10 - 200 = 12050
    assert opts["COASTAL_CARIBBEAN"]["total"] == (1000 + 225) * 10 - 200
    # additive tier inherits discount through protector, not double-counted
    assert opts["PREFERRED"]["total"] == 11800.0 + opts["PREFERRED"]["adder_per_sq"] * 10


def test_package_options_no_discount_unchanged():
    from core.perkins_packages import package_options
    a = package_options("standing_seam_metal", 10, 12000.0)
    b = package_options("standing_seam_metal", 10, 12000.0, discount_total=0.0)
    assert a == b
