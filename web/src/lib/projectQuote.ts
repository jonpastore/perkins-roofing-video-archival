/**
 * Multi-building bid logic (#430/#449 slice 4) — pure, no React, no api client.
 *
 * ⚠️ THIS LIVES HERE RATHER THAN IN Quoting.tsx FOR A MEASURED REASON. The tests originally
 * imported these from the page module, which transitively imports src/api.ts -> src/auth.ts,
 * and auth.ts calls getAuth() at MODULE SCOPE. That needs VITE_FIREBASE_API_KEY, which a dev
 * machine has in web/.env and CI does not — so the suite passed locally and failed in CI with
 * `FirebaseError: auth/invalid-api-key`, a failure about configuration rather than about this
 * logic. Keeping the pure rules in a leaf module means they can be tested without booting the
 * app's auth singleton.
 */

export interface ProjectItemDraft {
  key: string;
  label: string;
  cost: number;
  markup: number;
}


export interface ProjectBuildingDraft {
  name: string;
  days?: number;
  quote: Record<string, unknown>;
  squares: number;
  /** The property this roof was captured against — a bid must be ONE site. */
  propertyId?: number | null;
  /** Captured so a zone mismatch is caught here, where the user can still see the culprit. */
  codeZone?: string;
}


/** The POST body for /estimator/project-quote. Module-level and exported so it can be tested
 *  without mounting a 3,000-line page — the one place "the form is the per-building editor"
 *  charges rent, paid here. */
export function buildProjectQuoteBody(args: {
  name: string;
  buildings: ProjectBuildingDraft[];
  persist: boolean;
  propertyId?: number | null;
  projectItems?: ProjectItemDraft[];
  addOnBlocks?: ProjectItemDraft[];
  permitCount?: number;
}): Record<string, unknown> {
  return {
    name: args.name.trim() || "Untitled project",
    property_id: args.propertyId ?? undefined,
    buildings: args.buildings.map((b) => ({ name: b.name, days: b.days, quote: b.quote })),
    project_items: (args.projectItems ?? []).map((i) => ({
      key: i.key, label: i.label, cost: i.cost, markup: i.markup,
    })),
    // A SEPARATE list on purpose: Tim's proposal presents General Conditions and his add-on
    // blocks ($42,050 sloped + $31,000 tile) as different quoted blocks, and bid_projects
    // .add_on_blocks exists for exactly that. Folding them together prices identically but
    // persists the misfiling slice 2 fixed.
    add_on_blocks: (args.addOnBlocks ?? []).map((i) => ({
      key: i.key, label: i.label, cost: i.cost, markup: i.markup,
    })),
    permit_count: args.permitCount && args.permitCount > 0 ? args.permitCount : 1,
    persist: args.persist,
  };
}


/** Identity of a bid, for "is this exact bid already saved?".
 *
 *  Includes each building's FULL quote: remove-and-re-add is the only way to edit a captured
 *  roof, so a signature over name+squares alone reported "already saved" about a bid whose price
 *  had changed — and disabled the only button that could save the correction. permitCount is
 *  normalised because "1", "01" and "1.0" all send 1 but hash differently, which let an identical
 *  bid save twice. */
export function projectBidSignature(args: {
  name: string;
  buildings: ProjectBuildingDraft[];
  items: ProjectItemDraft[];
  permitCount: string;
}): string {
  return JSON.stringify({
    n: args.name.trim(),
    b: args.buildings.map((x) => [x.name, x.squares, x.days ?? null, JSON.stringify(x.quote)]),
    i: args.items.map((x) => [x.key, x.cost, x.markup]),
    p: Number(args.permitCount) || 1,
  });
}


/** Why a roof may not join this bid. null = it may.
 *
 *  A bid is ONE site: every structure must share a property, or the "charged once for the site"
 *  arithmetic is describing two sites. Nothing on the server can catch this — it only compares
 *  branch, zone and config — so it is enforced where the capture happens. */
export function rejectBuildingCapture(args: {
  name: string;
  existing: ProjectBuildingDraft[];
  propertyId?: number | null;
  discountCount: number;
  days: string;
  codeZone?: string;
}): string | null {
  const name = args.name.trim();
  if (!name) {
    return "Name the structure (e.g. \"Clubhouse\") — a bid of anonymous roofs cannot be read, "
      + "and duplicates are refused.";
  }
  if (args.existing.some((b) => b.name.toLowerCase() === name.toLowerCase())) {
    return `"${name}" is already in this bid.`;
  }
  if (args.discountCount > 0) {
    return `Remove the ${args.discountCount} discount row(s) first — a project quote refuses `
      + "per-building discounts, because a discount that never comes off the price would still "
      + "be recorded on the estimate.";
  }
  if (args.days.trim() !== "" && !Number.isFinite(Number(args.days))) {
    return `On-site days must be a number (got "${args.days}").`;
  }
  if (args.days.trim() !== "" && Number(args.days) < 0) {
    return "On-site days cannot be negative.";
  }
  const first = args.existing[0];
  if (first && first.propertyId != null && args.propertyId != null
      && first.propertyId !== args.propertyId) {
    return "Every structure in a bid must be at the SAME property — that is what makes delivery, "
      + "permit and the dumpster site costs rather than per-roof ones.";
  }
  // The server refuses a mixed code_zone too, but by then it can only name the ZONES, not which
  // of nine captured structures is the odd one — and the list shows no zone, so the only recovery
  // was removing everything. Catch it where the user can still see what they changed.
  if (first && args.codeZone && first.codeZone && first.codeZone !== args.codeZone) {
    return `This roof is ${args.codeZone} but the bid is ${first.codeZone}. One bid is one site, `
      + "so every structure shares a code zone — change the region back, or start a separate bid.";
  }
  return null;
}
