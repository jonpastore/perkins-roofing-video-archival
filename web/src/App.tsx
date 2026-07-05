import { useState, useEffect, type ReactNode } from "react";
import type { User } from "firebase/auth";
import { signIn, signOutUser, getRole, onAuthChanged } from "./auth";
import { Archive } from "./pages/Archive";
import { SearchAsk } from "./pages/SearchAsk";
import { Templates } from "./pages/Templates";
import { ComposeEmail } from "./pages/ComposeEmail";
import { VideoApproval } from "./pages/VideoApproval";
import { Status } from "./pages/Status";
import { BRAND, FONT } from "./ui";

type Role = "admin" | "sales" | null;

// Placeholder page components — Articles + Scheduling filled in next
function ArticlesPage() { return <main><h2>Articles</h2></main>; }
function SchedulingPage() { return <main><h2>Scheduling</h2></main>; }

// Shared console shell: branded sidebar + content area. Both the admin and sales
// consoles are the same layout with different tabs, so they share this one component.
function Shell({
  title,
  tabs,
  render,
}: {
  title: string;
  tabs: [string, string][];
  render: (tab: string) => ReactNode;
}) {
  const [tab, setTab] = useState<string>(tabs[0][0]);
  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: FONT }}>
      <nav
        style={{
          width: 220,
          background: BRAND.navy,
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          padding: "18px 0",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "0 16px 18px",
            marginBottom: 10,
            borderBottom: "1px solid rgba(255,255,255,0.12)",
          }}
        >
          <img
            src="/perkins-logo.png"
            alt="Perkins Roofing"
            style={{ height: 36, background: "#fff", borderRadius: 6, padding: "3px 5px" }}
          />
          <span style={{ fontWeight: 700, fontSize: 13, lineHeight: 1.2 }}>{title}</span>
        </div>
        {tabs.map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "11px 16px",
              background: tab === id ? BRAND.navyActive : "transparent",
              color: tab === id ? "#fff" : "#c3c9d9",
              borderLeft: tab === id ? `3px solid ${BRAND.red}` : "3px solid transparent",
              cursor: "pointer",
              fontSize: 14,
              fontWeight: tab === id ? 600 : 400,
            }}
          >
            {label}
          </button>
        ))}
        <div style={{ marginTop: "auto", padding: "18px 16px 0" }}>
          <button
            onClick={signOutUser}
            style={{ background: "none", border: "none", color: "#9aa3ba", cursor: "pointer", fontSize: 13 }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <div style={{ flex: 1, padding: 32, overflowY: "auto", background: "#f7f8fa" }}>
        {render(tab)}
      </div>
    </div>
  );
}

function AdminShell() {
  return (
    <Shell
      title="Perkins Admin"
      tabs={[
        ["search-ask", "Search / Ask"],
        ["templates", "Templates"],
        ["articles", "Articles"],
        ["scheduling", "Scheduling"],
        ["video-approval", "Video Approval"],
        ["archive", "Archive"],
        ["config", "Status"],
      ]}
      render={(tab) => (
        <>
          {tab === "search-ask" && <SearchAsk />}
          {tab === "templates" && <Templates />}
          {tab === "articles" && <ArticlesPage />}
          {tab === "scheduling" && <SchedulingPage />}
          {tab === "video-approval" && <VideoApproval />}
          {tab === "archive" && <Archive />}
          {tab === "config" && <Status />}
        </>
      )}
    />
  );
}

function SalesShell() {
  return (
    <Shell
      title="Perkins Sales"
      tabs={[
        ["search-ask", "Search / Ask"],
        ["compose-email", "Compose Email"],
        ["archive", "Archive"],
      ]}
      render={(tab) => (
        <>
          {tab === "search-ask" && <SearchAsk />}
          {tab === "compose-email" && <ComposeEmail />}
          {tab === "archive" && <Archive />}
        </>
      )}
    />
  );
}

// Centered branded card used by the login + no-role screens
function CenterCard({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        fontFamily: FONT,
        background: `linear-gradient(160deg, #f7f8fa 0%, #eef1f6 100%)`,
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 14,
          padding: "44px 40px",
          boxShadow: "0 8px 30px rgba(27,42,82,0.12)",
          textAlign: "center",
          minWidth: 340,
          borderTop: `4px solid ${BRAND.red}`,
        }}
      >
        {children}
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
    <CenterCard>
      <img
        src="/perkins-logo.png"
        alt="Perkins Roofing"
        style={{ height: 60, marginBottom: 20 }}
      />
      <p style={{ margin: "0 0 28px", color: BRAND.navyText, fontSize: 15, fontWeight: 600 }}>
        Video Content Console
      </p>
      <button
        onClick={handleSignIn}
        disabled={loading}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 10,
          padding: "13px 28px",
          background: loading ? "#ccc" : BRAND.red,
          color: "#fff",
          border: "none",
          borderRadius: 8,
          cursor: loading ? "not-allowed" : "pointer",
          fontSize: 15,
          fontWeight: 600,
          boxShadow: loading ? "none" : "0 2px 8px rgba(239,60,26,0.35)",
        }}
        onMouseOver={(e) => { if (!loading) e.currentTarget.style.background = BRAND.redDark; }}
        onMouseOut={(e) => { if (!loading) e.currentTarget.style.background = BRAND.red; }}
      >
        {loading ? "Signing in…" : "Sign in with Google"}
      </button>
      {error && <p style={{ marginTop: 16, color: BRAND.red, fontSize: 13 }}>{error}</p>}
    </CenterCard>
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
          fontFamily: FONT,
          color: BRAND.navyText,
        }}
      >
        Loading…
      </div>
    );
  }

  if (!user) return <LoginScreen />;
  if (role === "admin") return <AdminShell />;
  if (role === "sales") return <SalesShell />;

  // Signed in but no recognized role
  return (
    <CenterCard>
      <img src="/perkins-logo.png" alt="Perkins Roofing" style={{ height: 52, marginBottom: 18 }} />
      <p style={{ margin: "0 0 6px", color: BRAND.navyText, fontWeight: 600, fontSize: 16 }}>
        Access pending
      </p>
      <p style={{ margin: "0 0 22px", color: "#667085", fontSize: 14, maxWidth: 300 }}>
        Your account doesn’t have an assigned role yet. Contact your administrator.
      </p>
      <button
        onClick={signOutUser}
        style={{
          padding: "10px 22px",
          cursor: "pointer",
          background: "#fff",
          color: BRAND.navyText,
          border: `1px solid ${BRAND.navyText}`,
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
        }}
      >
        Sign out
      </button>
    </CenterCard>
  );
}
