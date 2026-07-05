import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

interface MinedItem {
  question: string;
  video_id: string;
  t: number;
  url: string;
}

interface FaqEntry {
  question: string;
  answer: string;
  citations: string[];
}

function mmss(t: number): string {
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function Faq() {
  const [filter, setFilter] = useState("");
  const [mined, setMined] = useState<MinedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [results, setResults] = useState<FaqEntry[] | null>(null);
  const filterTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function load(q?: string) {
    setLoading(true);
    setError(null);
    const qs = q ? `?q=${encodeURIComponent(q)}&limit=100` : "?limit=100";
    apiFetch(`/faq/mined${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: MinedItem[]) => {
        setMined(data);
        setSelected(new Set());
        setResults(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  function handleFilterChange(val: string) {
    setFilter(val);
    if (filterTimer.current) clearTimeout(filterTimer.current);
    filterTimer.current = setTimeout(() => load(val || undefined), 350);
  }

  function toggleSelect(idx: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === mined.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(mined.map((_, i) => i)));
    }
  }

  async function handleBuild() {
    if (selected.size === 0) return;
    setBuildError(null);
    setBuilding(true);
    setResults(null);
    try {
      const questions = [...selected].map((i) => mined[i].question);
      const r = await apiFetch("/faq/build", {
        method: "POST",
        body: JSON.stringify({ questions }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data = await r.json();
      setResults(data.faq as FaqEntry[]);
    } catch (e: unknown) {
      setBuildError(e instanceof Error ? e.message : String(e));
    } finally {
      setBuilding(false);
    }
  }

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle>FAQ Builder</PageTitle>

      {/* Filter + Build controls */}
      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value)}
            placeholder="Filter by topic…"
            style={{ ...inputStyle, flex: 1, minWidth: 180 }}
          />
          <span style={{ fontSize: 13, color: BRAND.sub, whiteSpace: "nowrap" }}>
            {mined.length} question{mined.length !== 1 ? "s" : ""}
            {selected.size > 0 && `, ${selected.size} selected`}
          </span>
          <Button
            variant="ghost"
            style={{ padding: "8px 14px", fontSize: 13 }}
            onClick={toggleAll}
            disabled={mined.length === 0}
          >
            {selected.size === mined.length && mined.length > 0 ? "Deselect all" : "Select all"}
          </Button>
          <Button
            onClick={handleBuild}
            disabled={selected.size === 0 || building}
            style={{ whiteSpace: "nowrap" }}
          >
            {building ? "Building…" : "Build grounded answers"}
          </Button>
        </div>
        {buildError && <p style={{ color: BRAND.red, fontSize: 14, marginTop: 10 }}>{buildError}</p>}
      </Card>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {/* Mined questions list */}
      {!loading && !error && mined.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            No mined questions found{filter ? ` for "${filter}"` : ""}.
          </p>
        </Card>
      )}

      {!loading && !error && mined.length > 0 && (
        <Card style={{ marginBottom: 24, padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: `2px solid ${BRAND.border}`, background: BRAND.bg }}>
                <th style={{ padding: "10px 14px", width: 36 }} />
                <th style={{ padding: "10px 14px", textAlign: "left", color: BRAND.sub, fontWeight: 600 }}>
                  Question
                </th>
                <th style={{ padding: "10px 14px", textAlign: "left", color: BRAND.sub, fontWeight: 600, whiteSpace: "nowrap" }}>
                  Source
                </th>
              </tr>
            </thead>
            <tbody>
              {mined.map((item, idx) => (
                <tr
                  key={`${item.video_id}-${item.t}-${idx}`}
                  style={{
                    borderBottom: `1px solid ${BRAND.border}`,
                    background: selected.has(idx) ? "#f0f4ff" : undefined,
                    cursor: "pointer",
                  }}
                  onClick={() => toggleSelect(idx)}
                >
                  <td style={{ padding: "10px 14px", textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={selected.has(idx)}
                      onChange={() => toggleSelect(idx)}
                      onClick={(e) => e.stopPropagation()}
                      style={{ cursor: "pointer", width: 16, height: 16 }}
                    />
                  </td>
                  <td style={{ padding: "10px 14px", color: BRAND.ink }}>{item.question}</td>
                  <td style={{ padding: "10px 14px", whiteSpace: "nowrap" }}>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      style={{ color: BRAND.red, textDecoration: "none", fontWeight: 600, fontSize: 13 }}
                    >
                      ▶ {mmss(item.t)}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Build results */}
      {results !== null && (
        <>
          <h3 style={{ color: BRAND.navyText, fontSize: 16, margin: "0 0 14px" }}>
            Grounded answers ({results.length})
          </h3>
          {results.length === 0 ? (
            <Card>
              <p style={{ color: BRAND.sub, fontSize: 14, margin: 0 }}>No answers returned.</p>
            </Card>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {results.map((entry, i) => (
                <Card key={i} style={{ borderTop: `3px solid ${BRAND.red}` }}>
                  <p style={{ margin: "0 0 8px", fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>
                    {entry.question}
                  </p>
                  <p style={{ margin: "0 0 10px", color: BRAND.ink, fontSize: 14, lineHeight: 1.6 }}>
                    {entry.answer}
                  </p>
                  {entry.citations.length > 0 && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {entry.citations.map((url, j) => (
                        <a
                          key={j}
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: BRAND.red, fontSize: 12, textDecoration: "none", fontWeight: 600 }}
                        >
                          ▶ Source {j + 1}
                        </a>
                      ))}
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  );
}
