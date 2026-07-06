import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Loading, ErrorMsg, Badge, inputStyle } from "../ui";
import { getAuth } from "firebase/auth";

interface FirebaseUser {
  uid: string;
  email: string;
  display_name: string | null;
  role: string | null;
}

interface DirectoryUser {
  email: string;
  display_name: string | null;
}

type RoleOption = "admin" | "web_admin" | "sales" | "";

function roleBadge(role: string | null) {
  if (role === "admin") return <Badge tone="blue">admin</Badge>;
  if (role === "web_admin") return <Badge tone="amber">web admin</Badge>;
  if (role === "sales") return <Badge tone="green">sales</Badge>;
  return <Badge tone="gray">none</Badge>;
}

const INVITE_ROLES: RoleOption[] = ["admin", "web_admin", "sales"];

export function Users() {
  const [users, setUsers] = useState<FirebaseUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, RoleOption>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});
  const [myEmail, setMyEmail] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Record<string, boolean>>({});

  // Google Workspace directory (for the invite dropdown). Empty until domain-wide delegation
  // is configured on the API (WORKSPACE_ADMIN_SUBJECT); the free-text email invite works either way.
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);

  // Invite form state
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

  // When an invite email matches a directory user, autofill their name.
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
          {directory.length > 0
            ? "Pick a Perkins Workspace user from the dropdown, or type any external email to invite them. Assign a role and send."
            : "Pre-authorize any email address (internal or external) before first sign-in, then assign a role."}
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>
              Email * {directory.length > 0 && <span style={{ fontWeight: 400 }}>(pick or type)</span>}
            </label>
            <input
              type="email"
              list="gsuite-users"
              value={inviteEmail}
              onChange={(e) => onInviteEmailChange(e.target.value)}
              placeholder="user@perkinsroofing.net or external"
              style={{ ...inputStyle, minWidth: 220, padding: "7px 10px", fontSize: 13 }}
            />
            <datalist id="gsuite-users">
              {directory.map((d) => (
                <option key={d.email} value={d.email}>
                  {d.display_name ?? d.email}
                </option>
              ))}
            </datalist>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>Name (optional)</label>
            <input
              type="text"
              value={inviteName}
              onChange={(e) => setInviteName(e.target.value)}
              placeholder="Full name"
              style={{ ...inputStyle, minWidth: 160, padding: "7px 10px", fontSize: 13 }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>Role *</label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as RoleOption)}
              style={selectStyle}
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
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Action</th>
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
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                        <div style={{ display: "flex", gap: 6 }}>
                          <Button
                            onClick={() => handleSave(u)}
                            disabled={saving[u.uid] || !isDirty(u)}
                            style={{ padding: "6px 16px", fontSize: 13 }}
                          >
                            {saving[u.uid] ? "Saving…" : "Save"}
                          </Button>
                          {!u.uid.startsWith("default:") && u.email !== myEmail && (
                            <Button
                              variant="ghost"
                              onClick={() => handleRemove(u)}
                              disabled={removing[u.uid]}
                              style={{ padding: "6px 12px", fontSize: 13, color: BRAND.red }}
                            >
                              {removing[u.uid] ? "Removing…" : "Remove"}
                            </Button>
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
    </main>
  );
}
