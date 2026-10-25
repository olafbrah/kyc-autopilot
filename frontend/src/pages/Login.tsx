import { useEffect, useState } from "react";
import { api } from "../api";
import type { Me } from "../types";

type Persona = { sub: string; name: string; roles: string[] };

const BLURB: Record<string, string> = {
  analyst: "Works the human queue: claims cases and proposes decisions.",
  lead: "Approves proposals (four-eyes), QA-checks auto-clears, controls the agent.",
};

export default function Login({ onLogin }: { onLogin: (m: Me) => void }) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Persona[]>("/api/auth/personas").then(setPersonas).catch(() => setError("Dev sign-in is disabled; use SSO."));
  }, []);
  const login = async (sub: string) => {
    await api("/api/auth/login", { body: { sub } });
    onLogin(await api<Me>("/api/me"));
  };
  return (
    <div className="login">
      <h1>KYC Review</h1>
      <p className="muted">Development sign-in. In production this is your company SSO (Entra ID / Okta).</p>
      {error && <div className="error">{error}</div>}
      <div className="personas">
        {personas.map((p) => (
          <button key={p.sub} className="persona" onClick={() => login(p.sub)}>
            <div className="persona-name">{p.name}</div>
            <div className="persona-role">{p.roles.join(", ") || "no KYC role"}</div>
            <div className="muted small">{p.roles.map((r) => BLURB[r]).filter(Boolean).join(" ") || "Can sign in but sees nothing (shows access control)."}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
