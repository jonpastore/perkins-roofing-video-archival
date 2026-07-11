"""Perkins Roofing sell-price table — JB3 proposal engine.

Encode the live Knowify catalog sell prices as $/square.
PROTECTOR is always the base; other tiers are ADDITIVE adders on top of PROTECTOR
unless noted (CARIBBEAN metal and PROLONG flat are independent full-price bases).

All prices are Decimal; callers must NOT hard-code these — freeze_quote_snapshot
pins them at quote-issue time so later edits do not retro-change issued proposals.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

# ---------------------------------------------------------------------------
# Roof systems / tiers
# ---------------------------------------------------------------------------
RoofSystem = Literal["shingle", "tile", "flat", "metal"]
TileTier = Literal["PROTECTOR", "PREFERRED", "PREMIUM_CARIBBEAN", "PREMIUM_MEDITERRANEAN", "PREMIUM_MODERN", "COASTAL"]
ShingleTier = Literal["PROTECTOR", "PREFERRED", "PREMIUM", "COASTAL"]
FlatTier = Literal["PROTECTOR", "PREFERRED", "PREMIUM", "PROLONG", "RESTORE"]
MetalTier = Literal["PROTECTOR", "PREFERRED", "PREMIUM", "COASTAL", "HVHZ_COASTAL", "CARIBBEAN", "COASTAL_CARIBBEAN"]

# ---------------------------------------------------------------------------
# Shingle ($/sq)
# COASTAL / PREFERRED / PREMIUM are adders on PROTECTOR base
# ---------------------------------------------------------------------------
SHINGLE: dict[str, Decimal] = {
    "PROTECTOR":  Decimal("650.00"),
    "PREFERRED":  Decimal("42.50"),   # adder
    "PREMIUM":    Decimal("165.00"),  # adder
    "COASTAL":    Decimal("215.00"),  # adder
}

# ---------------------------------------------------------------------------
# Tile ($/sq)
# PREFERRED / PREMIUM_* / COASTAL are adders on PROTECTOR base
# ---------------------------------------------------------------------------
TILE: dict[str, Decimal] = {
    "PROTECTOR":           Decimal("1100.00"),
    "PREFERRED":           Decimal("160.00"),   # adder
    "PREMIUM_CARIBBEAN":   Decimal("290.00"),   # adder
    "PREMIUM_MEDITERRANEAN": Decimal("365.00"), # adder
    "PREMIUM_MODERN":      Decimal("485.00"),   # adder
    "COASTAL":             Decimal("47.50"),    # adder — non-corrosive metals upgrade
}

# ---------------------------------------------------------------------------
# Flat ($/sq)
# PREFERRED / PREMIUM / RESTORE are adders on PROTECTOR base
# PROLONG is an independent full-price base (not an adder)
# ---------------------------------------------------------------------------
FLAT: dict[str, Decimal] = {
    "PROTECTOR":  Decimal("850.00"),
    "PREFERRED":  Decimal("175.00"),  # adder
    "PREMIUM":    Decimal("315.00"),  # adder
    "PROLONG":    Decimal("500.00"),  # independent base (not on PROTECTOR)
    "RESTORE":    Decimal("115.00"),  # adder
}

# PROLONG is a standalone base, not additive
FLAT_STANDALONE_BASES = {"PROLONG"}

# ---------------------------------------------------------------------------
# Metal ($/sq)
# PREFERRED / PREMIUM / COASTAL / HVHZ_COASTAL / COASTAL_CARIBBEAN are adders
# CARIBBEAN is an independent full-price base
# ---------------------------------------------------------------------------
METAL: dict[str, Decimal] = {
    "PROTECTOR":      Decimal("1125.00"),
    "PREFERRED":      Decimal("115.00"),   # adder
    "PREMIUM":        Decimal("115.00"),   # adder
    "COASTAL":        Decimal("430.00"),   # adder — aluminum Kynar upgrade
    "HVHZ_COASTAL":   Decimal("365.00"),   # adder — HVHZ-rated aluminum
    "CARIBBEAN":      Decimal("1000.00"),  # independent base
    "COASTAL_CARIBBEAN": Decimal("225.00"), # adder on CARIBBEAN
}

METAL_STANDALONE_BASES = {"CARIBBEAN"}

# Map system string → price table
_TABLES: dict[str, dict[str, Decimal]] = {
    "shingle": SHINGLE,
    "tile":    TILE,
    "flat":    FLAT,
    "metal":   METAL,
}

_STANDALONE: dict[str, set[str]] = {
    "shingle": set(),
    "tile":    set(),
    "flat":    FLAT_STANDALONE_BASES,
    "metal":   METAL_STANDALONE_BASES,
}


def sell_price_per_sq(system: str, tier: str) -> Decimal:
    """Return the sell price ($/sq) for a system+tier combination.

    For PROTECTOR: returns the base price directly.
    For additive tiers: returns PROTECTOR + adder.
    For standalone bases (CARIBBEAN metal, PROLONG flat): returns that base directly.
    For COASTAL_CARIBBEAN: returns CARIBBEAN base + COASTAL_CARIBBEAN adder (NOT PROTECTOR).

    Raises KeyError for unknown system or tier.
    """
    system = system.lower()
    table = _TABLES[system]
    standalone = _STANDALONE[system]
    if tier == "PROTECTOR":
        return table["PROTECTOR"]
    if tier in standalone:
        return table[tier]
    # COASTAL_CARIBBEAN is an adder on CARIBBEAN, not on PROTECTOR
    if system == "metal" and tier == "COASTAL_CARIBBEAN":
        return table["CARIBBEAN"] + table["COASTAL_CARIBBEAN"]
    return table["PROTECTOR"] + table[tier]


def package_prices_snapshot(system: str) -> dict[str, str]:
    """Return the full price table for a system as {tier: str($/sq)} for snapshotting.

    All values serialized as fixed-point strings (4 dp) for stable hashing.
    """
    system = system.lower()
    table = _TABLES[system]
    return {tier: format(price, "f") for tier, price in table.items()}
