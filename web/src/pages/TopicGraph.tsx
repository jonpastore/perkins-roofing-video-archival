import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Badge, Button, Card, ErrorMsg, Loading } from "../ui";
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
}: {
  kind: GraphKind;
  onClose: () => void;
}) {
  const [published, setPublished] = useState<PubFilter>("all");
  const [data, setData] = useState<GraphPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
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
        setOpenId(null);
        setOpenSubject(null);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [kind, published]);

  const selected = useMemo(
    () => data?.genres.find((g) => g.id === openId) ?? null,
    [data, openId],
  );
  const selectedSubject = useMemo(
    () => selected?.subjects.find((s) => s.slug === openSubject) ?? null,
    [selected, openSubject],
  );

  const noun = kind === "faqs" ? "FAQs" : "articles";

  return (
    <div
      role="dialog"
      aria-label="Topic graph"
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)",
        zIndex: 40, display: "flex", justifyContent: "center", alignItems: "flex-start",
        padding: "32px 16px", overflow: "auto",
      }}
      onClick={onClose}
    >
      <Card
        style={{
          width: "min(1100px, 100%)", maxHeight: "calc(100vh - 48px)",
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
              Top row is genre. Click a cell to see subjects, then {noun}.
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
            <DiversityBanner data={data} noun={noun} />
            <Icicle
              genres={data.genres}
              selectedId={openId}
              onSelect={(id) => { setOpenId(id); setOpenSubject(null); }}
              published={published}
            />
            <Legend legend={data.legend} />

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

            <GenreTable
              genres={data.genres}
              openId={openId}
              onOpen={(id) => { setOpenId(id); setOpenSubject(null); }}
            />
          </>
        )}
      </Card>
    </div>
  );
}

function DiversityBanner({ data, noun }: { data: GraphPayload; noun: string }) {
  const even = data.diversity.shannon;
  const conc = data.diversity.concentrated;
  return (
    <div
      style={{
        display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 12,
        padding: "10px 12px", background: BRAND.bg, borderRadius: 8, fontSize: 13,
      }}
    >
      <span><strong>{data.totals.published}</strong> published {noun}</span>
      <span>Evenness {even.toFixed(2)} {even < 0.7 ? "(uneven)" : "(ok)"}</span>
      <span>Concentration {data.diversity.herfindahl.toFixed(2)} {conc ? "— density issue" : ""}</span>
      {data.diversity.flags.slice(0, 4).map((f) => (
        <Badge key={f.genre} tone={densityTone(f.flag)}>
          {f.genre}: {f.flag.replace("_", " ")}
        </Badge>
      ))}
    </div>
  );
}

function Icicle({
  genres, selectedId, onSelect, published,
}: {
  genres: Genre[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  published: PubFilter;
}) {
  const weight = (g: Genre) => {
    if (published === "yes") return Math.max(g.n_published, 0.15);
    if (published === "no") return Math.max(g.opportunity, 0.15);
    return Math.max(g.n_published + g.opportunity, 0.2);
  };
  const total = genres.reduce((s, g) => s + weight(g), 0) || 1;
  return (
    <div style={{ display: "flex", height: 72, borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}` }}>
      {genres.map((g) => {
        const pct = (weight(g) / total) * 100;
        if (pct < 1.2 && g.id !== selectedId) return null;
        const active = selectedId === g.id;
        return (
          <button
            key={g.id}
            type="button"
            title={`${g.label} · ${g.n_published} published · ${g.n_unpublished} open`}
            onClick={() => onSelect(g.id)}
            style={{
              flex: `${weight(g)} 1 0`,
              minWidth: 28,
              border: "none",
              borderRight: `1px solid rgba(255,255,255,0.25)`,
              background: FILL[g.color],
              color: "#fff",
              cursor: "pointer",
              padding: "6px 4px",
              fontSize: 11,
              fontWeight: active ? 700 : 500,
              outline: active ? "2px solid #fff" : "none",
              outlineOffset: -2,
              overflow: "hidden",
              textAlign: "left",
            }}
          >
            <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {g.label}
            </div>
            <div style={{ opacity: 0.85, fontSize: 10 }}>
              {g.n_published}p / {g.n_unpublished}o
            </div>
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
  if (genre.subjects.length === 0) {
    return <p style={{ fontSize: 13, color: BRAND.sub }}>No subjects in this filter.</p>;
  }
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
        {genre.label} — {genre.subjects.length} subjects
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {genre.subjects.slice(0, 40).map((s) => (
          <button
            key={s.slug}
            type="button"
            onClick={() => onSelect(s.slug)}
            style={{
              fontSize: 12, padding: "4px 8px", borderRadius: 4, cursor: "pointer",
              border: `1px solid ${selectedSlug === s.slug ? BRAND.navyText : BRAND.border}`,
              background: s.covered ? "#eef2ff" : "#fff",
              color: BRAND.navyText, maxWidth: 260,
              textAlign: "left",
            }}
          >
            {s.label}
            <span style={{ color: BRAND.sub, marginLeft: 6 }}>
              {s.covered ? "covered" : `opp ${s.opportunity.toFixed(2)}`}
            </span>
          </button>
        ))}
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

function GenreTable({
  genres, openId, onOpen,
}: {
  genres: Genre[];
  openId: string | null;
  onOpen: (id: string) => void;
}) {
  return (
    <div style={{ marginTop: 18, overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: `2px solid ${BRAND.border}` }}>
            {["Genre", "Published", "Open", "Coverage", "YT views", "Comments", "Grounded", "Opportunity", "Density", ""].map((h) => (
              <th key={h} style={{ padding: "6px 8px", color: BRAND.sub, fontWeight: 600, fontSize: 11 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {genres.map((g) => (
            <tr
              key={g.id}
              style={{
                borderBottom: `1px solid ${BRAND.border}`,
                background: openId === g.id ? "#f3f6fb" : undefined,
              }}
            >
              <td style={{ padding: "8px", fontWeight: 600, color: FILL[g.color] }}>{g.label}</td>
              <td style={{ padding: "8px" }}>{g.n_published}</td>
              <td style={{ padding: "8px" }}>{g.n_unpublished}</td>
              <td style={{ padding: "8px" }}>{Math.round(g.coverage * 100)}%</td>
              <td style={{ padding: "8px" }}>{fmt(g.yt_views)}</td>
              <td style={{ padding: "8px" }}>{fmt(g.yt_comments)}</td>
              <td style={{ padding: "8px" }}>{Math.round(g.grounding_seconds / 60)}m</td>
              <td style={{ padding: "8px" }}>{g.opportunity.toFixed(2)}</td>
              <td style={{ padding: "8px" }}>
                <Badge tone={densityTone(g.density)}>{g.density.replace("_", " ")}</Badge>
              </td>
              <td style={{ padding: "8px" }}>
                <Button variant="ghost" onClick={() => onOpen(g.id)} style={{ padding: "4px 10px", fontSize: 12 }}>
                  Open
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Legend({ legend }: { legend: Record<string, string> }) {
  return (
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "8px 0 4px", fontSize: 11, color: BRAND.sub }}>
      {Object.entries(legend).map(([k, v]) => (
        <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: FILL[k as Genre["color"]] }} />
          {v}
        </span>
      ))}
    </div>
  );
}
