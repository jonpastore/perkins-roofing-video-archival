/** Split a pasted one-line address into the fields the property form holds.
 *
 * Estimators paste "1234 SW 5th St, Miami, FL 33169" out of an email or Google Maps and then
 * retype it into five boxes. This does the split so they don't.
 *
 * Deliberately NOT a general address parser — it handles the shapes that actually arrive
 * (comma-separated, optional unit, ZIP or ZIP+4, occasional trailing "USA") and returns what it
 * is sure about, leaving the rest blank rather than guessing. A wrong city silently written into
 * a field is worse than an empty one the estimator fills in.
 */
export interface ParsedAddress {
  street: string;
  city: string;
  state: string;
  zip: string;
}

// A trailing "<state> <zip>", where <state> may be the two-letter code OR a spelled-out name.
// Spelled out matters: "…, Jupiter, Florida 33477" used to fall through every branch and land
// whole in the CITY field, which then fed the geocoder — the exact "wrong city is worse than an
// empty one" failure this file is written to avoid.
const STATE_ZIP = /^([A-Za-z][A-Za-z .]*?)\.?\s+(\d{5})(?:-(\d{4}))?$/;
const ZIP_ONLY = /^(\d{5})(?:-(\d{4}))?$/;
const STATE_ONLY = /^([A-Za-z]{2})\.?$/;
// Perkins works one state. Anything else spelled out is still recognised as "not a city" — the
// ZIP is taken and `state` left blank rather than guessing at an abbreviation.
const STATE_NAMES: Record<string, string> = { florida: "FL" };
// "…, FL 33477, Palm Beach County" — a county is not a city and must not become one.
const COUNTY = /\bcounty$/i;

/** Two-letter code as-is; a known spelled-out name mapped; anything else -> "" (never a guess). */
function normaliseState(raw: string): string {
  const s = raw.trim().replace(/\.$/, "");
  if (/^[A-Za-z]{2}$/.test(s)) return s.toUpperCase();
  return STATE_NAMES[s.toLowerCase()] ?? "";
}

/** True when the text looks like a whole address rather than just a street line. */
export function looksComplete(text: string): boolean {
  const p = parseAddress(text);
  return Boolean(p.street && (p.city || p.zip));
}

export function parseAddress(raw: string): ParsedAddress {
  const empty: ParsedAddress = { street: "", city: "", state: "", zip: "" };
  // Newlines are a paste from a letter or a signature block; treat them as field separators too.
  const text = (raw || "").replace(/\s+/g, " ").trim();
  if (!text) return empty;

  let parts = text.split(",").map((p) => p.trim()).filter(Boolean);
  // A trailing country is noise for a Florida roofer, and so is a county.
  if (parts.length && /^(usa|us|united states)$/i.test(parts[parts.length - 1])) parts.pop();
  if (parts.length > 1 && COUNTY.test(parts[parts.length - 1])) parts.pop();
  if (!parts.length) return empty;

  // No commas at all: the whole thing is a street line. Pull a trailing "FL 33169" if present,
  // since "123 Main St Miami FL 33169" is a common paste and the tail is unambiguous even when
  // the city/street boundary is not — so the city is left blank rather than guessed at.
  if (parts.length === 1) {
    const m = /^(.*?)\s+([A-Za-z]{2})\.?\s+(\d{5})(?:-\d{4})?$/.exec(parts[0]);
    if (m) return { street: m[1].trim(), city: "", state: m[2].toUpperCase(), zip: m[3] };
    return { ...empty, street: parts[0] };
  }

  const out: ParsedAddress = { ...empty };
  const last = parts[parts.length - 1];

  const stateZip = STATE_ZIP.exec(last);
  if (stateZip) {
    out.state = normaliseState(stateZip[1]);
    out.zip = stateZip[2];
    parts.pop();
  } else if (ZIP_ONLY.test(last)) {
    out.zip = ZIP_ONLY.exec(last)![1];
    parts.pop();
    // "..., Miami, FL, 33169" — state was its own field before the ZIP.
    const maybeState = parts[parts.length - 1];
    if (maybeState && STATE_ONLY.test(maybeState)) {
      out.state = normaliseState(maybeState);
      parts.pop();
    }
  } else if (STATE_ONLY.test(last) || STATE_NAMES[last.toLowerCase()]) {
    out.state = normaliseState(last);
    parts.pop();
  }

  if (parts.length) {
    out.city = parts.pop()!;
    // Whatever is left is street + unit; rejoin so "Apt 4" stays attached to the street line.
    out.street = parts.join(", ");
  }
  // Only a city survived with nothing before it — that is a street line, not a city.
  if (!out.street && out.city) {
    out.street = out.city;
    out.city = "";
  }
  return out;
}

// NO code-zone derivation here, deliberately. HVHZ (Miami-Dade + Broward) moves the price, and
// Florida ZIPs do not line up with county boundaries in contiguous ranges — Deerfield Beach is
// Broward at 33441-33443, sitting inside a range otherwise full of Palm Beach. A ZIP-prefix guess
// would silently reprice those jobs, so the code-zone selector stays a human decision.
