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
          Pre-authorize any email address before first sign-in. Org-directory autocomplete
          requires Google Workspace admin consent and is a planned follow-up — use this form
          for now.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <label style={{ fontSize: 12, color: BRAND.sub, fontWeight: 600 }}>Email *</label>
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="user@example.com"
              style={{ ...inputStyle, minWidth: 220, padding: "7px 10px", fontSize: 13 }}
            />
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
                        <Button
                          onClick={() => handleSave(u)}
                          disabled={saving[u.uid] || !isDirty(u)}
                          style={{ padding: "6px 16px", fontSize: 13 }}
                        >
                          {saving[u.uid] ? "Saving…" : "Save"}
                        </Button>
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
