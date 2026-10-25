import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "./api";
import type { Me } from "./types";
import Login from "./pages/Login";
import Queue from "./pages/Queue";
import Application from "./pages/Application";
import Agent from "./pages/Agent";
import Evals from "./pages/Evals";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext)!;
export const can = (me: Me, perm: string) => me.permissions.includes(perm);

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    api<Me>("/api/me")
      .then(setMe)
      .catch((e) => (e instanceof ApiError && (e.status === 401 || e.status === 403) ? setMe(null) : setMe(null)));
  }, [location.pathname === "/login"]);

  if (me === undefined) return <div className="loading">Loading…</div>;
  if (me === null && location.pathname !== "/login") return <Navigate to="/login" replace />;
  if (me === null) return <Login onLogin={(m) => { setMe(m); navigate("/queue"); }} />;

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" });
    setMe(null);
    navigate("/login");
  };

  const initials = me.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <MeContext.Provider value={me}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">K</span>
            <div>
              <div className="brand-name">KYC Review</div>
              <div className="brand-sub">Autopilot</div>
            </div>
          </div>
          <nav className="side-nav">
            <NavLink to="/queue">Queue <Icon d={ICONS.queue} /></NavLink>
            <NavLink to="/agent">Agent <Icon d={ICONS.agent} /></NavLink>
            <NavLink to="/evals">Evals <Icon d={ICONS.evals} /></NavLink>
          </nav>
          <div className="side-section">Status</div>
          <div className="side-legend">
            <span><i className="dot dot-green" />Auto-cleared</span>
            <span><i className="dot dot-amber" />Needs a human</span>
            <span><i className="dot dot-blue" />Awaiting approval</span>
          </div>
          <div className="side-user">
            <span className="avatar">{initials}</span>
            <div className="side-user-text">
              <div className="side-user-name">{me.name}</div>
              <div className="side-user-role">{me.roles.join(", ") || "no role"}</div>
            </div>
            <button className="icon-btn" title="Sign out" onClick={logout}><Icon d={ICONS.logout} /></button>
          </div>
        </aside>
        <main>
          {me.permissions.includes("kyc:read") ? (
            <Routes>
              <Route path="/queue" element={<Queue />} />
              <Route path="/applications/:id" element={<Application />} />
              <Route path="/agent" element={<Agent />} />
              <Route path="/evals" element={<Evals />} />
              <Route path="/evals/:version" element={<Evals />} />
              <Route path="*" element={<Navigate to="/queue" replace />} />
            </Routes>
          ) : (
            <div className="card empty">You are signed in as {me.name} but have no KYC role. Ask a lead for access.</div>
          )}
        </main>
      </div>
    </MeContext.Provider>
  );
}

const ICONS = {
  queue: "M4 6h16M4 12h16M4 18h10",
  agent: "M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9zM18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z",
  evals: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  logout: "M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3M10 16l4-4-4-4M14 12H4",
};

function Icon({ d }: { d: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}
