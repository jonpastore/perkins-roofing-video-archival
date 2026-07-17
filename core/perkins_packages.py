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
    "PREFERRED":           Decimal("165.00"),   # adder — verified Greener proposal 7/17: $7,095/43sq
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


# Estimator roof_type → package system
_ROOF_TYPE_SYSTEM: dict[str, str] = {
    "13_tile": "tile", "barrel_tile": "tile",
    "3tab_shingle": "shingle", "dimensional_shingle": "shingle",
    "standing_seam_metal": "metal",
    "tpo": "flat", "bur": "flat", "coatings": "flat", "silicone": "flat",
}

_TIER_LABELS: dict[str, str] = {
    "PROTECTOR": "Perkins Protector",
    "PREFERRED": "Perkins Preferred",
    "PREMIUM": "Perkins Premium",
    "PREMIUM_CARIBBEAN": "Perkins Premium (Caribbean)",
    "PREMIUM_MEDITERRANEAN": "Perkins Premium (Mediterranean)",
    "PREMIUM_MODERN": "Perkins Premium (Modern)",
    "COASTAL": "Coastal Upgrade",
    "HVHZ_COASTAL": "HVHZ Coastal Upgrade",
    "CARIBBEAN": "Caribbean (standalone)",
    "COASTAL_CARIBBEAN": "Coastal Caribbean",
    "PROLONG": "Prolong (standalone)",
    "RESTORE": "Restore",
}


def package_options(roof_type: str, num_squares: float, protector_total: float,
                    discount_total: float = 0.0) -> list[dict]:
    """Full package menu for a quote (Zoom 2026-07-17 [51:56]: offer ALL premiums + coastal).

    PROTECTOR's total comes from the ESTIMATOR ENGINE (cuts/OH/profit aware) — the
    catalog PROTECTOR $/sq is intentionally ignored. Adder tiers are flat catalog
    prices × squares layered on the engine total (upgrades don't re-price cuts —
    "it's just a swap of materials" [24:00]). Standalone bases (CARIBBEAN metal,
    PROLONG flat) are their own catalog price × squares.

    protector_total is already POST-discount, so additive tiers inherit the discount
    through it. Standalone bases don't build on protector, so the same resolved
    discount_total ($) is subtracted from them explicitly — otherwise a discounted
    metal/flat quote would lose its discount the moment the customer picked a
    standalone tier.
    """
    system = _ROOF_TYPE_SYSTEM.get(roof_type)
    if system is None:
        return []
    table = _TABLES[system]
    standalone = _STANDALONE[system]
    sq = Decimal(str(num_squares))
    prot = Decimal(str(protector_total))
    disc = Decimal(str(discount_total))
    out = [{
        "key": "PROTECTOR", "label": _TIER_LABELS["PROTECTOR"], "system": system,
        "adder_per_sq": None, "addl_price": 0.0, "total": float(prot), "standalone": False,
    }]
    for tier, price in table.items():
        if tier == "PROTECTOR":
            continue
        if tier in standalone:
            total = price * sq - disc
            addl = total - prot
        elif system == "metal" and tier == "COASTAL_CARIBBEAN":
            total = (table["CARIBBEAN"] + price) * sq - disc
            addl = total - prot
        else:
            addl = price * sq
            total = prot + addl
        out.append({
            "key": tier, "label": _TIER_LABELS.get(tier, tier.title()), "system": system,
            "adder_per_sq": float(price), "addl_price": round(float(addl), 2),
            "total": round(float(total), 2), "standalone": tier in standalone,
        })
    return out


def package_prices_snapshot(system: str) -> dict[str, str]:
    """Return the full price table for a system as {tier: str($/sq)} for snapshotting.

    All values serialized as fixed-point strings (4 dp) for stable hashing.
    """
    system = system.lower()
    table = _TABLES[system]
    return {tier: format(price, "f") for tier, price in table.items()}
