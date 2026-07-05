import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, inputStyle, Loading, ErrorMsg } from "../ui";

interface EmailTemplate {
  id: number;
  name: string;
  subject: string;
  body: string;
}

interface ProofResult {
  proofed: string;
  suggestions: unknown;
}

interface Props {
  /** Pre-filled body text (e.g. source links built from SearchAsk). */
  initialBody?: string;
  onClose: () => void;
}

export function ComposeEmailModal({ initialBody = "", onClose }: Props) {
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState<string | null>(null);

  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState(initialBody);

  const [proofLoading, setProofLoading] = useState(false);
  const [proofError, setProofError] = useState<string | null>(null);
  const [proofResult, setProofResult] = useState<ProofResult | null>(null);

  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sentId, setSentId] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/email/templates")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: EmailTemplate[]) => setTemplates(data))
      .catch((e) => setTemplatesError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTemplatesLoading(false));
  }, []);

  function handleTemplateChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = Number(e.target.value);
    if (!id) return;
    const tpl = templates.find((t) => t.id === id);
    if (tpl) {
      setSubject(tpl.subject);
      // Prepend the pre-filled body (source links) after the template body if present.
      setBody(body.trim() ? `${tpl.body}\n\n${body}` : tpl.body);
      setProofResult(null);
      setSentId(null);
      setSendError(null);
    }
  }

  async function handleProofread() {
    setProofLoading(true);
    setProofError(null);
    setProofResult(null);
    try {
      const r = await apiFetch("/email/proof", {
        method: "POST",
        body: JSON.stringify({ draft: body }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data: ProofResult = await r.json();
      setProofResult(data);
    } catch (e) {
      setProofError(e instanceof Error ? e.message : String(e));
    } finally {
      setProofLoading(false);
    }
  }

  async function handleSend() {
    setSending(true);
    setSendError(null);
    setSentId(null);
    try {
      const r = await apiFetch("/email/send", {
        method: "POST",
        body: JSON.stringify({ to, subject, html: body }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const data: { id: string } = await r.json();
      setSentId(data.id);
      setTo("");
      setSubject("");
      setBody("");
      setProofResult(null);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  const canSend = !sending && to.trim() !== "" && subject.trim() !== "" && body.trim() !== "";

  return (
    // Backdrop
    <div
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 1000,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "48px 16px 32px",
        overflowY: "auto",
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 14,
          width: "100%",
          maxWidth: 680,
          boxShadow: "0 8px 32px rgba(16,24,40,0.18)",
          padding: 28,
          position: "relative",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: BRAND.navyText }}>
            Compose Email
          </h3>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: 20,
              color: BRAND.sub,
              lineHeight: 1,
              padding: "2px 6px",
            }}
          >
            ×
          </button>
        </div>

        {/* Template picker */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
            Load from template
          </label>
          {templatesLoading && <Loading label="Loading templates…" />}
          {templatesError && <ErrorMsg>Could not load templates: {templatesError}</ErrorMsg>}
          {!templatesLoading && !templatesError && (
            <select
              defaultValue=""
              onChange={handleTemplateChange}
              style={{ ...inputStyle, width: "100%" }}
            >
              <option value="">— choose a template —</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          )}
        </div>

        {/* Compose fields */}
        <Card style={{ marginBottom: 18 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
                To
              </label>
              <input
                type="email"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                placeholder="recipient@example.com"
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
                Subject
              </label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Email subject"
                style={{ ...inputStyle, width: "100%" }}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
                Body
              </label>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={10}
                style={{ ...inputStyle, width: "100%", resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <Button
                variant="ghost"
                onClick={handleProofread}
                disabled={proofLoading || body.trim() === ""}
              >
                {proofLoading ? "Proofreading…" : "Proofread"}
              </Button>
              <Button onClick={handleSend} disabled={!canSend}>
                {sending ? "Sending…" : "Send"}
              </Button>
            </div>
          </div>
        </Card>

        {/* Proofread loading / error */}
        {proofLoading && <Loading label="Proofreading with Gemini…" />}
        {proofError && <ErrorMsg>Proofread failed: {proofError}</ErrorMsg>}

        {/* Proofread result */}
        {proofResult && (
          <Card style={{ marginBottom: 16, borderTop: `4px solid ${BRAND.navy}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Proofread version
              </span>
              <Button
                variant="ghost"
                style={{ padding: "5px 12px", fontSize: 13 }}
                onClick={() => { setBody(proofResult.proofed); setProofResult(null); }}
              >
                Use this
              </Button>
            </div>
            <pre style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: BRAND.ink, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>
              {proofResult.proofed}
            </pre>
            {proofResult.suggestions != null && (
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${BRAND.border}` }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: BRAND.sub, marginBottom: 8 }}>SUGGESTIONS</div>
                <div style={{ fontSize: 14, color: BRAND.ink, lineHeight: 1.6 }}>
                  {typeof proofResult.suggestions === "string"
                    ? proofResult.suggestions
                    : Array.isArray(proofResult.suggestions)
                    ? (proofResult.suggestions as string[]).map((s, i) => (
                        <div key={i} style={{ marginBottom: 4 }}>• {String(s)}</div>
                      ))
                    : JSON.stringify(proofResult.suggestions, null, 2)}
                </div>
              </div>
            )}
          </Card>
        )}

        {/* Send error */}
        {sendError && <ErrorMsg>Send failed: {sendError}</ErrorMsg>}

        {/* Send success */}
        {sentId && (
          <Card style={{ borderTop: `4px solid #1a7f4b` }}>
            <p style={{ margin: 0, fontSize: 15, color: "#1a7f4b", fontWeight: 600 }}>
              Email sent — message ID: <code style={{ fontWeight: 400 }}>{sentId}</code>
            </p>
            <div style={{ marginTop: 12 }}>
              <Button variant="ghost" onClick={onClose}>Close</Button>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
