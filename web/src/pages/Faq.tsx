import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

interface FaqItem {
  id: number;
  question: string;
  answer: string | null;
  status: string;
  video_id: string;
  video_title: string;
  url: string;
  start: number;
}

interface FaqListResponse {
  total: number;
  items: FaqItem[];
}

interface Coverage {
  mined: number;
  answered: number;
  uncovered_nodes: number;
}

interface PublishResult {
  page_id: number;
  page_url: string;
  published: number;
  action: "created" | "updated";
}

interface EstimateResult {
  count: number;
  mine_cost_usd: number;
  answer_cost_usd: number;
  model: string;
  caps: { mine_max: number; answer_batch_max: number };
}

const MINE_BATCH_OPTIONS = [50, 100, 200] as const;
const ANSWER_BATCH_OPTIONS = [25, 50, 100] as const;

function fmt$( n: number): string {
  return `$${n.toFixed(4)}`;
}

function mmss(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const PAGE_SIZE = 50;

export function Faq() {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [items, setItems] = useState<FaqItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [answeredFilter, setAnsweredFilter] = useState<"all" | "yes" | "no">("all");
  const [loading, setLoading] = useState(true);
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mining, setMining] = useState(false);
  const [generatingBatch, setGeneratingBatch] = useState(false);
  const [answeringId, setAnsweringId] = useState<number | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<PublishResult | null>(null);
  const [mineBatchSize, setMineBatchSize] = useState<number>(200);
  const [answerBatchSize, setAnswerBatchSize] = useState<number>(25);
  const [mineEstimate, setMineEstimate] = useState<EstimateResult | null>(null);
  const [answerEstimate, setAnswerEstimate] = useState<EstimateResult | null>(null);
  const filterTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function loadCoverage() {
    setCoverageLoading(true);
    apiFetch("/faq/coverage")
      .then((r) => r.json())
      .then((d: Coverage) => setCoverage(d))
      .catch(() => setCoverage(null))
      .finally(() => setCoverageLoading(false));
  }

  function fetchEstimate(count: number, setter: (e: EstimateResult) => void) {
    apiFetch(`/faq/estimate?count=${count}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: EstimateResult | null) => { if (d) setter(d); })
      .catch(() => {});
  }

  useEffect(() => { fetchEstimate(mineBatchSize, setMineEstimate); }, [mineBatchSize]);
  useEffect(() => { fetchEstimate(answerBatchSize, setAnswerEstimate); }, [answerBatchSize]);

  function loadItems(q: string, ans: "all" | "yes" | "no", off: number) {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(off),
      answered: ans,
    });
    if (q) params.set("q", q);
    apiFetch(`/faq?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d: FaqListResponse) => {
        setItems(d.items);
        setTotal(d.total);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadCoverage();
    loadItems("", "all", 0);
    fetchEstimate(mineBatchSize, setMineEstimate);
    fetchEstimate(answerBatchSize, setAnswerEstimate);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleFilterChange(val: string) {
    setFilter(val);
    if (filterTimer.current) clearTimeout(filterTimer.current);
    filterTimer.current = setTimeout(() => {
      setOffset(0);
      loadItems(val, answeredFilter, 0);
    }, 350);
  }

  function handleAnsweredChange(val: "all" | "yes" | "no") {
    setAnsweredFilter(val);
    setOffset(0);
    loadItems(filter, val, 0);
  }

  function handleLoadMore() {
    const nextOffset = offset + PAGE_SIZE;
    setOffset(nextOffset);
    apiFetch(`/faq?limit=${PAGE_SIZE}&offset=${nextOffset}&answered=${answeredFilter}${filter ? `&q=${encodeURIComponent(filter)}` : ""}`)
      .then((r) => r.json())
      .then((d: FaqListResponse) => {
        setItems((prev) => [...prev, ...d.items]);
        setTotal(d.total);
      });
  }

  async function handleMine() {
    setMining(true);
    setActionMsg(null);
    try {
      const r = await apiFetch("/faq/mine", { method: "POST", body: JSON.stringify({ limit: mineBatchSize }) });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const d = await r.json();
      setActionMsg(`Mined ${d.mined} new questions. ${d.remaining_uncovered} content items still available.`);
      loadCoverage();
      setOffset(0);
      loadItems(filter, answeredFilter, 0);
    } catch (e: unknown) {
      setActionMsg(`Mine failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setMining(false);
    }
  }

  async function handleGenerateBatch() {
    setGeneratingBatch(true);
    setActionMsg(null);
    try {
      const r = await apiFetch("/faq/answer-batch", { method: "POST", body: JSON.stringify({ limit: answerBatchSize }) });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const d = await r.json();
      setActionMsg(`Generated ${d.answered} answers. ${d.remaining} still unanswered.`);
      loadCoverage();
      setOffset(0);
      loadItems(filter, answeredFilter, 0);
    } catch (e: unknown) {
      setActionMsg(`Generate failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGeneratingBatch(false);
    }
  }

  async function handleAnswerOne(item: FaqItem) {
    setAnsweringId(item.id);
    try {
      const r = await apiFetch(`/faq/${item.id}/answer`, { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const updated: FaqItem = await r.json();
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      loadCoverage();
    } catch (e: unknown) {
      setActionMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setAnsweringId(null);
    }
  }

  async function handlePublishWordPress() {
    setPublishing(true);
    setPublishResult(null);
    setActionMsg(null);
    try {
      const r = await apiFetch("/faq/publish-wordpress", { method: "POST" });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const d: PublishResult = await r.json();
      setPublishResult(d);
    } catch (e: unknown) {
      setActionMsg(`Publish failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPublishing(false);
    }
  }

  const hasMore = offset + PAGE_SIZE < total;

  return (
    <main style={{ maxWidth: 960 }}>
      <PageTitle>FAQ Builder</PageTitle>

      {/* Coverage summary bar */}
      <Card style={{ marginBottom: 20 }}>
        {coverageLoading ? (
          <p style={{ margin: 0, fontSize: 14, color: BRAND.sub }}>Loading coverage…</p>
        ) : coverage ? (
          <>
            {/* Empty-state: no questions mined yet but content is available */}
            {coverage.mined === 0 && coverage.uncovered_nodes > 0 && (
              <div style={{
                background: "#fff8e1",
                border: "1px solid #ffe082",
                borderRadius: 8,
                padding: "16px 20px",
                marginBottom: 16,
              }}>
                <p style={{ margin: "0 0 10px", fontWeight: 700, fontSize: 15, color: BRAND.navyText }}>
                  No questions mined yet — {coverage.uncovered_nodes.toLocaleString()} content items available
                </p>
                <p style={{ margin: "0 0 12px", fontSize: 13, color: BRAND.ink }}>
                  The content graph has been built from your videos. Click below to extract FAQ questions
                  from claims and objections found in the content.
                </p>
                <Button onClick={handleMine} disabled={mining} style={{ fontSize: 14 }}>
                  {mining ? "Mining questions…" : `Mine ${coverage.uncovered_nodes.toLocaleString()} questions now`}
                </Button>
              </div>
            )}

            <div style={{ fontSize: 14, color: BRAND.ink, marginBottom: 12 }}>
              <strong style={{ color: BRAND.navyText }}>{coverage.mined}</strong> questions mined
              {" · "}
              <strong style={{ color: BRAND.navyText }}>{coverage.answered}</strong> answered
              {" · "}
              <strong style={{ color: BRAND.navyText }}>{coverage.uncovered_nodes.toLocaleString()}</strong> available to mine
            </div>

            {/* Mine batch controls */}
            {coverage.uncovered_nodes > 0 && (
              <div style={{ background: BRAND.bg, borderRadius: 8, padding: "12px 16px", marginBottom: 12 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, color: BRAND.ink, fontWeight: 600 }}>Mine questions:</span>
                  {MINE_BATCH_OPTIONS.map((n) => (
                    <button
                      key={n}
                      onClick={() => setMineBatchSize(n)}
                      style={{
                        padding: "4px 12px", borderRadius: 6, fontSize: 13, cursor: "pointer",
                        fontWeight: mineBatchSize === n ? 700 : 400,
                        background: mineBatchSize === n ? BRAND.navy : "#fff",
                        color: mineBatchSize === n ? "#fff" : BRAND.navyText,
                        border: `1px solid ${mineBatchSize === n ? BRAND.navy : BRAND.border}`,
                      }}
                    >
                      {n}
                    </button>
                  ))}
                  <Button onClick={handleMine} disabled={mining || coverage.uncovered_nodes === 0} style={{ fontSize: 13 }}>
                    {mining ? "Mining…" : `Mine ${mineBatchSize}`}
                  </Button>
                </div>
                <p style={{ margin: 0, fontSize: 12, color: BRAND.sub }}>
                  {mineEstimate
                    ? <>Mining {mineBatchSize} questions ~ <strong>{fmt$(mineEstimate.mine_cost_usd)}</strong> (estimate, {mineEstimate.model})</>
                    : "Loading estimate…"}
                  {coverage.uncovered_nodes > 500 && mineEstimate && (
                    <> · Mining all {coverage.uncovered_nodes.toLocaleString()} ~ <strong>{fmt$(mineEstimate.mine_cost_usd / mineBatchSize * coverage.uncovered_nodes)}</strong> (estimate)</>
                  )}
                </p>
              </div>
            )}

            {/* Answer batch controls */}
            {coverage.mined > coverage.answered && (
              <div style={{ background: BRAND.bg, borderRadius: 8, padding: "12px 16px", marginBottom: 12 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, color: BRAND.ink, fontWeight: 600 }}>Generate answers:</span>
                  {ANSWER_BATCH_OPTIONS.map((n) => (
                    <button
                      key={n}
                      onClick={() => setAnswerBatchSize(n)}
                      style={{
                        padding: "4px 12px", borderRadius: 6, fontSize: 13, cursor: "pointer",
                        fontWeight: answerBatchSize === n ? 700 : 400,
                        background: answerBatchSize === n ? BRAND.navy : "#fff",
                        color: answerBatchSize === n ? "#fff" : BRAND.navyText,
                        border: `1px solid ${answerBatchSize === n ? BRAND.navy : BRAND.border}`,
                      }}
                    >
                      {n}
                    </button>
                  ))}
                  <Button onClick={handleGenerateBatch} disabled={generatingBatch} style={{ fontSize: 13 }}>
                    {generatingBatch ? "Generating…" : `Generate ${answerBatchSize}`}
                  </Button>
                </div>
                <p style={{ margin: 0, fontSize: 12, color: BRAND.sub }}>
                  {answerEstimate
                    ? <>Answering {answerBatchSize} questions ~ <strong>{fmt$(answerEstimate.answer_cost_usd)}</strong> (estimate, {answerEstimate.model})</>
                    : "Loading estimate…"}
                  {coverage.mined - coverage.answered > 100 && answerEstimate && (
                    <> · Answering all {(coverage.mined - coverage.answered).toLocaleString()} unanswered ~ <strong>{fmt$(answerEstimate.answer_cost_usd / answerBatchSize * (coverage.mined - coverage.answered))}</strong> (estimate)</>
                  )}
                </p>
              </div>
            )}

            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {coverage.answered > 0 && (
                <Button
                  onClick={handlePublishWordPress}
                  disabled={publishing}
                  variant="ghost"
                  style={{ whiteSpace: "nowrap", fontSize: 13 }}
                >
                  {publishing
                    ? "Publishing…"
                    : `Publish FAQ to website (${coverage.answered} answered)`}
                </Button>
              )}
            </div>

            {publishResult && (
              <p style={{ margin: "10px 0 0", fontSize: 13, color: BRAND.ink }}>
                FAQ page {publishResult.action} on WordPress ({publishResult.published} Q&amp;As).{" "}
                <a
                  href={publishResult.page_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: BRAND.red, fontWeight: 600 }}
                >
                  View page
                </a>
              </p>
            )}
          </>
        ) : (
          <p style={{ margin: 0, fontSize: 14, color: BRAND.sub }}>Coverage unavailable.</p>
        )}
        {actionMsg && (
          <p style={{ margin: "10px 0 0", fontSize: 13, color: BRAND.sub }}>{actionMsg}</p>
        )}
      </Card>

      {/* Filters */}
      <Card style={{ marginBottom: 20, padding: "14px 20px" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value)}
            placeholder="Search questions…"
            style={{ ...inputStyle, flex: 1, minWidth: 180 }}
          />
          <select
            value={answeredFilter}
            onChange={(e) => handleAnsweredChange(e.target.value as "all" | "yes" | "no")}
            style={{ ...inputStyle, minWidth: 130 }}
          >
            <option value="all">All</option>
            <option value="yes">Answered</option>
            <option value="no">Unanswered</option>
          </select>
          <span style={{ fontSize: 13, color: BRAND.sub, whiteSpace: "nowrap" }}>
            {total} question{total !== 1 ? "s" : ""}
          </span>
        </div>
      </Card>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && items.length === 0 && (
        <Card>
          <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
            {filter
              ? `No questions found for "${filter}".`
              : coverage && coverage.mined === 0 && coverage.uncovered_nodes > 0
              ? `Use the "Mine questions now" button above to generate FAQ questions from your content.`
              : "No questions found. Use \"Mine more\" to generate from content."}
          </p>
        </Card>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {items.map((item) => (
              <Card key={item.id} style={{ borderLeft: `4px solid ${item.status === "answered" ? BRAND.navy : BRAND.border}` }}>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: "0 0 6px", fontWeight: 700, color: BRAND.navyText, fontSize: 15 }}>
                      {item.question}
                    </p>
                    {item.answer ? (
                      <p style={{ margin: "0 0 8px", color: BRAND.ink, fontSize: 14, lineHeight: 1.6 }}>
                        {item.answer}
                      </p>
                    ) : (
                      <p style={{ margin: "0 0 8px", color: BRAND.sub, fontSize: 13, fontStyle: "italic" }}>
                        No answer yet.
                      </p>
                    )}
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: BRAND.red, fontSize: 13, textDecoration: "none", fontWeight: 600 }}
                    >
                      ▶ {item.video_title} @ {mmss(item.start)}
                    </a>
                  </div>
                  {item.status !== "answered" && (
                    <Button
                      variant="ghost"
                      disabled={answeringId === item.id}
                      onClick={() => handleAnswerOne(item)}
                      style={{ fontSize: 12, padding: "6px 12px", whiteSpace: "nowrap", flexShrink: 0 }}
                    >
                      {answeringId === item.id ? "Generating…" : "Generate answer"}
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>

          {hasMore && (
            <div style={{ textAlign: "center", marginTop: 20 }}>
              <Button variant="ghost" onClick={handleLoadMore} style={{ fontSize: 13 }}>
                Load more ({total - offset - items.length} remaining)
              </Button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
