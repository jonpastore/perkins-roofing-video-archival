"""Price several structures at one site as ONE bid (pure logic).

Jarvis #430/#449. Tim's Evergrene bid prices 9 buildings at 650 Evergrene Pkwy as one deal. We had
no container for that, so `estimate()` — a pure function of ONE roof — was called nine times and
every site-scoped quantity was silently reinterpreted as roof-scoped and multiplied by nine.

Measured against the live jupiter config (scripts/evergrene_gap_analysis.py):

    every building OVER by +10.2% to +84.9%, ~+15% on the buildings together
    $24,000 of once-per-site fees charged eight times
    $116,420 of project scope (General Conditions + add-on blocks) with nowhere to live

The bid netted to -9% only because the over-charge and the missing scope masked each other. That
is why both halves land together: removing the per-building fees WITHOUT carrying the project
blocks swings the bid to roughly -23%, which is worse and under.

WHAT IS SITE-SCOPED, AND WHY

    delivery_plywood_vents  one truck serves the site. Tim's own sheet agrees — Delivery is a
                            per-building day column that is EMPTY for 8 of 9 rows, with the site
                            figure entered on the totals row.
    new_bonus_values        a back-end crew line, not the customer-facing bonus stack.
                            ⚠️ per mobilisation or per roof completed is genuinely 50/50 —
                            PENDING TIM. Defaulted to per-project because that is what makes
                            Evergrene reconcile.
    permit_processing       a COUNT, not a scope — and the count is ONE PER BUILDING. Tim,
                            2026-08-02, answered directly; verified against his own books, where
                            73 of the 333 Knowify projects carrying a permit line bill more than
                            one (ISOLA CONDOMINIUM ASSOCIATION bills six). `permit_count`
                            therefore defaults to the number of buildings, and an operator who
                            knows the county issued one site permit still says so explicitly.
                            ⚠️ Those Knowify lines are the county's permit FEES passed through;
                            ours is the flat $500 (+$500 commercial) PROCESSING fee. Both scale
                            per structure — his catalog scope reads "you pay permit fee(s) only",
                            plural — but they are not the same money.
    tile_dumpster           a site quantity that is NOT a flat fee. tile_dumpster_count is a
                            ceil(), so nine calls round up nine times — 14 dumpsters against the
                            10 the site needs. Recomputed here over the SUMMED squares.

    stories_3_5_delivery_chute stays per building: a chute is rented for the tall structure.

THE PROFIT FLOOR

Weeks are a property of the crew's stay on the SITE, not of a roof. The crew arrives at Evergrene
once and stays 88 days; summing per-building ceil() gives 20 weeks for an 18-week site.

⚠️ #449 specifies "$2,500 PER SITE PER WEEK". Measured against Tim's own bid that is 17 weeks x
$2,500 = $42,500 against his actual margin of $30,363 — the spec as written still over-prices the
project by 40%. So `basis="week"` is implemented and available, and the DEFAULT is `basis="project"`
(one floor for the whole bid), under which Evergrene's natural margin clears the floor and it never
binds — which is what Tim actually did. Reported, not silently chosen: price_project returns both
numbers so the divergence is visible rather than buried.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from core.estimator import QuoteInput, estimate
from core.pricing_config import PricingConfig

#: Fees the estimator adds once per CALL that are really once per SITE. tile_dumpster is here not
#: because it is flat but because its ceil() must run over the summed squares exactly once.
DEFAULT_ONCE_PER_PROJECT = frozenset({
    "delivery_plywood_vents", "new_bonus_values", "permit_processing", "tile_dumpster",
})

FLOOR_BASES = ("project", "week", "building")

#: The ONLY keys core.estimator._build_fixed honours in `suppress_fixed_keys`. A key outside this
#: set is silently ignored on BOTH sides — not suppressed per building, and not re-added once — so
#: a typo (or the plausible-looking "stories_3_5_delivery_chute", named two lines below in this
#: module's docstring) quietly reverts the bid to per-building pricing at HTTP 200.
SUPPRESSIBLE_FEE_KEYS = frozenset({
    "delivery_plywood_vents", "new_bonus_values", "permit_processing", "tile_dumpster",
})


@dataclass
class ProjectItem:
    """A quoted block belonging to the site rather than to any one roof.

    Tim's General Conditions is (green fence + telehandler $22,800 + full-time PM $9,000) x 1.15
    = $36,570, and on his sheet it is referenced by NO total formula — it stands as its own quoted
    line. His add-on blocks, by contrast, he folds into the Clubhouse.

    ⚠️ ONLY `allocation="project"` IS IMPLEMENTED. `"building:<name>"` is the shape reserved for
    Tim's folding habit, and price_project does not branch on it — it was accepted, echoed back
    and priced as its own line, so a caller asking to fold $42,050 of add-ons into the Clubhouse
    got a page that said it had while the Clubhouse's per-square figure never moved. Refused at
    the boundary until the fold exists, because a silent no-op on money is worse than a 422.
    """
    key: str
    label: str
    cost: float
    markup: float = 1.0
    #: "project" (its own line) | "building:<name>" (folded into one structure, Tim's habit)
    allocation: str = "project"

    @property
    def amount(self) -> float:
        return round(self.cost * self.markup, 2)


@dataclass
class Building:
    """One structure in the bid: a label plus the QuoteInput that prices it."""
    name: str
    quote: QuoteInput
    #: Days the crew is on THIS structure. Used only for the site's week count; when absent the
    #: building contributes its own estimate's series days.
    days: Optional[float] = None
    #: This structure's own street address. OPTIONAL, and normally absent: Tim, 2026-08-02, asked
    #: for per-building addresses "yes but they can share", and sharing is the common case — nine
    #: Evergrene buildings on one parkway. Absent means "the bid project's property", which is
    #: resolved at RENDER time, not here: this module prices, and a street address moves no money.
    #: Two of Evergrene's gates are on different roads, which is the case that needs the column.
    address: Optional[str] = None


@dataclass
class ProjectPricing:
    project_total: float = 0.0
    buildings: list[dict] = field(default_factory=list)
    project_items: list[dict] = field(default_factory=list)
    project_fixed: list[dict] = field(default_factory=list)
    profit: float = 0.0
    floor: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: The count actually priced — reported because it now DEFAULTS to the building count, so a
    #: caller that passed nothing still has to persist and display the number it was charged for.
    permit_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_total": round(self.project_total, 2),
            "buildings": self.buildings,
            "project_items": self.project_items,
            "project_fixed": self.project_fixed,
            "profit": round(self.profit, 2),
            "floor": self.floor,
            "warnings": self.warnings,
            "permit_count": self.permit_count,
        }


def _fixed_once(config: PricingConfig, buildings: list[Building], zone: str,
                once: frozenset[str], permit_count: int) -> list[dict]:
    """The site's share of the fees every building would otherwise have paid in full."""
    out: list[dict] = []
    commercial_count = sum(1 for b in buildings if b.quote.project_kind == "commercial")

    if "delivery_plywood_vents" in once:
        out.append({"key": "delivery_plywood_vents", "label": "Delivery / Plywood / Vents",
                    "amount": float(config.raw["delivery_plywood_vents"]),
                    "basis": "once per site — one truck serves it"})
    if "new_bonus_values" in once:
        out.append({"key": "new_bonus_values", "label": "New Bonus Values",
                    "amount": float(config.raw["new_bonus_values"]),
                    "basis": "once per site (per mobilisation vs per roof — pending Tim)"})
    if "permit_processing" in once:
        base = float(config.raw["permit_processing"])
        # The commercial adder is per COMMERCIAL permit, not per permit. With one commercial
        # structure among nine and permit_count=9 (Palm Beach may issue one per structure), the
        # old `if any(commercial)` charged the adder nine times. min() also gives the right answer
        # for a single site permit: any commercial scope makes that one permit commercial.
        commercial_permits = min(commercial_count, permit_count)
        amount = base * permit_count + float(config.raw["permit_commercial_add"]) * commercial_permits
        label = "Permit Processing" if permit_count == 1 else f"Permit Processing x{permit_count}"
        basis = (f"{permit_count} permit(s) — one per building (Tim, 2026-08-02)"
                 if permit_count == len(buildings)
                 else f"{permit_count} permit(s) — set explicitly, not the {len(buildings)}-building default")
        if commercial_permits:
            basis += f"; commercial adder on {commercial_permits} of them"
        out.append({"key": "permit_processing", "label": label,
                    "amount": round(amount, 2), "basis": basis})
    if "tile_dumpster" in once:
        # ONE ceil over the summed tile squares. Per building this rounds up per building.
        tile_sq = sum(b.quote.num_squares for b in buildings
                      if _tile_involved(b.quote))
        if tile_sq > 0:
            count = config.tile_dumpster_count(tile_sq, zone)
            out.append({"key": "tile_dumpster", "label": "Tile Dumpster",
                        "amount": round(count * float(config.raw["tile_dumpster_cost"]), 2),
                        "basis": f"{count} dumpsters over {tile_sq:g} summed tile squares "
                                 f"(one ceil for the site, not one per building)"})
    return out


def _tile_involved(q: QuoteInput) -> bool:
    """Mirrors the estimator's own test — tile on either side of the job generates dump loads."""
    from core.estimator import _is_tile  # noqa: PLC0415 — internal, kept in one place
    return bool(_is_tile(q.roof_type) or q.existing_roof == "tile")


def price_project(
    config: PricingConfig,
    buildings: list[Building],
    *,
    project_items: Optional[list[ProjectItem]] = None,
    once_per_project: frozenset[str] = DEFAULT_ONCE_PER_PROJECT,
    floor_basis: str = "project",
    permit_count: Optional[int] = None,
) -> dict[str, Any]:
    """Price a multi-structure bid as one deal.

    Each building is priced by the ordinary estimator with the site-scoped fees suppressed and its
    own profit floor disabled; the site's fees are then added ONCE and one floor is applied over
    the whole bid.

    `permit_count=None` (the default) means ONE PERMIT PER BUILDING — Tim's rule, see the module
    docstring. Pass an integer to say the county issued a different number for this site.

    Returns the roll-up as a dict. Raises ValueError on an unknown floor basis or no buildings —
    silently pricing zero buildings as $0 is not a useful answer.
    """
    if not buildings:
        raise ValueError("a bid project needs at least one building")
    names = [b.name for b in buildings]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(
            f"duplicate structure name(s) {dupes} — structure_name is how a persisted project "
            f"tells nine anonymous estimates apart, so duplicates make it unreadable."
        )
    if floor_basis not in FLOOR_BASES:
        raise ValueError(f"floor_basis must be one of {FLOOR_BASES}, got {floor_basis!r}")
    unknown = sorted(set(once_per_project) - SUPPRESSIBLE_FEE_KEYS)
    if unknown:
        raise ValueError(
            f"once_per_project contains key(s) the estimator cannot suppress: {unknown}. "
            f"Valid: {sorted(SUPPRESSIBLE_FEE_KEYS)}. An unrecognised key is ignored on both "
            f"sides, which silently reverts the bid to per-building pricing."
        )

    if permit_count is not None and permit_count < 1:
        raise ValueError(f"permit_count must be at least 1, got {permit_count}")

    out = ProjectPricing(permit_count=len(buildings) if permit_count is None else permit_count)
    zone = buildings[0].quote.code_zone
    per_building_floor = floor_basis == "building"

    total_days = 0.0
    for b in buildings:
        q = _with_project_flags(b.quote, once_per_project, per_building_floor)
        r = estimate(config, q)
        profit = next((li["amount"] for li in r["line_items_detail"]
                       if li["key"] == "profit"), 0.0)
        # `profit_guidance` is only present on daily-overhead quotes, so it cannot be the only
        # source for either number. Days fall back to what the caller supplied (Tim's sheet has a
        # day column per building), and the would-be floor falls back to the flat job floor —
        # which IS what this roof would have paid standing alone under the default basis.
        guidance = r.get("profit_guidance") or {}
        days = b.days if b.days is not None else (guidance.get("total_series_days") or 0.0)
        total_days += float(days or 0.0)
        out.buildings.append({
            # BOTH sections. total_squares() counts sloped + flat, so reporting only the sloped
            # side here made one screen show the same building as "35 sq" (capture) and "20 sq"
            # (priced) with a 35 headline — the 75%-high implied $/sq this module documents,
            # rendered next to the correct figure.
            "name": b.name, "squares": q.num_squares + (q.flat_squares or 0),
            "address": b.address,
            "total": r["project_total"],
            "profit": profit, "days": float(days or 0.0),
            "would_be_floored_to": (
                None if per_building_floor
                else (guidance.get("effective_floor") or float(config.job_profit_floor() or 0.0))),
            "line_items_detail": r["line_items_detail"],
            "warnings": r["warnings"],
        })
        out.project_total += r["project_total"]
        out.profit += profit

    # Under the legacy 'building' basis every building already paid its own fees, so adding the
    # site's set on top would bill them TWICE. Caught by test_building_basis_restores_the_old
    # _behaviour — the suppression and the re-adding are one decision and must move together.
    if per_building_floor:
        # Nothing is suppressed on the legacy basis, so every building pulled its OWN permit inside
        # its own estimate: the count is the building count whatever the caller asked for, and
        # reporting their number would put a figure in the audit row that nothing charged.
        out.permit_count = len(buildings)
    else:
        out.project_fixed = _fixed_once(config, buildings, zone, once_per_project,
                                        out.permit_count)
        out.project_total += sum(f["amount"] for f in out.project_fixed)

    seen_keys: set[str] = set()
    for item in (project_items or []):
        if item.allocation != "project":
            raise ValueError(
                f"project_item {item.key!r}: allocation={item.allocation!r} is not implemented. "
                f"Only 'project' is honoured; a 'building:<name>' fold would be recorded and "
                f"then priced as its own line anyway, which is a silent no-op on money."
            )
        if item.key in seen_keys:
            raise ValueError(
                f"duplicate project_item key {item.key!r} — each block must be identifiable, "
                f"or a roll-up cannot say which line an amount came from."
            )
        seen_keys.add(item.key)
        d = {"key": item.key, "label": item.label, "cost": item.cost,
             "markup": item.markup, "amount": item.amount, "allocation": item.allocation}
        out.project_items.append(d)
        out.project_total += item.amount
        # Markup ON a project block is margin the same way a roof's markup is.
        out.profit += item.amount - item.cost

    out.floor = _apply_project_floor(config, out, total_days, floor_basis)
    out.project_total = round(out.project_total, 2)
    out.profit = round(out.profit, 2)
    return out.to_dict()


def total_squares(buildings: list[Building]) -> float:
    """Every square the bid PRICES — sloped plus low-slope.

    A roof with both sections is one job (core/estimator.py prices `flat_squares` against
    `flat_roof_type` in the same call), and 36% of Perkins roofs are mixed. Summing only
    `num_squares` reported a Clubhouse of 20 sloped + 15 flat as 20 squares against a total that
    priced 35 — measured on the live jupiter config, an implied $1,787.50/sq against a true
    $1,021.43/sq, 75% high. That figure reaches a customer through project_snapshot.
    """
    return sum(b.quote.num_squares + (b.quote.flat_squares or 0) for b in buildings)


def dominant_roof_type(buildings: list[Building]) -> str:
    """The roof type carrying the most squares in the bid, counting BOTH sections.

    A project snapshot still has to answer "what roof is this?" with ONE value, because
    core/proposal.py:_REQUIRED_SNAPSHOT_KEYS demands a scalar `roof_type` and every consumer —
    the contract renderer, the T&C picker, the deposit policy — reads it. Picking the largest by
    area rather than the first building means a nine-structure tile job does not describe itself
    as a metal job because the bus stop happened to be listed first. Ties break on the type name
    so the answer is stable across calls.

    Low-slope sections count under their OWN `flat_roof_type`: a bid that is mostly TPO by area
    should not call itself tile because the tile happens to sit on the sloped side.
    """
    by_type: dict[str, float] = {}
    for b in buildings:
        by_type[b.quote.roof_type] = by_type.get(b.quote.roof_type, 0.0) + b.quote.num_squares
        flat = b.quote.flat_squares or 0
        if flat and b.quote.flat_roof_type:
            by_type[b.quote.flat_roof_type] = by_type.get(b.quote.flat_roof_type, 0.0) + flat
    return max(sorted(by_type), key=lambda t: by_type[t])


def project_snapshot(roll_up: dict[str, Any], buildings: list[Building],
                     base: dict[str, Any]) -> dict[str, Any]:
    """A proposal quote_snapshot for a whole bid, built from a single-building `base` snapshot.

    ⚠️ NOT WIRED YET — as of slice 2 the only callers are tests. It takes a `base` because the
    scalar snapshot fields (tiers, deposit_policy, floors, estimator_version, sent_at_iso) are
    assembled by whoever creates the PROPOSAL, and /estimator/project-quote does not build a
    proposal. Slice 3 is where it gets called. Said plainly here so nobody reads its test coverage
    as evidence that project proposals work.

    Deliberately ADDITIVE: `roof_type` becomes the dominant building and `num_squares` the sum, so
    every key core/proposal.py already requires is still present and still a scalar of the right
    type. That is why _REQUIRED_SNAPSHOT_KEYS needs no change and why an existing single-building
    proposal keeps rendering unchanged — the project keys are extra, not a replacement.

    ⚠️ The three added keys are the whole record of the other eight buildings. Anything that
    rewrites a snapshot by re-quoting one estimate destroys them — see the guard owed on
    web/src/pages/Proposals.tsx.
    """
    return {
        **base,
        "roof_type": dominant_roof_type(buildings),
        "num_squares": round(total_squares(buildings), 2),
        "buildings": roll_up["buildings"],
        "project_items": roll_up["project_items"] + roll_up["project_fixed"],
        "project_totals": {
            "project_total": roll_up["project_total"],
            "profit": roll_up["profit"],
            "floor": roll_up["floor"],
            "building_count": len(roll_up["buildings"]),
            "warnings": roll_up["warnings"],
        },
    }


def _with_project_flags(q: QuoteInput, once: frozenset[str],
                        per_building_floor: bool) -> QuoteInput:
    """Copy a QuoteInput with the project flags set, leaving the caller's object untouched."""
    from dataclasses import replace  # noqa: PLC0415
    return replace(
        q,
        suppress_fixed_keys=frozenset() if per_building_floor else frozenset(once),
        profit_floor_scope="job" if per_building_floor else "project",
    )


def _apply_project_floor(config: PricingConfig, out: ProjectPricing,
                         total_days: float, basis: str) -> dict:
    """One floor for the site. Returns what it did and, always, what the alternative would be.

    Both numbers are reported because #449 specifies the weekly basis and the weekly basis does
    not reconcile with Tim's own bid. Burying that choice in a default would hide a 40% difference
    inside a number he is asked to sign.
    """
    weekly = float(config.weekly_profit_floor() or 0.0)
    job = float(config.job_profit_floor() or 0.0)
    per_week = float(config.profit_floor_days_per_week() or 5)
    weeks = max(1, math.ceil(total_days / per_week)) if total_days > 0 else 1
    week_floor = round(weeks * weekly, 2)

    # A week floor with no days is not a floor. `profit_guidance` is attached only to
    # daily-overhead quotes, so a bid of per_sq buildings with no explicit `days` contributes
    # zero and `weeks` collapses to 1 — nine structures on an 18-week site were quoting ONE
    # week's $2,500 with no warning. Refuse rather than price it: the caller either supplies
    # Building.days (Tim's sheet has a day column per building) or uses overhead_mode="daily".
    if basis == "week" and total_days <= 0:
        raise ValueError(
            "floor_basis='week' needs on-site days, and none of the buildings supplied any. "
            "Set Building.days per structure, or quote them with overhead_mode='daily' so the "
            "day model derives them. Pricing a 1-week floor for a multi-week site silently "
            "under-charges by the number of weeks."
        )

    info = {"basis": basis, "on_site_days": round(total_days, 2), "on_site_weeks": weeks,
            "project_floor": job, "weekly_basis_would_be": week_floor,
            "profit_before_floor": round(out.profit, 2), "applied": 0.0}

    if basis == "building":
        info["note"] = "legacy: every building paid its own floor"
        return info
    if not config.enforce_profit_floor():
        info["note"] = "floor not enforced by this config"
        return info

    target = week_floor if basis == "week" else job
    info["target"] = target
    if out.profit < target:
        shortfall = round(target - out.profit, 2)
        # ONE project line, not redistributed. Spreading it would reprice every building's per-sq
        # and re-open every margin badge, and Tim's own site money sits on one row.
        out.project_items.append({
            "key": "project_profit_floor", "label": "Project minimum profit",
            "cost": shortfall, "markup": 1.0, "amount": shortfall, "allocation": "project"})
        out.project_total += shortfall
        out.profit += shortfall
        info["applied"] = shortfall
        out.warnings.append(
            f"project_profit_floor_applied: bid profit ${info['profit_before_floor']:,.0f} raised "
            f"to ${target:,.0f} by one site-level floor ({basis} basis). Per building it would "
            f"have been {len(out.buildings)} separate floors."
        )
    if basis == "project" and total_days <= 0:
        out.warnings.append(
            "project_floor_basis_undisclosed: no on-site days were supplied, so the #449 weekly "
            "basis cannot be costed for comparison. The 'weekly_basis_would_be' figure below is "
            "one week's floor, NOT this site's — supply Building.days or quote daily to see the "
            "real divergence."
        )
    if basis == "project" and total_days > 0 and week_floor > target:
        out.warnings.append(
            f"project_floor_basis_divergence: #449 specifies a per-site-per-WEEK floor, which "
            f"here is {weeks} x ${weekly:,.0f} = ${week_floor:,.0f}. Tim's own Evergrene margin "
            f"was $30,363, so the weekly basis prices ~40% above what he bid. Using the "
            f"'project' basis instead — pending his answer."
        )
    return info
