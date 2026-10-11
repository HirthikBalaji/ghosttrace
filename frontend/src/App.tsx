import { useEffect, useState } from "react";
import { CommandCenter } from "./pages/CommandCenter";
import { StoryPage } from "./pages/Story";
import { InvestigationPage } from "./pages/Investigation";
import { HypothesesPage } from "./pages/Hypotheses";
import { ContainmentPage } from "./pages/Containment";
import { CertificatePage } from "./pages/Certificate";
import { BrainPage } from "./pages/Brain";
import { MemoryAuditPage } from "./pages/MemoryAudit";
import { api } from "./api";
import { authMode, signOut } from "./auth";

export interface Me { subject: string; roles: string[]; auth_mode: string; warning: string | null }

export type Route = "command" | "story" | "investigation" | "hypotheses" | "containment" | "certificate" | "brain" | "memory";
const NAV: { id: Route; label: string; icon: string; needsInv?: boolean }[] = [
  { id: "command", label: "Command center", icon: "◉" },
  { id: "story", label: "Story mode", icon: "▶", needsInv: true },
  { id: "investigation", label: "Investigation", icon: "⌘", needsInv: true },
  { id: "hypotheses", label: "Hypotheses", icon: "⚖", needsInv: true },
  { id: "containment", label: "Containment", icon: "⛨", needsInv: true },
  { id: "certificate", label: "Certificates", icon: "✔", needsInv: true },
  { id: "brain", label: "Company Brain", icon: "❖" },
  { id: "memory", label: "Memory & audit", icon: "☰" },
];

function readHash(): { route: Route; inv: string | null; cert: string | null } {
  const [r, inv, cert] = window.location.hash.replace(/^#\/?/, "").split("/");
  const route = (NAV.find((n) => n.id === r)?.id ?? "command") as Route;
  return { route, inv: inv || null, cert: cert || null };
}

export default function App() {
  const [loc, setLoc] = useState(readHash());
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => { api.get<Me>("/api/v1/whoami").then(setMe).catch(() => setMe(null)); }, []);
  useEffect(() => {
    const on = () => setLoc(readHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    try {
      if (loc.inv) localStorage.setItem("gt.inv", loc.inv);
    } catch { /* storage unavailable: fine */ }
  }, [loc.inv]);
  let inv = loc.inv;
  if (!inv) {
    try { inv = localStorage.getItem("gt.inv"); } catch { inv = null; }
  }
  const go = (route: Route, invId?: string | null, cert?: string | null) => {
    const parts = [route, invId ?? inv ?? "", cert ?? ""].filter((x, i) => i === 0 || x);
    window.location.hash = "/" + parts.join("/");
  };
  useEffect(() => {
    const t = NAV.find((n) => n.id === loc.route)?.label ?? "";
    document.title = `${t} — GHOSTTRACE (synthetic demo)`;
    document.getElementById("main")?.focus();
  }, [loc.route]);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <div className="banner" role="note">
        {authMode === "oidc"
          ? "Every containment action is a simulation or a recorded human approval — nothing is executed by this system."
          : "SYNTHETIC DEMO — all data is synthetic and every containment action is a simulation. Demo-only authentication."}
      </div>
      <div className="shell">
        <nav className="nav" aria-label="Primary">
          <div className="brand">
            <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="13" fill="none" stroke="var(--accent)" strokeWidth="3" strokeDasharray="5 3" /><circle cx="16" cy="16" r="4" fill="var(--accent)" /></svg>
            <div><b>GHOSTTRACE</b><small>open-world containment</small></div>
          </div>
          {NAV.map((n) => (
            <button key={n.id} aria-current={loc.route === n.id ? "page" : undefined} disabled={n.needsInv && !inv}
              title={n.needsInv && !inv ? "Start an investigation first" : undefined} onClick={() => go(n.id)}>
              <span aria-hidden="true">{n.icon}</span>{n.label}
            </button>
          ))}
          <div className="spacer" />
          <div className="meta">
            Workspace <code>demo</code><br />Investigation <code>{inv ?? "—"}</code><br />
            {me && <>Signed in as <code>{me.subject}</code><br />Roles: {me.roles.join(", ") || "none"}<br /></>}
            {authMode === "oidc" && <button className="btn sm" style={{ marginTop: 6 }} onClick={() => signOut()}>Sign out</button>}
          </div>
        </nav>
        <main id="main" tabIndex={-1}>
          {loc.route === "command" && <CommandCenter onOpen={(id) => go("investigation", id)} />}
          {loc.route === "story" && inv && <StoryPage invId={inv} go={go} />}
          {loc.route === "investigation" && inv && <InvestigationPage invId={inv} go={go} />}
          {loc.route === "hypotheses" && inv && <HypothesesPage invId={inv} />}
          {loc.route === "containment" && inv && <ContainmentPage invId={inv} go={go} me={me} />}
          {loc.route === "certificate" && inv && <CertificatePage invId={inv} certId={loc.cert} go={go} />}
          {loc.route === "brain" && <BrainPage />}
          {loc.route === "memory" && <MemoryAuditPage invId={inv} />}
          {!inv && NAV.find((n) => n.id === loc.route)?.needsInv && <div className="state">No investigation selected. Start one from the command center.</div>}
        </main>
      </div>
    </>
  );
}
