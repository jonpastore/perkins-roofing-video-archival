import { useEffect, useRef, useState } from "react";
import { Editor } from "@tinymce/tinymce-react";
import "tinymce/tinymce";
import "tinymce/models/dom/model";
import "tinymce/themes/silver";
import "tinymce/icons/default";
import "tinymce/plugins/lists";
import "tinymce/plugins/link";
import "tinymce/plugins/image";
import "tinymce/plugins/code";
import "tinymce/plugins/table";
// Self-hosted skin: with skin:false the UI CSS must be bundled explicitly or the
// editor mounts invisibly (the "blank Body" bug). All local — no CDN, no API key.
import "tinymce/skins/ui/oxide/skin.css";
import contentUiCss from "tinymce/skins/ui/oxide/content.css?raw";
import contentCss from "tinymce/skins/content/default/content.css?raw";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, inputStyle, Loading, ErrorMsg } from "../ui";

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

export function ComposeEmail() {
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState<string | null>(null);

  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const [signature, setSignature] = useState<string | null>(null);

  const [proofLoading, setProofLoading] = useState(false);
  const [proofError, setProofError] = useState<string | null>(null);
  const [proofResult, setProofResult] = useState<ProofResult | null>(null);

  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sentId, setSentId] = useState<string | null>(null);

  const [savingTemplate, setSavingTemplate] = useState(false);
  const [saveTemplateError, setSaveTemplateError] = useState<string | null>(null);

  const editorRef = useRef<unknown>(null);

  useEffect(() => {
    apiFetch("/email/templates")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: EmailTemplate[]) => setTemplates(data))
      .catch((e) => setTemplatesError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTemplatesLoading(false));

    apiFetch("/me/signature")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { signature?: string | null } | null) => {
        if (data?.signature) setSignature(data.signature);
      })
      .catch(() => null);
  }, []);

  function handleTemplateChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = Number(e.target.value);
    if (!id) return;
    const tpl = templates.find((t) => t.id === id);
    if (tpl) {
      setSubject(tpl.subject);
      setBody(tpl.body);
      setProofResult(null);
      setSentId(null);
      setSendError(null);
    }
  }

  async function handleSaveTemplate() {
    const name = prompt("Template name:");
    if (!name?.trim()) return;
    setSavingTemplate(true);
    setSaveTemplateError(null);
    try {
      const r = await apiFetch("/email/templates", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), subject, body }),
      });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const created: EmailTemplate = await r.json();
      setTemplates((prev) => [...prev, created]);
    } catch (e) {
      setSaveTemplateError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingTemplate(false);
    }
  }

  function handleInsertSignature() {
    if (!signature) return;
    setBody((prev) => prev + "<br><br>" + signature);
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
    <main style={{ maxWidth: 720 }}>
      <PageTitle>Compose Email</PageTitle>

      {/* Template picker */}
      <div style={{ marginBottom: 20 }}>
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
      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
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
            <Editor
              licenseKey="gpl"
              onInit={(_evt, editor) => { editorRef.current = editor; }}
              value={body}
              onEditorChange={(content) => setBody(content)}
              init={{
                skin: false,
                content_css: false,
                content_style: [contentUiCss, contentCss].join("\n"),
                menubar: false,
                plugins: "lists link image code table",
                toolbar: "undo redo | bold italic | bullist numlist | link image | code",
                height: 320,
                branding: false,
              }}
            />
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center" }}>
            {saveTemplateError && (
              <span style={{ fontSize: 12, color: BRAND.red, marginRight: "auto" }}>
                Save failed: {saveTemplateError}
              </span>
            )}
            {signature && (
              <Button variant="ghost" onClick={handleInsertSignature} style={{ fontSize: 13 }}>
                Insert signature
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={handleSaveTemplate}
              disabled={savingTemplate || body.trim() === "" || subject.trim() === ""}
              style={{ fontSize: 13 }}
            >
              {savingTemplate ? "Saving…" : "Save as template"}
            </Button>
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
        <Card style={{ marginBottom: 20, borderTop: `4px solid ${BRAND.navy}` }}>
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
        </Card>
      )}
    </main>
  );
}
