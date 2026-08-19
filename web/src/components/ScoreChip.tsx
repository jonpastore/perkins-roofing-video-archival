import { BRAND } from "../ui";

export const SCORE_HELP = {
  opportunity:
    "Opportunity ranks an uncovered topic using uniqueness, demand, grounding, named-entity value, and genre diversity; existing pages score zero.",
  heat:
    "Heat measures demonstrated audience response, weighting comments more than likes and likes more than views.",
  coverage:
    "Coverage is the share of qualified topics in this subject or genre that already have a page; high coverage means look elsewhere unless engagement supports repackaging.",
} as const;

export type ScoreKind = keyof typeof SCORE_HELP;
export type ScoreBand = "low" | "medium" | "high";

export function engagementScore(views: number, likes: number, comments: number): number {
  const log1p = (n: number) => Math.log(1 + Math.max(0, n));
  return 2 * log1p(comments) + log1p(likes) + 0.25 * log1p(views);
}

export function scoreBand(value: number, peers: number[]): ScoreBand {
  if (value <= 0) return "low";
  if (peers.length < 3) {
    if (value >= 5) return "high";
    if (value >= 1) return "medium";
    return "low";
  }
  const ordered = [...peers].sort((a, b) => a - b);
  const p33 = ordered[Math.floor((ordered.length * 33) / 100)];
  const p66 = ordered[Math.floor((ordered.length * 66) / 100)];
  if (value <= p33) return "low";
  if (value <= p66) return "medium";
  return "high";
}

export function HelpTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      aria-label={text}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 16,
        height: 16,
        borderRadius: "50%",
        flexShrink: 0,
        border: `1px solid ${BRAND.navyText}`,
        color: BRAND.navyText,
        fontSize: 11,
        fontWeight: 700,
        cursor: "help",
        lineHeight: 1,
      }}
    >
      ?
    </span>
  );
}

const BAND_COLOR: Record<ScoreBand, string> = {
  high: "#1f7a4d",
  medium: "#b45309",
  low: "#6b7280",
};

const COVERAGE_COLOR: Record<ScoreBand, string> = {
  high: "#b45309",
  medium: BRAND.navyText,
  low: "#1f7a4d",
};

export function ScoreChip({
  kind,
  value,
  peers = [],
}: {
  kind: ScoreKind;
  value: number;
  peers?: number[];
}) {
  const band = scoreBand(value, peers);
  const color = kind === "coverage" ? COVERAGE_COLOR[band] : BAND_COLOR[band];
  const label = kind === "opportunity" ? "Opportunity" : kind === "heat" ? "Heat" : "Coverage";
  let display: string;
  if (kind === "coverage") {
    if (value >= 0.999) display = "Covered";
    else if (value <= 0) display = "Uncovered";
    else display = `${Math.round(value * 100)}%`;
  } else {
    display = value.toFixed(1);
  }
  const bandText = kind === "coverage" && (value >= 0.999 || value <= 0)
    ? ""
    : ` — ${band.charAt(0).toUpperCase()}${band.slice(1)}`;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        whiteSpace: "nowrap",
        fontSize: 12,
        fontWeight: 700,
        color,
      }}
    >
      {label} {display}{bandText}
      <HelpTip text={SCORE_HELP[kind]} />
    </span>
  );
}
