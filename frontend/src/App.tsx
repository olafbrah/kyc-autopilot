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

  return (
    <MeContext.Provider value={me}>
      <header className="topbar">
        <div className="brand">KYC Review <span className="brand-sub">with Autopilot</span></div>
        <nav>
          <NavLink to="/queue">Queue</NavLink>
          <NavLink to="/agent">Agent</NavLink>
          <NavLink to="/evals">Evals</NavLink>
        </nav>
        <div className="whoami">
          <span>{me.name}</span>
          <span className="roles">{me.roles.join(", ") || "no role"}</span>
          <button className="link" onClick={logout}>Sign out</button>
        </div>
      </header>
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
    </MeContext.Provider>
  );
}
