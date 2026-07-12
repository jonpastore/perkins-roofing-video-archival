import { useState, useEffect } from "react";
import { apiFetch, apiFetchMultipart } from "../api";
import { BRAND, FONT, Button, Card, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

interface ContractFaqEntry {
  id: number;
  question: string;
  answer: string | null;
  quote: string | null;
  status: "draft" | "approved";
  created_at: string | null;
}

interface GenerateResult {
  generated: number;
  rejected_grounding: number;
  rejected_safety: number;
  entries: Array<{ q: string; a: string; quote: string }>;
}

interface AiPromptsResult {
  system_prompt: string;
  user_prompt: string;
  suggested_followups: string[];
}

interface TcVersion {
  id: number;
  version_tag: string;
  content_gcs: string | null;
  effective_at: string | null;
  created_at: string | null;
  tc_text?: string;
  chars?: number;
}

const COUNT_OPTIONS = [5, 10, 15, 20] as const;
type StatusFilter = "all" | "draft" | "approved";

export function ContractFaq() {
  const [tcText, setTcText] = useState("");
  const [count, setCount] = useState<number>(10);
  const [generating, setGenerating] = useState(false);
  const [generateResult, setGenerateResult] = useState<GenerateResult | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractMsg, setExtractMsg] = useState<string | null>(null);
  const [prompting, setPrompting] = useState(false);
  const [aiPrompts, setAiPrompts] = useState<AiPromptsResult | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [tcVersion, setTcVersion] = useState<TcVersion | null>(null);
  const [tcVersionLoading, setTcVersionLoading] = useState(false);
  const [tcVersionMsg, setTcVersionMsg] = useState<string | null>(null);
  const [tcVersionError, setTcVersionError] = useState<string | null>(null);
  const [savingVersion, setSavingVersion] = useState(false);

  const [entries, setEntries] = useState<ContractFaqEntry[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editQ, setEditQ] = useState("");
  const [editA, setEditA] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  function loadEntries(filter: StatusFilter = statusFilter) {
    setListLoading(true);
    setListError(null);
    const params = filter !== "all" ? `?status=${filter}` : "";
    apiFetch(`/contract-faq${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: ContractFaqEntry[]) => setEntries(data))
      .catch((e: unknown) => setListError(e instanceof Error ? e.message : String(e)))
      .finally(() => setListLoading(false));
  }

  function loadLatestTcVersion() {
    setTcVersionLoading(true);
    setTcVersionError(null);
    apiFetch("/contract-faq/tc-version/latest")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: TcVersion | null) => {
        if (!data) {
          setTcVersion(null);
          return;
        }
        setTcVersion(data);
        setTcText(data.tc_text ?? "");
        setTcVersionMsg(`Loaded saved T&C version ${data.version_tag} (${(data.chars ?? 0).toLocaleString()} chars).`);
      })
      .catch((e: unknown) => setTcVersionError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTcVersionLoading(false));
  }

  useEffect(() => {
    loadEntries();
    loadLatestTcVersion();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleStatusFilter(f: StatusFilter) {
    setStatusFilter(f);
    loadEntries(f);
  }

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    setGenerateResult(null);
    try {
      const r = await apiFetch("/contract-faq/generate", {
        method: "POST",
        body: JSON.stringify({ tc_text: tcText, count, tc_version_id: tcVersion?.id }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error((err as { detail?: string }).detail ?? r.statusText);
      }
      const data: GenerateResult = await r.json();
      setGenerateResult(data);
      loadEntries(statusFilter);
    } catch (e: unknown) {
      setGenerateError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function handlePdfUpload(file: File | null) {
    if (!file) return;
    setExtracting(true);
    setExtractMsg(null);
    setGenerateError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const tag = file.name.replace(/\.pdf$/i, "");
      const r = await apiFetchMultipart(`/contract-faq/extract-pdf?save=true&version_tag=${encodeURIComponent(tag)}`, { method: "POST", body: form });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error((err as { detail?: string }).detail ?? r.statusText);
      }
      const data: { filename: string; chars: number; text: string; tc_version?: TcVersion } = await r.json();
      setTcText(data.text);
      if (data.tc_version) setTcVersion(data.tc_version);
      setExtractMsg(`Saved and loaded ${data.chars.toLocaleString()} characters from ${data.filename}. Review/trim if needed, then generate more FAQs or AI prompts.`);
    } catch (e: unknown) {
      setGenerateError(e instanceof Error ? e.message : String(e));
    } finally {
      setExtracting(false);
    }
  }

  async function handleSaveVersion() {
    setSavingVersion(true);
    setTcVersionError(null);
    setTcVersionMsg(null);
    try {
      const tag = tcVersion?.version_tag
        ? `${tcVersion.version_tag}-edited-${new Date().toISOString().slice(0, 10)}`
        : `tc-${new Date().toISOString().slice(0, 10)}`;
      const r = await apiFetch("/contract-faq/tc-version", {
        method: "POST",
        body: JSON.stringify({ tc_text: tcText, version_tag: tag }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error((err as { detail?: string }).detail ?? r.statusText);
      }
      const data: TcVersion = await r.json();
      setTcVersion(data);
      setTcVersionMsg(`Saved T&C version ${data.version_tag} (${(data.chars ?? tcText.length).toLocaleString()} chars).`);
    } catch (e: unknown) {
      setTcVersionError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingVersion(false);
    }
  }

  async function handleGeneratePrompts() {
    setPrompting(true);
    setPromptError(null);
    setAiPrompts(null);
    try {
      const r = await apiFetch("/contract-faq/ai-prompts", {
        method: "POST",
        body: JSON.stringify({ tc_text: tcText, include_existing_faqs: true }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error((err as { detail?: string }).detail ?? r.statusText);
      }
      setAiPrompts(await r.json());
    } catch (e: unknown) {
      setPromptError(e instanceof Error ? e.message : String(e));
    } finally {
      setPrompting(false);
    }
  }

  function startEdit(entry: ContractFaqEntry) {
    setEditingId(entry.id);
    setEditQ(entry.question);
    setEditA(entry.answer ?? "");
  }

  function cancelEdit() {
    setEditingId(null);
    setEditQ("");
    setEditA("");
  }

  async function saveEdit(id: number) {
    setSavingId(id);
    try {
      const r = await apiFetch(`/contract-faq/${id}`, {
        method: "PUT",
        body: JSON.stringify({ question: editQ, answer: editA }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const updated: ContractFaqEntry = await r.json();
      setEntries((prev) => prev.map((e) => (e.id === id ? updated : e)));
      setEditingId(null);
    } catch (e: unknown) {
      setListError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  }

  async function handleApprove(id: number) {
    setApprovingId(id);
    try {
      const r = await apiFetch(`/contract-faq/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: "approved" }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const updated: ContractFaqEntry = await r.json();
      setEntries((prev) => prev.map((e) => (e.id === id ? updated : e)));
    } catch (e: unknown) {
      setListError(e instanceof Error ? e.message : String(e));
    } finally {
      setApprovingId(null);
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id);
    try {
      const r = await apiFetch(`/contract-faq/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch (e: unknown) {
      setListError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletingId(null);
    }
  }

  const draftCount = entries.filter((e) => e.status === "draft").length;
  const approvedCount = entries.filter((e) => e.status === "approved").length;

  function tabStyle(f: StatusFilter): React.CSSProperties {
    const active = statusFilter === f;
    return {
      padding: "7px 16px",
      border: "none",
      borderBottom: active ? `2px solid ${BRAND.red}` : "2px solid transparent",
      background: "none",
      cursor: "pointer",
      fontSize: 13,
      fontWeight: active ? 700 : 500,
      color: active ? BRAND.navyText : BRAND.sub,
      marginBottom: -1,
    };
  }

  return (
    <main style={{ maxWidth: 960, fontFamily: FONT }}>
      <PageTitle>Contract FAQ</PageTitle>

      {/* Generate panel */}
      <Card style={{ marginBottom: 24 }}>
        <p style={{ margin: "0 0 12px", fontWeight: 600, color: BRAND.navyText, fontSize: 15 }}>
          Generate FAQ from contract / T&amp;C
        </p>
        <p style={{ margin: "0 0 12px", fontSize: 13, color: BRAND.sub }}>
          Upload a text-based proposal/contract PDF or paste Terms &amp; Conditions below. The extracted
          text is saved as a versioned T&amp;C source so you can mine more FAQs and generate AI review prompts later.
        </p>
        <div style={{ marginBottom: 12, padding: 10, border: `1px solid ${BRAND.border ?? "#e3e7f0"}`, borderRadius: 8, background: BRAND.bg, fontSize: 12, color: BRAND.sub }}>
          {tcVersionLoading ? "Loading latest saved T&C version…" : tcVersion ? (
            <>Current saved version: <strong style={{ color: BRAND.navyText }}>{tcVersion.version_tag}</strong> · {(tcVersion.chars ?? tcText.length).toLocaleString()} chars</>
          ) : "No saved T&C version loaded yet."}
          {tcVersionMsg && <div style={{ marginTop: 4, color: "#1a7f4b" }}>{tcVersionMsg}</div>}
          {tcVersionError && <div style={{ marginTop: 4, color: BRAND.red }}>T&amp;C version error: {tcVersionError}</div>}
        </div>
        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8, cursor: extracting ? "wait" : "pointer" }}>
            <span style={{
              display: "inline-block",
              padding: "8px 12px",
              border: `1px solid ${BRAND.border ?? "#e3e7f0"}`,
              borderRadius: 8,
              color: BRAND.navyText,
              fontSize: 13,
              fontWeight: 700,
              background: "#fff",
            }}>
              {extracting ? "Extracting PDF…" : "Upload contract PDF"}
            </span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              disabled={extracting}
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                void handlePdfUpload(f);
                e.currentTarget.value = "";
              }}
              style={{ display: "none" }}
            />
          </label>
          <Button
            variant="ghost"
            onClick={handleSaveVersion}
            disabled={savingVersion || tcText.trim().length < 100}
            style={{ fontSize: 13, padding: "8px 12px" }}
          >
            {savingVersion ? "Saving…" : "Save T&C version"}
          </Button>
          <Button
            variant="ghost"
            onClick={loadLatestTcVersion}
            disabled={tcVersionLoading}
            style={{ fontSize: 13, padding: "8px 12px" }}
          >
            Reload latest saved
          </Button>
          {extractMsg && <span style={{ fontSize: 12, color: "#1a7f4b" }}>{extractMsg}</span>}
        </div>
        <textarea
          value={tcText}
          onChange={(e) => setTcText(e.target.value)}
          placeholder="Paste contract Terms & Conditions text here (minimum 100 characters)…"
          rows={8}
          style={{
            ...inputStyle,
            width: "100%",
            resize: "vertical",
            fontFamily: "monospace",
            fontSize: 13,
            marginBottom: 12,
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, color: BRAND.ink, fontWeight: 600 }}>Pairs to generate:</span>
          {COUNT_OPTIONS.map((n) => (
            <button
              key={n}
              onClick={() => setCount(n)}
              style={{
                padding: "4px 12px",
                borderRadius: 6,
                fontSize: 13,
                cursor: "pointer",
                fontWeight: count === n ? 700 : 400,
                background: count === n ? BRAND.navy : "#fff",
                color: count === n ? "#fff" : BRAND.navyText,
                border: `1px solid ${count === n ? BRAND.navy : (BRAND.border ?? "#e3e7f0")}`,
              }}
            >
              {n}
            </button>
          ))}
          <Button
            onClick={handleGenerate}
            disabled={generating || tcText.trim().length < 100}
            style={{ marginLeft: "auto", fontSize: 13 }}
          >
            {generating ? "Generating…" : `Generate ${count} pairs`}
          </Button>
          <Button
            variant="ghost"
            onClick={handleGeneratePrompts}
            disabled={prompting || tcText.trim().length < 100}
            style={{ fontSize: 13 }}
          >
            {prompting ? "Building prompts…" : "AI review prompts"}
          </Button>
        </div>
        {generateError && (
          <div style={{ marginTop: 10 }}>
            <ErrorMsg>Generate failed: {generateError}</ErrorMsg>
          </div>
        )}
        {generateResult && (
          <p style={{ marginTop: 10, fontSize: 13, color: BRAND.ink }}>
            Generated <strong>{generateResult.generated}</strong> entries.
            {generateResult.rejected_grounding > 0 && (
              <> Rejected <strong>{generateResult.rejected_grounding}</strong> (not grounded in contract).</>
            )}
            {generateResult.rejected_safety > 0 && (
              <> Rejected <strong>{generateResult.rejected_safety}</strong> (safety).</>
            )}
          </p>
        )}
        {promptError && (
          <div style={{ marginTop: 10 }}>
            <ErrorMsg>Prompt generation failed: {promptError}</ErrorMsg>
          </div>
        )}
        {aiPrompts && (
          <Card style={{ marginTop: 14, background: BRAND.bg }}>
            <p style={{ margin: "0 0 8px", fontWeight: 700, color: BRAND.navyText, fontSize: 13 }}>
              Copy/paste AI review prompts
            </p>
            <p style={{ margin: "0 0 10px", color: BRAND.sub, fontSize: 12 }}>
              Use these in ChatGPT/Claude/Gemini to explain the contract and cross-check the FAQ both ways.
            </p>
            <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", marginBottom: 4 }}>System prompt</label>
            <textarea readOnly value={aiPrompts.system_prompt} rows={3} style={{ ...inputStyle, width: "100%", fontSize: 12, fontFamily: "monospace", marginBottom: 10 }} />
            <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", marginBottom: 4 }}>User prompt</label>
            <textarea readOnly value={aiPrompts.user_prompt} rows={8} style={{ ...inputStyle, width: "100%", fontSize: 12, fontFamily: "monospace", marginBottom: 10 }} />
            <label style={{ display: "block", fontSize: 11, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", marginBottom: 4 }}>Suggested follow-ups</label>
            <ul style={{ margin: 0, paddingLeft: 18, color: BRAND.ink, fontSize: 13 }}>
              {aiPrompts.suggested_followups.map((p) => <li key={p}>{p}</li>)}
            </ul>
          </Card>
        )}
      </Card>

      {/* Entries table */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", borderBottom: `1px solid ${BRAND.border ?? "#e3e7f0"}`, marginBottom: 16 }}>
          <button style={tabStyle("all")} onClick={() => handleStatusFilter("all")}>
            All
            <span style={{
              marginLeft: 6, fontSize: 11, fontWeight: 700, padding: "1px 6px",
              borderRadius: 10, background: "#eef1f5", color: BRAND.sub,
            }}>{entries.length}</span>
          </button>
          <button style={tabStyle("draft")} onClick={() => handleStatusFilter("draft")}>
            Draft
            {draftCount > 0 && (
              <span style={{
                marginLeft: 6, fontSize: 11, fontWeight: 700, padding: "1px 6px",
                borderRadius: 10, background: "#fff3e0", color: "#b45309",
              }}>{draftCount}</span>
            )}
          </button>
          <button style={tabStyle("approved")} onClick={() => handleStatusFilter("approved")}>
            Approved
            {approvedCount > 0 && (
              <span style={{
                marginLeft: 6, fontSize: 11, fontWeight: 700, padding: "1px 6px",
                borderRadius: 10, background: "#e8f5e9", color: "#2e7d32",
              }}>{approvedCount}</span>
            )}
          </button>
        </div>

        {listLoading && <Loading label="Loading entries…" />}
        {listError && <ErrorMsg>Error: {listError}</ErrorMsg>}

        {!listLoading && !listError && entries.length === 0 && (
          <Card>
            <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
              No contract FAQ entries yet. Paste T&amp;C text above and click Generate.
            </p>
          </Card>
        )}

        {!listLoading && entries.length > 0 && (
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border ?? "#e3e7f0"}`, textAlign: "left" }}>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, width: "30%" }}>Question</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, width: "35%" }}>Answer</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, width: "20%" }}>Supporting quote</th>
                  <th style={{ padding: "10px 16px", color: BRAND.sub, fontWeight: 600, width: "15%", whiteSpace: "nowrap" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr
                    key={entry.id}
                    style={{
                      borderBottom: `1px solid ${BRAND.border ?? "#e3e7f0"}`,
                      background: entry.status === "approved" ? "#f9fff9" : undefined,
                    }}
                  >
                    <td style={{ padding: "10px 16px", verticalAlign: "top" }}>
                      {editingId === entry.id ? (
                        <textarea
                          value={editQ}
                          onChange={(e) => setEditQ(e.target.value)}
                          rows={3}
                          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
                        />
                      ) : (
                        <span style={{ fontWeight: 600, color: BRAND.navyText }}>{entry.question}</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 16px", verticalAlign: "top" }}>
                      {editingId === entry.id ? (
                        <textarea
                          value={editA}
                          onChange={(e) => setEditA(e.target.value)}
                          rows={3}
                          style={{ ...inputStyle, width: "100%", fontSize: 13 }}
                        />
                      ) : (
                        <span style={{ color: BRAND.ink }}>{entry.answer ?? ""}</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 16px", verticalAlign: "top" }}>
                      {entry.quote ? (
                        <span style={{
                          fontSize: 12, color: BRAND.sub, fontStyle: "italic",
                          borderLeft: `3px solid ${BRAND.border ?? "#e3e7f0"}`, paddingLeft: 8,
                          display: "block",
                        }}>
                          "{entry.quote}"
                        </span>
                      ) : (
                        <span style={{ color: BRAND.sub, fontSize: 12 }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 16px", verticalAlign: "top", whiteSpace: "nowrap" }}>
                      {editingId === entry.id ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          <Button
                            onClick={() => saveEdit(entry.id)}
                            disabled={savingId === entry.id}
                            style={{ fontSize: 12, padding: "5px 10px" }}
                          >
                            {savingId === entry.id ? "Saving…" : "Save"}
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={cancelEdit}
                            style={{ fontSize: 12, padding: "5px 10px" }}
                          >
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {entry.status === "draft" && (
                            <Button
                              onClick={() => handleApprove(entry.id)}
                              disabled={approvingId === entry.id}
                              style={{ fontSize: 12, padding: "5px 10px", background: "#2e7d32" }}
                            >
                              {approvingId === entry.id ? "…" : "Approve"}
                            </Button>
                          )}
                          {entry.status === "approved" && (
                            <span style={{
                              fontSize: 11, fontWeight: 700, color: "#2e7d32",
                              padding: "3px 8px", background: "#e8f5e9", borderRadius: 10,
                              textAlign: "center",
                            }}>
                              Approved
                            </span>
                          )}
                          <Button
                            variant="ghost"
                            onClick={() => startEdit(entry)}
                            style={{ fontSize: 12, padding: "5px 10px" }}
                          >
                            Edit
                          </Button>
                          <button
                            onClick={() => handleDelete(entry.id)}
                            disabled={deletingId === entry.id}
                            style={{
                              background: "none", border: "none", cursor: "pointer",
                              color: BRAND.red, fontSize: 12, padding: "5px 0",
                              textAlign: "left", fontWeight: 500,
                            }}
                          >
                            {deletingId === entry.id ? "Deleting…" : "Delete"}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </main>
  );
}
