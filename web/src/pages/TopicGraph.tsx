import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";
import { BRAND, Badge, Button, Card, ErrorMsg, Loading } from "../ui";
import { engagementScore, HelpTip, ScoreChip } from "../components/ScoreChip";
import { errText } from "../lib/errors";

export type GraphKind = "articles" | "faqs";
type PubFilter = "all" | "yes" | "no";

interface Leaf {
  slug: string | null;
  title: string | null;
  status: string | null;
  role: string | null;
}

interface Subject {
  label: string;
  slug: string;
  n_variants: number;
  n_videos: number;
  yt_views: number;
  yt_likes: number;
  yt_comments: number;
  grounding_seconds: number;
  covered: boolean;
  opportunity: number;
  aio: number;
  articles: Leaf[];
}

interface Genre {
  id: string;
  label: string;
  publishable: boolean;
  n_subjects: number;
  n_variants: number;
  n_published: number;
  n_unpublished: number;
  covered_subjects: number;
  yt_views: number;
  yt_likes: number;
  yt_comments: number;
  grounding_seconds: number;
  opportunity: number;
  coverage: number;
  density: string;
  color: "navy" | "green" | "amber" | "red";
  subjects: Subject[];
}

interface GraphPayload {
  kind: GraphKind;
  published_filter: PubFilter;
  genres: Genre[];
  diversity: {
    herfindahl: number;
    shannon: number;
    concentrated: boolean;
    flags: { genre: string; flag: string }[];
  };
  totals: { items: number; published: number; genres: number };
  legend: Record<string, string>;
}

const FILL: Record<Genre["color"], string> = {
  navy: BRAND.navy,
  green: "#1f7a4d",
  amber: "#b45309",
  red: BRAND.red,
};

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n));
}

function densityTone(d: string): "red" | "amber" | "green" | "gray" {
  if (d === "over_served") return "red";
  if (d === "under_served" || d === "empty") return "amber";
  if (d === "internal") return "gray";
  return "green";
}

export function TopicGraphPanel({
  kind,
  onClose,
  initialGenreId = null,
}: {
  kind: GraphKind;
  onClose: () => void;
  initialGenreId?: string | null;
}) {
  const [published, setPublished] = useState<PubFilter>("all");
  const [data, setData] = useState<GraphPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(initialGenreId);
  const [openSubject, setOpenSubject] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    apiFetch(`/topic-graph?kind=${kind}&published=${published}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await errText(r));
        return r.json();
      })
      .then((body: GraphPayload) => {
        setData(body);
        const keep = initialGenreId && body.genres.some((g) => g.id === initialGenreId)
          ? initialGenreId
          : null;
        setOpenId(keep);
        setOpenSubject(null);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [kind, published, initialGenreId]);

  const selected = useMemo(
    () => data?.genres.find((g) => g.id === openId) ?? null,
    [data, openId],
  );
  const selectedSubject = useMemo(
    () => selected?.subjects.find((s) => s.slug === openSubject) ?? null,
    [selected, openSubject],
  );

  const noun = kind === "faqs" ? "FAQs" : "articles";

  return createPortal(
    <div
      role="dialog"
      aria-label="Topic graph"
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)",
        zIndex: 80, display: "flex", justifyContent: "center", alignItems: "flex-start",
        padding: "24px 16px", overflow: "auto",
      }}
      onClick={onClose}
    >
      <Card
        style={{
          width: "min(880px, calc(100vw - 32px))", maxHeight: "calc(100vh - 48px)",
          overflow: "auto", padding: 20,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0, color: BRAND.navyText, fontSize: 18 }}>
              {kind === "faqs" ? "FAQ graph" : "Topic graph"}
            </h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: BRAND.sub }}>
              Pick a genre, then a subject, then {noun}.
            </p>
          </div>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: BRAND.sub }}>Show:</span>
          {([["all", "All"], ["yes", "Published"], ["no", "Not published"]] as const).map(([v, lab]) => (
            <button
              key={v}
              type="button"
              onClick={() => setPublished(v)}
              style={{
                fontSize: 12, padding: "4px 10px", borderRadius: 6, cursor: "pointer",
                border: `1px solid ${published === v ? BRAND.navyText : BRAND.border}`,
                background: published === v ? BRAND.navyText : "#fff",
                color: published === v ? "#fff" : BRAND.sub,
                fontWeight: published === v ? 600 : 400,
              }}
            >
              {lab}
            </button>
          ))}
        </div>

        {loading && <Loading label="Scoring topics…" />}
        {err && <ErrorMsg>{err}</ErrorMsg>}

        {data && !loading && (
          <>
            <DiversityBanner data={data} noun={noun} legend={data.legend} />
            <GenreBar
              genres={data.genres}
              selectedId={openId}
              onSelect={(id) => { setOpenId(id); setOpenSubject(null); }}
            />

            {selected && (
              <SubjectStrip
                genre={selected}
                selectedSlug={openSubject}
                onSelect={setOpenSubject}
              />
            )}
            {selectedSubject && (
              <LeafList subject={selectedSubject} noun={noun} />
            )}
          </>
        )}
      </Card>
    </div>,
    document.body,
  );
}

function DiversityBanner({
  data, noun, legend,
}: {
  data: GraphPayload;
  noun: string;
  legend: Record<string, string>;
}) {
  const even = data.diversity.shannon;
  const flags = data.diversity.flags.slice(0, 3);
  const help = [
    `Evenness ${even.toFixed(2)} (near 1 = pages spread across genres).`,
    `Concentration ${data.diversity.herfindahl.toFixed(2)} (near 1 = one genre owns the inventory).`,
    ...Object.values(legend),
  ].join(" ");
  return (
    <div
      style={{
        display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12, alignItems: "center",
        padding: "8px 12px", background: BRAND.bg, borderRadius: 8, fontSize: 13,
      }}
    >
      <span><strong>{data.totals.published}</strong> published {noun}</span>
      <span style={{ color: BRAND.sub }}>{even < 0.7 ? "spread is uneven" : "spread is even"}</span>
      {flags.map((f) => (
        <Badge key={f.genre} tone={densityTone(f.flag)}>
          {f.genre}: {f.flag.replace("_", " ")}
        </Badge>
      ))}
      <HelpTip text={help} />
    </div>
  );
}

function GenreBar({
  genres, selectedId, onSelect,
}: {
  genres: Genre[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 4 }}>
      {genres.map((g) => {
        const active = selectedId === g.id;
        return (
          <button
            key={g.id}
            type="button"
            title={`${g.label}: ${g.n_published} published, ${g.n_unpublished} open`}
            onClick={() => onSelect(g.id)}
            style={{
              display: "flex", alignItems: "stretch",
              minWidth: 148, maxWidth: "100%",
              padding: 0, cursor: "pointer", textAlign: "left",
              borderRadius: 8, overflow: "hidden",
              border: `1.5px solid ${active ? FILL[g.color] : BRAND.border}`,
              background: active ? "#f3f6fb" : "#fff",
            }}
          >
            <span style={{ width: 6, background: FILL[g.color], flexShrink: 0 }} />
            <span style={{ padding: "8px 10px", minWidth: 0 }}>
              <span style={{
                display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {g.label}
              </span>
              <span style={{ fontSize: 11, color: BRAND.sub }}>
                {g.n_published} published · {g.n_unpublished} open
                {g.density !== "balanced" ? ` · ${g.density.replace("_", " ")}` : ""}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function SubjectStrip({
  genre, selectedSlug, onSelect,
}: {
  genre: Genre;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
}) {
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return [...genre.subjects]
      .filter((s) => !needle || s.label.toLowerCase().includes(needle))
      .sort((a, b) => {
        if (a.covered !== b.covered) return a.covered ? 1 : -1;
        if (b.opportunity !== a.opportunity) return b.opportunity - a.opportunity;
        return b.yt_views - a.yt_views;
      });
  }, [genre.subjects, q]);

  if (genre.subjects.length === 0) {
    return <p style={{ fontSize: 13, color: BRAND.sub }}>No subjects in this filter.</p>;
  }
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap",
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: BRAND.navyText }}>
          {genre.label}
          <span style={{ fontWeight: 400, color: BRAND.sub, marginLeft: 8 }}>
            {rows.length} of {genre.subjects.length}
            {genre.yt_views ? ` · ${fmt(genre.yt_views)} views` : ""}
          </span>
          <ScoreChip kind="coverage" value={genre.coverage ?? 0} />
        </div>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search subjects"
          aria-label="Search subjects"
          style={{
            flex: "1 1 180px", maxWidth: 280, fontSize: 13, padding: "6px 10px",
            border: `1px solid ${BRAND.border}`, borderRadius: 6,
          }}
        />
      </div>
      <div style={{
        maxHeight: 320, overflowY: "auto", border: `1px solid ${BRAND.border}`,
        borderRadius: 8,
      }}>
        {rows.map((s) => {
          const active = selectedSlug === s.slug;
          return (
            <button
              key={s.slug}
              type="button"
              onClick={() => onSelect(s.slug)}
              style={{
                display: "flex", width: "100%", gap: 12, alignItems: "flex-start",
                padding: "10px 12px", cursor: "pointer", textAlign: "left",
                border: "none", borderBottom: `1px solid ${BRAND.border}`,
                background: active ? "#eef2ff" : "#fff",
              }}
            >
              <span style={{ flex: 1, fontSize: 13, color: BRAND.navyText, lineHeight: 1.35 }}>
                {s.label}
              </span>
              <span style={{
                flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end",
                gap: 4, fontSize: 11, color: BRAND.sub, textAlign: "right",
              }}>
                {s.covered
                  ? <ScoreChip kind="coverage" value={1} />
                  : <ScoreChip kind="opportunity" value={s.opportunity} peers={rows.map((r) => r.opportunity)} />}
                {s.n_videos ? `${fmt(s.yt_views)} views` : ""}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function LeafList({ subject, noun }: { subject: Subject; noun: string }) {
  return (
    <div style={{ marginTop: 10, fontSize: 13 }}>
      <div style={{ fontWeight: 600, color: BRAND.navyText, marginBottom: 4 }}>
        {subject.label}
      </div>
      <div style={{ color: BRAND.sub, fontSize: 12, marginBottom: 6 }}>
        {subject.n_variants} variants · {fmt(subject.yt_views)} views · {subject.yt_comments} comments
        · {Math.round(subject.grounding_seconds / 60)} min transcript
        {subject.aio ? " · AIO entity" : ""}
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        {subject.covered
          ? <ScoreChip kind="coverage" value={1} />
          : <ScoreChip kind="opportunity" value={subject.opportunity} />}
        <ScoreChip
          kind="heat"
          value={engagementScore(subject.yt_views, subject.yt_likes, subject.yt_comments)}
        />
      </div>
      {subject.articles.length === 0 ? (
        <span style={{ color: BRAND.sub }}>No published {noun} on this subject.</span>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {subject.articles.map((a) => (
            <li key={a.slug || a.title || ""}>
              {a.title || a.slug}{" "}
              <span style={{ color: BRAND.sub }}>{a.role} · {a.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}




