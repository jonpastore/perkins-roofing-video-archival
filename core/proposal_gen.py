"""JB3 proposal-generation engine — pure, no I/O.

Public API:
    compose_proposal(inputs, packages, price_book=None) -> dict
    freeze_quote_snapshot(proposal) -> (snapshot, hash)

All money uses Decimal. No side effects, no DB calls, no file I/O.
"""
from __future__ import annotations

import copy
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from core.perkins_packages import package_prices_snapshot, sell_price_per_sq
from core.pricing_config import compute_snapshot_hash

_Q2 = Decimal("0.01")

# T&C version pinned at snapshot time — bump when T&C text changes
TC_VERSION = "v1.0"

# ---------------------------------------------------------------------------
# Payment schedule helpers
# ---------------------------------------------------------------------------

_STANDARD_DRAWS = [
    {"sequence": 1, "label": "Acceptance / prior to permitting",                       "pct": Decimal("0.30")},
    {"sequence": 2, "label": "Material delivery / mobilization",                       "pct": Decimal("0.30")},
    {"sequence": 3, "label": "Completion of roof dry-in, prior to cap installation",   "pct": Decimal("0.30")},
    {"sequence": 4, "label": "Substantial completion (net balance)",                   "pct": None},  # balance
]

_PALMER_DRAWS = [
    {"sequence": 1, "label": "Acceptance / prior to permitting",                       "pct": Decimal("0.15")},
    {"sequence": 2, "label": "Justin acquiring financing",                              "pct": Decimal("0.15")},
    {"sequence": 3, "label": "Material delivery / mobilization",                       "pct": Decimal("0.30")},
    {"sequence": 4, "label": "Completion of roof dry-in, prior to cap installation",   "pct": Decimal("0.30")},
    {"sequence": 5, "label": "Substantial completion (net balance)",                   "pct": None},  # balance
]


def _build_payment_schedule(
    total: Decimal,
    variant: str,
    custom_milestones: list[dict] | None,
) -> dict:
    """Compute draw amounts for the given schedule variant.

    variant: "standard" | "palmer" | "custom"
    custom_milestones: list of {sequence, label, pct} — pct float/Decimal, last draw pct=None for balance.
    """
    if custom_milestones:
        template = [
            {
                "sequence": d["sequence"],
                "label": d["label"],
                "pct": Decimal(str(d["pct"])) if d.get("pct") is not None else None,
            }
            for d in custom_milestones
        ]
        v = "custom"
    elif variant == "palmer":
        template = [dict(d) for d in _PALMER_DRAWS]
        v = "palmer-5-draw-custom"
    else:
        template = [dict(d) for d in _STANDARD_DRAWS]
        v = "standard-30-30-30-balance"

    draws = []
    running = Decimal("0.00")
    for draw in template:
        if draw["pct"] is not None:
            amount = (total * draw["pct"]).quantize(_Q2, rounding=ROUND_HALF_UP)
            running += amount
        else:
            amount = (total - running).quantize(_Q2, rounding=ROUND_HALF_UP)
        draws.append({
            "sequence": draw["sequence"],
            "label": draw["label"],
            "pct": int(draw["pct"] * 100) if draw["pct"] is not None else None,
            "amount": str(amount),
        })
    return {"variant": v, "draws": draws}


# ---------------------------------------------------------------------------
# Expiry rule  (M2 fix: checks scope lines AND metal keyword in extra_lines)
# ---------------------------------------------------------------------------

def _has_metal(scope_lines: list[dict]) -> bool:
    """True if any line is a metal ROOF system (drives the 15-day expiry rule).

    Detected via roof_system=='metal' on a package scope, or an explicit
    is_metal flag on an extra line. A description keyword scan is deliberately
    NOT used: it false-positives on metal accessories like "Copper Metal
    Install" (a flashing line on a shingle job), which must keep the 30-day
    expiry — only a metal ROOF shortens it to 15.
    """
    for line in scope_lines:
        if (line.get("roof_system") or "").lower() == "metal":
            return True
        if line.get("is_metal"):
            return True
    return False


# ---------------------------------------------------------------------------
# Core: compose_proposal
# ---------------------------------------------------------------------------

def compose_proposal(
    inputs: dict[str, Any],
    packages: dict[str, Any] | None = None,
    price_book: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a proposal dict from declarative inputs.

    inputs keys:
        customer:           str — customer name
        property:           str — property address
        project_name:       str — project title (optional)
        hvhz:               bool — HVHZ FBC compliance flag (default False)
        custom_milestones:  list[dict] | None — overrides default payment schedule
        payment_variant:    str — "standard" | "palmer" (default "standard")
        scopes:             list[dict] — package/roof-system lines (see below)
        extra_lines:        list[dict] — non-package lines (gutters, stucco, etc.)
        discounts:          list[dict] — {description, amount} — amount positive; stored negative

    Each scope dict:
        roof_system:    str — "shingle" | "tile" | "flat" | "metal"
        tier:           str — e.g. "PROTECTOR", "COASTAL", "PREMIUM_CARIBBEAN"
        squares:        float | Decimal | None
        description:    str (optional)
        unit_price:     float | Decimal | None — explicit $/sq override (bypasses table)
        is_optional:    bool — if True, line is EXCLUDED from contract_total by default
        included:       bool — if True AND is_optional=True, overrides exclusion (accepted optional)

    Each extra_line dict:
        description:    str
        line_total:     Decimal | float | str — explicit total
        is_optional:    bool — excluded from total if True (unless included=True)
        included:       bool — override for accepted optionals
        is_metal:       bool — set True to trigger 15-day expiry for metal extra lines
        unit_price:     Decimal | float | None
        qty:            Decimal | float | None

    Contract total = sum of all lines where NOT (is_optional AND NOT included).
    FL roofing services: tax = $0.
    """
    customer = inputs.get("customer", "")
    property_addr = inputs.get("property", "")
    project_name = inputs.get("project_name", "")
    hvhz = bool(inputs.get("hvhz", False))
    payment_variant = inputs.get("payment_variant", "standard")
    custom_milestones = inputs.get("custom_milestones")

    scope_lines: list[dict] = []
    line_num = 1

    # --- Package / roof system lines ---
    for scope in inputs.get("scopes", []):
        system = scope["roof_system"].lower()
        tier = scope.get("tier", "PROTECTOR")
        squares = Decimal(str(scope["squares"])) if scope.get("squares") is not None else None
        is_optional = bool(scope.get("is_optional", False))
        included = bool(scope.get("included", False))

        # Resolve unit price: explicit override > table lookup
        if scope.get("unit_price") is not None:
            unit_price = Decimal(str(scope["unit_price"]))
        else:
            unit_price = sell_price_per_sq(system, tier)

        if squares is not None:
            line_total = (unit_price * squares).quantize(_Q2, rounding=ROUND_HALF_UP)
        else:
            line_total = Decimal("0.00")

        scope_lines.append({
            "line_num": line_num,
            "description": scope.get("description", f"PERKINS {tier} - {system.title()} Re-Roof"),
            "roof_system": system,
            "package": tier,
            "squares": str(squares) if squares is not None else None,
            "unit_price": str(unit_price.quantize(_Q2, rounding=ROUND_HALF_UP)),
            "line_total": str(line_total),
            "is_optional": is_optional,
            "included": included,
        })
        line_num += 1

    # --- Extra non-package lines ---
    for extra in inputs.get("extra_lines", []):
        lt = Decimal(str(extra.get("line_total", "0.00")))
        is_optional = bool(extra.get("is_optional", False))
        included = bool(extra.get("included", False))
        scope_lines.append({
            "line_num": line_num,
            "description": extra.get("description", ""),
            "roof_system": None,
            "package": None,
            "squares": str(extra["qty"]) if extra.get("qty") is not None else None,
            "unit_price": (
                str(Decimal(str(extra["unit_price"])).quantize(_Q2))
                if extra.get("unit_price") is not None else None
            ),
            "line_total": str(lt),
            "is_optional": is_optional,
            "included": included,
            "is_metal": bool(extra.get("is_metal", False)),
        })
        line_num += 1

    # --- Discount lines (always included, always negative) ---
    for disc in inputs.get("discounts", []):
        amount = Decimal(str(disc["amount"]))
        scope_lines.append({
            "line_num": line_num,
            "description": disc.get("description", "Discount"),
            "roof_system": None,
            "package": None,
            "squares": None,
            "unit_price": None,
            "line_total": str((-amount).quantize(_Q2, rounding=ROUND_HALF_UP)),
            "is_optional": False,
            "included": True,
        })
        line_num += 1

    # --- Totals (M1 fix: exclude is_optional=True lines unless included=True) ---
    def _in_total(line: dict) -> bool:
        if not line.get("is_optional", False):
            return True
        return bool(line.get("included", False))

    subtotal = sum(
        (Decimal(ln["line_total"]) for ln in scope_lines if _in_total(ln)),
        Decimal("0.00"),
    )
    tax = Decimal("0.00")  # FL roofing services exempt
    contract_total = subtotal + tax

    # --- Expiry (M2 fix: checks all lines including extra_lines) ---
    exp_days = 15 if _has_metal(scope_lines) else 30

    # --- Payment schedule ---
    payment_schedule = _build_payment_schedule(contract_total, payment_variant, custom_milestones)

    return {
        "customer": customer,
        "property": property_addr,
        "project_name": project_name,
        "hvhz": hvhz,
        "scope_lines": scope_lines,
        "subtotal": str(subtotal.quantize(_Q2, rounding=ROUND_HALF_UP)),
        "tax": str(tax),
        "contract_total": str(contract_total.quantize(_Q2, rounding=ROUND_HALF_UP)),
        "payment_schedule": payment_schedule,
        "expiry_days": exp_days,
        "tc_version": TC_VERSION,
    }


# ---------------------------------------------------------------------------
# Snapshot + hash (C1 fix: non-underscore keys; uses compute_snapshot_hash
# which does NOT strip keys — every pinned field IS hashed)
# ---------------------------------------------------------------------------

def freeze_quote_snapshot(
    proposal: dict[str, Any],
    price_book: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Pin a proposal as an immutable snapshot with a content hash.

    Captures:
    - All scope lines with resolved prices (source of truth — no re-derivation on read)
    - Package sell-price tables at snapshot time (per system referenced in proposal)
    - Price-book hash if a price_book dict is provided
    - TC version

    Stored under plain (non-underscore) keys so compute_snapshot_hash includes
    ALL fields. A price-table edit after issuance changes the hash → tamper evident.

    Returns (snapshot, sha256_hex).
    """
    snapshot = copy.deepcopy(proposal)

    # Capture package table for each roof system referenced in scope lines
    systems_seen = {
        ln["roof_system"]
        for ln in proposal.get("scope_lines", [])
        if ln.get("roof_system")
    }
    snapshot["package_tables"] = {
        system: package_prices_snapshot(system)
        for system in sorted(systems_seen)
    }

    if price_book is not None:
        from core.pricing_config import compute_hash
        snapshot["price_book_hash"] = (
            price_book.get("config_hash") or compute_hash(price_book)
        )

    snapshot["tc_version"] = proposal.get("tc_version", TC_VERSION)

    h = compute_snapshot_hash(snapshot)
    return snapshot, h
