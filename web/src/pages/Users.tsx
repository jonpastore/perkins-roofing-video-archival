import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { BRAND, Card, Button, PageTitle, Loading, ErrorMsg, Badge } from "../ui";
import { getAuth } from "firebase/auth";

interface FirebaseUser {
  uid: string;
  email: string;
  role: string | null;
}

type RoleOption = "admin" | "sales" | "";

function roleBadge(role: string | null) {
  if (role === "admin") return <Badge tone="blue">admin</Badge>;
  if (role === "sales") return <Badge tone="green">sales</Badge>;
  return <Badge tone="gray">none</Badge>;
}

export function Users() {
  const [users, setUsers] = useState<FirebaseUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, RoleOption>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saveError, setSaveError] = useState<Record<string, string>>({});
  const [myEmail, setMyEmail] = useState<string | null>(null);

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
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Email</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Current Role</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Assign Role</th>
                  <th style={{ padding: "8px 12px", color: BRAND.sub, fontWeight: 600 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.uid} style={{ borderBottom: `1px solid ${BRAND.border}` }}>
                    <td style={{ padding: "10px 12px", color: BRAND.ink }}>
                      {u.email}
                      {u.email === myEmail && (
                        <span style={{ marginLeft: 6, fontSize: 11, color: BRAND.sub }}>(you)</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 12px" }}>{roleBadge(u.role)}</td>
                    <td style={{ padding: "10px 12px" }}>
                      <select
                        value={pending[u.uid] ?? ""}
                        onChange={(e) =>
                          setPending((p) => ({ ...p, [u.uid]: e.target.value as RoleOption }))
                        }
                        style={{
                          padding: "6px 10px",
                          border: `1px solid ${BRAND.border}`,
                          borderRadius: 6,
                          fontSize: 13,
                          background: "#fff",
                          cursor: "pointer",
                        }}
                      >
                        <option value="">none</option>
                        <option value="admin">admin</option>
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
