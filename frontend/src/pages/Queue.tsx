import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { can, useMe } from "../App";
import type { Row, Stats } from "../types";
import { REASON_LABEL, StatusBadge, TierBadge, Stat, ago, pct } from "../ui";

const TABS: { key: string; label: string; count?: (c: Record<string, number>, qa: number) => number }[] = [
  { key: "needs_review", label: "Needs review", count: (c) => c.needs_review ?? 0 },
  { key: "mine", label: "Mine" },
  { key: "pending_approval", label: "Awaiting approval", count: (c) => c.pending_approval ?? 0 },
  { key: "agent", label: "With agent", count: (c) => c.new ?? 0 },
  { key: "auto_cleared", label: "Auto-cleared", count: (c) => c.auto_cleared ?? 0 },
  { key: "qa", label: "QA sample", count: (_, qa) => qa },
  { key: "decided", label: "Decided by humans", count: (c) => (c.approved ?? 0) + (c.rejected ?? 0) },
];

export default function Queue() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "needs_review";
  const [items, setItems] = useState<Row[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [qaPending, setQaPending] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [list, s] = await Promise.all([
      api<{ items: Row[]; counts: Record<string, number>; qa_pending: number }>(`/api/applications?tab=${tab}`),
      api<Stats>("/api/agent/stats"),
    ]);
    setItems(list.items);
    setCounts(list.counts);
    setQaPending(list.qa_pending);
    setStats(s);
  }, [tab]);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const simulate = async () => {
    setBusy(true);
    try {
      await api("/api/simulate?n=20", { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const human = (counts.needs_review ?? 0) + (counts.in_review ?? 0) + (counts.pending_approval ?? 0);
  return (
    <>
      <section className="stats">
        <Stat label="Auto-cleared by agent" value={pct(stats?.auto_clear_rate)} hint={`${stats?.auto_cleared ?? 0} of ${stats?.auto_mode_reviews ?? 0} reviewed`} />
        <Stat label="In the human queue" value={human} hint={`${counts.needs_review ?? 0} unclaimed`} />
        <Stat label="Waiting for agent" value={counts.new ?? 0} hint={`${stats?.reviews_last_5m ?? 0} reviewed in last 5 min`} />
        <Stat
          label="Median time to decision"
          value={stats?.median_minutes_to_decision.auto != null ? `${stats.median_minutes_to_decision.auto} min` : "–"}
          hint={`humans: ${stats?.median_minutes_to_decision.human != null ? stats.median_minutes_to_decision.human + " min" : "–"}`}
        />
        {can(me, "agent:admin") && (
          <button className="primary" onClick={simulate} disabled={busy}>
            {busy ? "Sending…" : "Simulate 20 new applicants"}
          </button>
        )}
      </section>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={t.key === tab ? "tab active" : "tab"} onClick={() => setParams({ tab: t.key })}>
            {t.label}
            {t.count && <span className="count">{t.count(counts, qaPending)}</span>}
          </button>
        ))}
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Applicant</th>
            <th>Nationality</th>
            <th>Risk</th>
            <th>Agent</th>
            <th>Status</th>
            <th>Assignee</th>
            <th>Received</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td colSpan={7} className="empty">Nothing here.</td>
            </tr>
          )}
          {items.map((r) => (
            <tr key={r.id}>
              <td>
                <Link to={`/applications/${r.id}`}>{r.full_name}</Link>
                <div className="muted small">{r.external_id}</div>
              </td>
              <td>{r.nationality}</td>
              <td><TierBadge tier={r.risk_tier} /></td>
              <td>
                {!r.ai ? (
                  <span className="muted">–</span>
                ) : r.ai.recommendation === "approve" ? (
                  <span>Approve <span className="muted small">{pct(r.ai.confidence)}</span></span>
                ) : (
                  <span className="escalated">Escalated: {REASON_LABEL[r.ai.escalation_reason ?? "other"] ?? r.ai.escalation_reason}</span>
                )}
              </td>
              <td>
                <StatusBadge status={r.status} />
                {r.qa_status && <span className="muted small"> QA {r.qa_status}</span>}
              </td>
              <td>{r.assignee ?? <span className="muted">–</span>}</td>
              <td className="muted">{ago(r.received_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
