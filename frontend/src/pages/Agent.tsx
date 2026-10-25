import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { can, useMe } from "../App";
import type { AgentSettings, Row, Stats } from "../types";
import { REASON_LABEL, Stat, blockerLabel, pct } from "../ui";

function Bars({ data, label }: { data: [string, number][]; label: (k: string) => string }) {
  const max = Math.max(1, ...data.map(([, n]) => n));
  if (!data.length) return <p className="muted small">None yet.</p>;
  return (
    <div className="bars">
      {data.map(([k, n]) => (
        <div key={k} className="bar-row">
          <span className="bar-label">{label(k)}</span>
          <span className="bar"><span style={{ width: `${(n / max) * 100}%` }} /></span>
          <span className="bar-n">{n}</span>
        </div>
      ))}
    </div>
  );
}

export default function Agent() {
  const me = useMe();
  const admin = can(me, "agent:admin");
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [draft, setDraft] = useState<{ threshold: number; qa_rate: number } | null>(null);
  const [qa, setQa] = useState<Row[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [s, st, q] = await Promise.all([
      api<Stats>("/api/agent/stats"),
      api<AgentSettings>("/api/agent/settings"),
      api<{ items: Row[] }>("/api/applications?tab=qa"),
    ]);
    setStats(s);
    setSettings(st);
    setDraft((d) => d ?? { threshold: st.threshold, qa_rate: st.qa_rate });
    setQa(q.items);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const save = async (body: Partial<AgentSettings>) => {
    setError("");
    try {
      setSettings(await api<AgentSettings>("/api/agent/settings", { method: "PUT", body }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!stats || !settings || !draft) return <div className="loading">Loading…</div>;
  return (
    <>
      <div className="title-row">
        <h1>Agent</h1>
        <span className={`mode mode-${settings.mode}`}>
          {settings.mode === "auto" ? "Auto-clearing" : settings.mode === "shadow" ? "Shadow mode" : "Off"}
        </span>
        {settings.updated_by && <span className="muted small">last changed by {settings.updated_by}</span>}
      </div>
      {error && <div className="error">{error}</div>}

      <section className="stats">
        <Stat label="Auto-clear rate" value={pct(stats.auto_clear_rate)} hint={`${stats.auto_cleared} of ${stats.auto_mode_reviews} in auto mode`} />
        <Stat label="Reviewed, last hour" value={stats.reviews_last_60m} hint={`${stats.reviews_last_5m} in last 5 min`} />
        <Stat label="Avg model latency" value={stats.avg_latency_ms != null ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s` : "–"} />
        <Stat label="Model spend" value={`$${stats.cost_usd.toFixed(2)}`} hint={stats.agent_versions.map(([v, n]) => `${v}: ${n}`).join(", ")} />
        <Stat label="QA sample" value={`${stats.qa.pending ?? 0} pending`} hint={`${stats.qa.confirmed ?? 0} confirmed · ${stats.qa.reopened ?? 0} reopened`} />
      </section>

      <div className="grid">
        <div className="col">
          <section className="card">
            <h2>Why cases went to humans</h2>
            <Bars data={stats.blockers} label={blockerLabel} />
          </section>
          <section className="card">
            <h2>Agent escalation reasons</h2>
            <Bars data={stats.escalation_reasons} label={(k) => REASON_LABEL[k] ?? k} />
          </section>
        </div>
        <div className="col">
          <section className="card">
            <h2>Controls</h2>
            <p className="small muted">
              The agent can only clear a case when every automated check is clear, the risk tier is low, it recommends approve
              with confidence at or above the threshold, and no instructions are found in applicant text. This rule is enforced
              by the API, not the model.
            </p>
            <div className="control">
              <label>Mode</label>
              <div className="seg">
                {(["auto", "shadow", "off"] as const).map((m) => (
                  <button key={m} disabled={!admin} className={settings.mode === m ? "active" : ""} onClick={() => save({ mode: m })}>
                    {m === "auto" ? "Auto" : m === "shadow" ? "Shadow (recommend only)" : "Off"}
                  </button>
                ))}
              </div>
            </div>
            <div className="control">
              <label>Confidence threshold: {draft.threshold.toFixed(2)}</label>
              <input type="range" min={0.5} max={1} step={0.01} disabled={!admin} value={draft.threshold}
                onChange={(e) => setDraft({ ...draft, threshold: Number(e.target.value) })} />
            </div>
            <div className="control">
              <label>QA sample rate: {pct(draft.qa_rate)}</label>
              <input type="range" min={0} max={0.5} step={0.01} disabled={!admin} value={draft.qa_rate}
                onChange={(e) => setDraft({ ...draft, qa_rate: Number(e.target.value) })} />
            </div>
            {admin ? (
              <div className="actions">
                <button className="primary" onClick={() => save(draft)}
                  disabled={draft.threshold === settings.threshold && draft.qa_rate === settings.qa_rate}>Save</button>
                <button className="danger" onClick={() => save({ mode: "off" })} disabled={settings.mode === "off"}>
                  Kill switch: send everything to humans
                </button>
              </div>
            ) : (
              <p className="muted small">Only leads can change these.</p>
            )}
          </section>
          <section className="card">
            <h2>QA sample of auto-clears</h2>
            {qa.length === 0 ? <p className="muted small">No sampled cases yet.</p> : (
              <table className="table compact">
                <tbody>
                  {qa.map((r) => (
                    <tr key={r.id}>
                      <td><Link to={`/applications/${r.id}`}>{r.full_name}</Link></td>
                      <td className="small">{r.qa_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
