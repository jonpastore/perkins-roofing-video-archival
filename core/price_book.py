"""JB1 price-book engine — pure functions, no I/O.

All money math uses Decimal throughout. Unit economics formula:

    price_per_square = unit_price * (1 + tax_rate) * (1 + waste_rate) / unit_coverage

Returns None whenever unit_price is None (not-stocked/unknown) or unit_coverage
is None/0 (not a per-square item). Never substitute 0 for a missing price.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

_Q = Decimal("0.0001")


def _canon(v: object) -> object:
    """Normalize a value to a JSON-safe, canonically-typed form for hashing.

    Decimal and float money fields are quantized to 4dp and serialized as
    fixed-point strings so that ``Decimal("45.0000")``, ``45.0``, ``"45.00"``
    and ``45`` all produce the same hash. Strings, bools, None, and ints pass
    through unchanged. Lists of scalars are NOT sorted here — roof_system_ids
    order is preserved (callers that treat it as a set should sort before
    calling freeze_items; otherwise two logically-equal books with different
    roof_system_ids ordering will hash differently, which is the safe default).
    """
    if isinstance(v, bool):  # bool is a subclass of int — guard first
        return v
    if isinstance(v, Decimal):
        return format(v.quantize(_Q, rounding=ROUND_HALF_UP), "f")
    if isinstance(v, float):
        return format(Decimal(str(v)).quantize(_Q, rounding=ROUND_HALF_UP), "f")
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    return v


def price_per_square(
    unit_price: Decimal | None,
    tax_rate: Decimal,
    waste_rate: Decimal,
    unit_coverage: Decimal | None,
) -> Decimal | None:
    """Landed cost per roofing square for one material item.

    Formula: unit_price * (1 + tax_rate) * (1 + waste_rate) / unit_coverage

    Returns None when:
      - unit_price is None (item not stocked or price unknown)
      - unit_coverage is None or 0 (not a per-square item, e.g. LF accessories)

    Quantized to 4 decimal places (ROUND_HALF_UP).
    """
    if unit_price is None:
        return None
    if not unit_coverage:
        return None
    result = unit_price * (1 + tax_rate) * (1 + waste_rate) / unit_coverage
    return result.quantize(_Q, rounding=ROUND_HALF_UP)


def compute_pricebook_hash(items: list[dict]) -> str:
    """RFC 8785 canonical hash of a price-book item list.

    Items are sorted by (sku, name) for stability before hashing so that
    reordering the list does not change the hash. Any edit to a unit_price,
    tax_rate, waste_rate, or other field produces a new hash.

    Decimal / float values are normalized via _canon before serialization so
    that ORM-hydrated Decimal rows hash identically to their string equivalents
    (e.g. Decimal("45.0000") == "45.0000" after normalization).
    """
    from core.pricing_config import compute_hash

    sorted_items = sorted(items, key=lambda i: (i.get("sku") or "", i.get("name") or ""))
    canonical = [_canon(item) for item in sorted_items]
    return compute_hash({"items": canonical})


def next_version(existing_versions: list[int]) -> int:
    """Next price-book version number: max(existing) + 1, or 1 if none exist."""
    return max(existing_versions, default=0) + 1


def freeze_items(items: list[dict]) -> tuple[list[dict], str]:
    """Return a canonicalized, JSON-serializable snapshot of items and its hash.

    The snapshot is sorted by (sku, name) and all Decimal/float values are
    normalized to 4dp fixed-point strings via _canon — identical to what
    compute_pricebook_hash hashes. Storing the canonical form means:
      - items_snapshot is directly JSON-serializable (no Decimal in the DB)
      - re-hashing the stored snapshot always reproduces config_hash

    Returns:
        (snapshot, config_hash)
    """
    sorted_items = sorted(items, key=lambda i: (i.get("sku") or "", i.get("name") or ""))
    snapshot = [_canon(dict(item)) for item in sorted_items]
    h = compute_pricebook_hash(snapshot)  # _canon is idempotent on already-canonical strings
    return snapshot, h
