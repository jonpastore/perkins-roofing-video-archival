import { useState, useEffect } from "react";
import type { User } from "firebase/auth";
import { signIn, signOutUser, getRole, onAuthChanged } from "./auth";

type Role = "admin" | "sales" | null;

// Placeholder page components — filled in later waves
function TemplatesPage() { return <main><h2>Templates</h2></main>; }
function ArticlesPage() { return <main><h2>Articles</h2></main>; }
function SchedulingPage() { return <main><h2>Scheduling</h2></main>; }
function VideoApprovalPage() { return <main><h2>Video Approval</h2></main>; }
function ConfigPage() { return <main><h2>Config</h2></main>; }
function SearchAskPage() { return <main><h2>Search / Ask</h2></main>; }
function ComposeEmailPage() { return <main><h2>Compose Email</h2></main>; }

type AdminTab = "templates" | "articles" | "scheduling" | "video-approval" | "config";
type SalesTab = "search-ask" | "compose-email";

function AdminShell() {
  const [tab, setTab] = useState<AdminTab>("templates");
  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "system-ui, sans-serif" }}>
      <nav style={{ width: 200, background: "#1a1a2e", color: "#fff", padding: "24px 0" }}>
        <div style={{ padding: "0 16px 24px", fontWeight: 700, fontSize: 15 }}>
          Perkins Admin
        </div>
        {(
          [
            ["templates", "Templates"],
            ["articles", "Articles"],
            ["scheduling", "Scheduling"],
            ["video-approval", "Video Approval"],
            ["config", "Config"],
          ] as [AdminTab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "10px 16px",
              background: tab === id ? "#16213e" : "transparent",
              color: tab === id ? "#e94560" : "#ccc",
              border: "none",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            {label}
          </button>
        ))}
        <div style={{ marginTop: "auto", padding: "24px 16px 0" }}>
          <button
            onClick={signOutUser}
            style={{ background: "none", border: "none", color: "#888", cursor: "pointer", fontSize: 13 }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <div style={{ flex: 1, padding: 32, overflowY: "auto" }}>
        {tab === "templates" && <TemplatesPage />}
        {tab === "articles" && <ArticlesPage />}
        {tab === "scheduling" && <SchedulingPage />}
        {tab === "video-approval" && <VideoApprovalPage />}
        {tab === "config" && <ConfigPage />}
      </div>
    </div>
  );
}

function SalesShell() {
  const [tab, setTab] = useState<SalesTab>("search-ask");
  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "system-ui, sans-serif" }}>
      <nav style={{ width: 200, background: "#1a1a2e", color: "#fff", padding: "24px 0" }}>
        <div style={{ padding: "0 16px 24px", fontWeight: 700, fontSize: 15 }}>
          Perkins Sales
        </div>
        {(
          [
            ["search-ask", "Search / Ask"],
            ["compose-email", "Compose Email"],
          ] as [SalesTab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "10px 16px",
              background: tab === id ? "#16213e" : "transparent",
              color: tab === id ? "#e94560" : "#ccc",
              border: "none",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            {label}
          </button>
        ))}
        <div style={{ marginTop: "auto", padding: "24px 16px 0" }}>
          <button
            onClick={signOutUser}
            style={{ background: "none", border: "none", color: "#888", cursor: "pointer", fontSize: 13 }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <div style={{ flex: 1, padding: 32, overflowY: "auto" }}>
        {tab === "search-ask" && <SearchAskPage />}
        {tab === "compose-email" && <ComposeEmailPage />}
      </div>
    </div>
  );
}

function LoginScreen() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSignIn() {
    setLoading(true);
    setError(null);
    try {
      await signIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        fontFamily: "system-ui, sans-serif",
        background: "#f5f5f5",
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 12,
          padding: "48px 40px",
          boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
          textAlign: "center",
          minWidth: 320,
        }}
      >
        <h1 style={{ margin: "0 0 8px", fontSize: 22, color: "#1a1a2e" }}>
          Perkins Roofing
        </h1>
        <p style={{ margin: "0 0 32px", color: "#666", fontSize: 14 }}>
          Video Content Console
        </p>
        <button
          onClick={handleSignIn}
          disabled={loading}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 24px",
            background: loading ? "#ccc" : "#1a1a2e",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            cursor: loading ? "not-allowed" : "pointer",
            fontSize: 15,
            fontWeight: 600,
          }}
        >
          {loading ? "Signing in..." : "Sign in with Google"}
        </button>
        {error && (
          <p style={{ marginTop: 16, color: "#e94560", fontSize: 13 }}>{error}</p>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<Role>(null);
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => {
    const unsubscribe = onAuthChanged(async (u) => {
      setUser(u);
      if (u) {
        const r = await getRole();
        setRole(r as Role);
      } else {
        setRole(null);
      }
      setAuthReady(true);
    });
    return unsubscribe;
  }, []);

  if (!authReady) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          fontFamily: "system-ui, sans-serif",
          color: "#666",
        }}
      >
        Loading...
      </div>
    );
  }

  if (!user) return <LoginScreen />;
  if (role === "admin") return <AdminShell />;
  if (role === "sales") return <SalesShell />;

  // Signed in but no recognized role
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        fontFamily: "system-ui, sans-serif",
        color: "#666",
      }}
    >
      <p>Your account does not have an assigned role. Contact your administrator.</p>
      <button
        onClick={signOutUser}
        style={{ marginTop: 16, padding: "8px 20px", cursor: "pointer" }}
      >
        Sign out
      </button>
    </div>
  );
}
