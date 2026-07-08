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
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Loading, ErrorMsg, Badge, inputStyle } from "../ui";
import { getAuth } from "firebase/auth";

interface FirebaseUser {
  uid: string;
  email: string;
  display_name: string | null;
  role: string | null;
  signature: string | null;
}

interface DirectoryUser {
  email: string;
  display_name: string | null;
}

type RoleOption = "admin" | "web_admin" | "sales" | "";
type InviteType = "external" | "internal";

function roleBadge(role: string | null) {
  if (role === "admin") return <Badge tone="blue">admin</Badge>;
  if (role === "web_admin") return <Badge tone="amber">web admin</Badge>;
  if (role === "sales") return <Badge tone="green">sales</Badge>;
  return <Badge tone="gray">none</Badge>;
}

const INVITE_ROLES: RoleOption[] = ["admin", "web_admin", "sales"];

// Inline SVG icon buttons matching Archive.tsx style
function IconButton({
  title,
  onClick,
  disabled,
  children,
  color,
}: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      style={{
        background: "none",
        border: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        padding: "4px 6px",
        lineHeight: 1,
        color: disabled ? "#bbb" : (color ?? BRAND.navy),
        display: "flex",
        alignItems: "center",
      }}
    >
      {children}
    </button>
  );
}

// Pencil SVG
function PencilIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 2.474L4.934 12.454l-3.517.879.879-3.517L11.013 1.427Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  );
}

// Disk / save SVG
function SaveIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="1.5" y="1.5" width="13" height="13" rx="2" stroke="currentColor" strokeWidth="1.5"/>
      <rect x="4" y="1.5" width="8" height="5" rx="0.5" stroke="currentColor" strokeWidth="1.25"/>
      <rect x="3" y="9" width="10" height="5" rx="1" stroke="currentColor" strokeWidth="1.25"/>
    </svg>
  );
}

// Trash-can SVG
function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M2 4h12M5.5 4V2.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V4m1.5 0-.75 9a1 1 0 0 1-1 .95H4.75a1 1 0 0 1-1-.95L3 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

// Signature modal with TinyMCE + copy-from-user
interface SigModalProps {
  user: FirebaseUser;
  allUsers: FirebaseUser[];
  initialHtml: string;
  saving: boolean;
  error: string | undefined;
  onSave: (html: string) => void;
  onClose: () => void;
}

function SignatureModal({ user, allUsers, initialHtml, saving, error, onSave, onClose }: SigModalProps) {
  const [html, setHtml] = useState(initialHtml);
  const editorRef = useRef<unknown>(null);

  // Users with non-empty signatures, excluding the current user
  const copyableSources = allUsers.filter(
    (u) => u.uid !== user.uid && u.signature && u.signature.trim() !== ""
  );

  function handleCopyFrom(e: React.ChangeEvent<HTMLSelectElement>) {
    const email = e.target.value;
    if (!email) return;
    const src = allUsers.find((u) => u.email === email);
    if (src?.signature) {
      setHtml(src.signature);
    }
    // Reset select back to placeholder
    e.target.value = "";
  }

  return (
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
            Edit signature — {user.display_name ?? user.email}
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

        {/* Copy from another user */}
        {copyableSources.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
              Copy signature from…
            </label>
            <select
              defaultValue=""
              onChange={handleCopyFrom}
              style={{ ...inputStyle, width: "100%", padding: "7px 10px", fontSize: 13 }}
            >
              <option value="">— select a user —</option>
              {copyableSources.map((u) => (
                <option key={u.uid} value={u.email}>
                  {u.email}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* TinyMCE editor */}
        <div style={{ marginBottom: 18 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: BRAND.navyText, marginBottom: 6 }}>
            Signature HTML
          </label>
          <Editor
            licenseKey="gpl"
            onInit={(_evt, editor) => { editorRef.current = editor; }}
            value={html}
            onEditorChange={(content) => setHtml(content)}
            init={{
              skin: false,
              content_css: false,
              menubar: false,
              plugins: "lists link image code table",
              toolbar: "undo redo | bold italic | bullist numlist | link image | code",
              height: 300,
              branding: false,
            }}
          />
        </div>

        {error && <p style={{ color: BRAND.red, fontSize: 13, marginBottom: 12 }}>{error}</p>}

        {/* Footer buttons */}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose} style={{ fontSize: 13 }}>
            Cancel
          </Button>
          <Button onClick={() => onSave(html)} disabled={saving} style={{ fontSize: 13 }}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function Users() {
  const [users, setUsers] = useState<FirebaseUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, RoleOption>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});
  const [myEmail, setMyEmail] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Record<string, boolean>>({});
  const [sigSaving, setSigSaving] = useState<Record<string, boolean>>({});
  const [sigError, setSigError] = useState<Record<string, string>>({});

  // Signature modal state — which user's modal is open
  const [sigModalUid, setSigModalUid] = useState<string | null>(null);

  // Google Workspace directory (for the invite dropdown). Empty until domain-wide delegation
  // is configured on the API (WORKSPACE_ADMIN_SUBJECT); the free-text email invite works either way.
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);

  // Invite form state
  const [inviteType, setInviteType] = useState<InviteType>("external");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<RoleOption>("sales");
  const [inviting, setInviting] = useState(false);
  const [inviteOk, setInviteOk] = useState<string | null>(null);
  const [inviteErr, setInviteErr] = useState<string | null>(null);

  useEffect(() => {
    const current = getAuth().currentUser;
    setMyEmail(current?.email ?? null);
    load();
    // Load the Workspace directory for the invite dropdown (best-effort).
    apiFetch("/admin/users/directory")
      .then((r) => (r.ok ? r.json() : { users: [] }))
      .then((d: { users?: DirectoryUser[] }) => setDirectory(d.users ?? []))
      .catch(() => setDirectory([]));
  }, []);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch("/admin/users")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((data: FirebaseUser[]) => {
        setUsers(data);
        // Seed pending state with current roles
        const initial: Record<string, RoleOption> = {};
        for (const u of data) {
          initial[u.uid] = (u.role as RoleOption) ?? "";
        }
        setPending(initial);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  async function handleSave(user: FirebaseUser) {
    const newRole = pending[user.uid] ?? "";

    // Synthetic default-admin entries (uid="default:...") have no Firebase record yet.
    // Direct them to use Invite instead.
    if (user.uid.startsWith("default:")) {
      setSaveError((prev) => ({
        ...prev,
        [user.uid]: "This admin has not signed in yet. Use Invite to create their account first.",
      }));
      return;
    }

    // Confirm if changing own role
    if (user.email === myEmail) {
      if (!confirm("You are changing your own role. This will affect your access immediately on next login. Continue?")) {
        return;
      }
    }

    setSaving((s) => ({ ...s, [user.uid]: true }));
    setSaveError((e) => { const n = { ...e }; delete n[user.uid]; return n; });

    try {
      const r = await apiFetch("/admin/users/role", {
        method: "POST",
        body: JSON.stringify({ email: user.email, role: newRole || null }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail ?? `${r.status} ${r.statusText}`);
      }
      const updated: FirebaseUser = await r.json();
      setUsers((prev) =>
        prev.map((u) => (u.uid === updated.uid ? { ...u, role: updated.role } : u))
      );
    } catch (e: unknown) {
      setSaveError((prev) => ({
        ...prev,
        [user.uid]: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setSaving((s) => ({ ...s, [user.uid]: false }));
    }
  }

  function isDirty(user: FirebaseUser): boolean {
    const current = (user.role as RoleOption) ?? "";
    return pending[user.uid] !== current;
  }

  // Adapted to accept the HTML string from the modal
  async function handleSaveSignature(user: FirebaseUser, html: string) {
    setSigSaving((s) => ({ ...s, [user.uid]: true }));
    setSigError((e) => { const n = { ...e }; delete n[user.uid]; return n; });
    try {
      const r = await apiFetch("/admin/users/signature", {
        method: "PUT",
        body: JSON.stringify({ email: user.email, signature: html.trim() || null }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail ?? `${r.status} ${r.statusText}`);
      }
      const updated: { email: string; signature: string | null } = await r.json();
      setUsers((prev) =>
        prev.map((u) => (u.email === updated.email ? { ...u, signature: updated.signature } : u))
      );
      setSigModalUid(null);
    } catch (e: unknown) {
      setSigError((prev) => ({
        ...prev,
        [user.uid]: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setSigSaving((s) => ({ ...s, [user.uid]: false }));
    }
  }

  async function handleInvite() {
    if (!inviteEmail.trim()) { setInviteErr("Email is required."); return; }
    if (!inviteRole) { setInviteErr("Role is required."); return; }
    setInviting(true);
    setInviteErr(null);
    setInviteOk(null);
    try {
      const r = await apiFetch("/admin/users/invite", {
        method: "POST",
        body: JSON.stringify({
          email: inviteEmail.trim(),
          role: inviteRole,
          display_name: inviteName.trim() || undefined,
        }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail ?? `${r.status} ${r.statusText}`);
      }
      const created: FirebaseUser = await r.json();
      setInviteOk(`Invited ${created.email} as ${created.role}.`);
      setInviteEmail("");
      setInviteName("");
      setInviteRole("sales");
      // Refresh user list to show newly invited user
      load();
    } catch (e: unknown) {
      setInviteErr(e instanceof Error ? e.message : String(e));
    } finally {
      setInviting(false);
    }
  }

  async function handleRemove(user: FirebaseUser) {
    if (user.uid.startsWith("default:")) {
      setSaveError((prev) => ({
        ...prev,
        [user.uid]: "Default admins can't be removed here — change the DEFAULT_ADMINS env.",
      }));
      return;
    }
    if (!confirm(`Remove ${user.email}? This deletes their account and signs them out.`)) return;

    setRemoving((s) => ({ ...s, [user.uid]: true }));
    setSaveError((e) => { const n = { ...e }; delete n[user.uid]; return n; });
    try {
      const r = await apiFetch("/admin/users", {
        method: "DELETE",
        body: JSON.stringify({ email: user.email }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail ?? `${r.status} ${r.statusText}`);
      }
      setUsers((prev) => prev.filter((u) => u.uid !== user.uid));
    } catch (e: unknown) {
      setSaveError((prev) => ({
        ...prev,
        [user.uid]: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setRemoving((s) => ({ ...s, [user.uid]: false }));
    }
  }

  // When an Internal directory user is selected, autofill their name.
  function onInternalSelect(email: string) {
    setInviteEmail(email);
    const match = directory.find((d) => d.email.toLowerCase() === email.trim().toLowerCase());
    if (match?.display_name) setInviteName(match.display_name);
  }

  // When the external free-text email changes, still try to autofill name if it matches directory.
  function onInviteEmailChange(email: string) {
    setInviteEmail(email);
    const match = directory.find((d) => d.email.toLowerCase() === email.trim().toLowerCase());
    if (match?.display_name) setInviteName(match.display_name);
  }

  const selectStyle = {
    padding: "6px 10px",
    border: `1px solid ${BRAND.border}`,
    borderRadius: 6,
    fontSize: 13,
    background: "#fff",
    cursor: "pointer",
  };

  const sigModalUser = sigModalUid ? users.find((u) => u.uid === sigModalUid) ?? null : null;

  return (
    <main style={{ maxWidth: 900 }}>
      <PageTitle
        right={
          <Button variant="ghost" onClick={load} disabled={loading} style={{ fontSize: 13 }}>
            Refresh
          </Button>
        }
      >
        User Management
      </PageTitle>

      {/* Invite form */}
      <Card style={{ marginBottom: 20 }}>
        <h3 style={{ margin: "0 0 4px", fontSize: 15, color: BRAND.navyText, fontWeight: 700 }}>
          Invite user
        </h3>
        <p style={{ margin: "0 0 14px", fontSize: 13, color: BRAND.sub }}>
          Pre-authorize an email address before first sign-in, then assign a role.
        </p>

        <div style={{
          display: "grid",
          gridTemplateColumns: "auto minmax(200px, 1.3fr) minmax(150px, 1fr) auto auto",
          gap: 12,
          alignItems: "end",
        }}>
          {/* User type segmented toggle */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>User type</label>
            <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: `1px solid ${BRAND.border}` }}>
              {(["external", "internal"] as InviteType[]).map((type) => (
                <button
                  key={type}
                  onClick={() => {
                    setInviteType(type);
                    setInviteEmail("");
                    setInviteName("");
                  }}
                  style={{
                    flex: 1,
                    padding: "6px 14px",
                    fontSize: 13,
                    fontWeight: 600,
                    border: "none",
                    borderRight: type === "external" ? `1px solid ${BRAND.border}` : "none",
                    cursor: "pointer",
                    background: inviteType === type ? BRAND.navy : "#fff",
                    color: inviteType === type ? "#fff" : BRAND.sub,
                    transition: "background 0.1s, color 0.1s",
                    textTransform: "capitalize",
                  }}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          {/* Email input — switches based on user type */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>Email *</label>
            {inviteType === "external" ? (
              <input
                type="email"
                value={inviteEmail}
                onChange={(e) => onInviteEmailChange(e.target.value)}
                placeholder="user@example.com"
                style={{ ...inputStyle, width: "100%", padding: "7px 10px", fontSize: 13 }}
              />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <select
                  value={inviteEmail}
                  onChange={(e) => onInternalSelect(e.target.value)}
                  style={{ ...selectStyle, width: "100%", padding: "7px 10px" }}
                  disabled={directory.length === 0}
                >
                  <option value="">— select Workspace user —</option>
                  {directory.map((d) => (
                    <option key={d.email} value={d.email}>
                      {d.display_name ? `${d.display_name} (${d.email})` : d.email}
                    </option>
                  ))}
                </select>
                {directory.length === 0 && (
                  <span style={{ fontSize: 11, color: BRAND.sub }}>
                    Workspace directory unavailable — use External to enter an email.
                  </span>
                )}
              </div>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>Name (optional)</label>
            <input
              type="text"
              value={inviteName}
              onChange={(e) => setInviteName(e.target.value)}
              placeholder="Full name"
              style={{ ...inputStyle, width: "100%", padding: "7px 10px", fontSize: 13 }}
            />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>Role *</label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as RoleOption)}
              style={{ ...selectStyle, width: "100%" }}
            >
              {INVITE_ROLES.map((r) => (
                <option key={r} value={r}>{r === "web_admin" ? "Web Admin" : r}</option>
              ))}
            </select>
          </div>

          <Button onClick={handleInvite} disabled={inviting} style={{ padding: "7px 18px", fontSize: 13 }}>
            {inviting ? "Inviting…" : "Invite"}
          </Button>
        </div>

        {inviteOk && <p style={{ marginTop: 10, fontSize: 13, color: "#1a7f4b" }}>{inviteOk}</p>}
        {inviteErr && <p style={{ marginTop: 10, fontSize: 13, color: BRAND.red }}>{inviteErr}</p>}
      </Card>

      {loading && <Loading />}
      {error && <ErrorMsg>Error: {error}</ErrorMsg>}

      {!loading && !error && (
        <Card>
          {users.length === 0 ? (
            <p style={{ color: BRAND.sub, fontSize: 14, margin: 0, textAlign: "center" }}>
              No users found.
            </p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${BRAND.border}`, textAlign: "left" }}>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Name / Email</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Current Role</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Assign Role</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Signature</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.uid} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "10px 12px", color: BRAND.ink }}>
                      {u.display_name && (
                        <div style={{ fontWeight: 600, marginBottom: 2 }}>
                          {u.display_name}
                          {u.email === myEmail && (
                            <span style={{ marginLeft: 6, fontSize: 11, color: BRAND.sub, fontWeight: 400 }}>(you)</span>
                          )}
                        </div>
                      )}
                      <div style={{ color: u.display_name ? BRAND.sub : BRAND.ink, fontSize: u.display_name ? 12 : 14 }}>
                        {u.email}
                        {!u.display_name && u.email === myEmail && (
                          <span style={{ marginLeft: 6, fontSize: 11, color: BRAND.sub }}>(you)</span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: "10px 12px" }}>{roleBadge(u.role)}</td>
                    <td style={{ padding: "10px 12px" }}>
                      <select
                        value={pending[u.uid] ?? ""}
                        onChange={(e) =>
                          setPending((p) => ({ ...p, [u.uid]: e.target.value as RoleOption }))
                        }
                        style={selectStyle}
                      >
                        <option value="">none</option>
                        <option value="admin">admin</option>
                        <option value="web_admin">Web Admin</option>
                        <option value="sales">sales</option>
                      </select>
                    </td>

                    {/* Signature cell — pencil icon opens modal */}
                    <td style={{ padding: "10px 12px", minWidth: 120 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        {u.signature ? (
                          <span style={{ fontSize: 12, color: BRAND.sub, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {u.signature.replace(/<[^>]+>/g, "").slice(0, 40) || "(HTML)"}
                          </span>
                        ) : (
                          <span style={{ fontSize: 12, color: BRAND.sub }}>None</span>
                        )}
                        <IconButton
                          title="Edit signature"
                          onClick={() => setSigModalUid(u.uid)}
                          color={BRAND.navyText}
                        >
                          <PencilIcon />
                        </IconButton>
                        {sigError[u.uid] && (
                          <span style={{ color: BRAND.red, fontSize: 11 }}>{sigError[u.uid]}</span>
                        )}
                      </div>
                    </td>

                    {/* Actions cell — Save (disk) + Remove (trash) icon buttons */}
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                        <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
                          <IconButton
                            title="Save role"
                            onClick={() => handleSave(u)}
                            disabled={saving[u.uid] || !isDirty(u)}
                            color={saving[u.uid] ? "#bbb" : BRAND.navyText}
                          >
                            {saving[u.uid] ? (
                              <span style={{ fontSize: 13, fontWeight: 600, color: BRAND.sub }}>…</span>
                            ) : (
                              <SaveIcon />
                            )}
                          </IconButton>
                          {!u.uid.startsWith("default:") && u.email !== myEmail && (
                            <IconButton
                              title="Remove user"
                              onClick={() => handleRemove(u)}
                              disabled={removing[u.uid]}
                              color={removing[u.uid] ? "#bbb" : BRAND.red}
                            >
                              {removing[u.uid] ? (
                                <span style={{ fontSize: 13, fontWeight: 600, color: BRAND.sub }}>…</span>
                              ) : (
                                <TrashIcon />
                              )}
                            </IconButton>
                          )}
                        </div>
                        {saveError[u.uid] && (
                          <span style={{ color: BRAND.red, fontSize: 12 }}>{saveError[u.uid]}</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {/* Signature modal */}
      {sigModalUser && (
        <SignatureModal
          user={sigModalUser}
          allUsers={users}
          initialHtml={sigModalUser.signature ?? ""}
          saving={sigSaving[sigModalUser.uid] ?? false}
          error={sigError[sigModalUser.uid]}
          onSave={(html) => handleSaveSignature(sigModalUser, html)}
          onClose={() => {
            setSigModalUid(null);
            setSigError((e) => { const n = { ...e }; delete n[sigModalUser.uid]; return n; });
          }}
        />
      )}
    </main>
  );
}
