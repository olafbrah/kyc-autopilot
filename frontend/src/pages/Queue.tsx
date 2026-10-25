import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { can, useMe } from "../App";
import type { Me, Row, Stats } from "../types";
import { REASON_LABEL, StatusBadge, ScreeningBadge, Stat, ago, pct } from "../ui";

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
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [list, s] = await Promise.all([
      api<{ items: Row[]; counts: Record<string, number>; qa_pending: number; total: number }>(`/api/applications?tab=${tab}`),
      api<Stats>("/api/agent/stats"),
    ]);
    setItems(list.items);
    setTotal(list.total);
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
      <div className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="lede">The agent clears applicants that pass screening. Everything it isn't sure about lands here.</p>
        </div>
      {can(me, "agent:admin") && (
        <button className="primary" onClick={simulate} disabled={busy}>
          {busy ? "Sending…" : "Simulate 20 new applicants"}
        </button>
      )}
      </div>
      <section className="stats">
        <Stat label="Auto-cleared by agent" value={pct(stats?.auto_clear_rate)} hint={`${stats?.auto_cleared ?? 0} of ${stats?.auto_mode_reviews ?? 0} reviewed`} />
        <Stat label="In the human queue" value={human} hint={`${counts.needs_review ?? 0} unclaimed`} />
        <Stat label="Waiting for agent" value={counts.new ?? 0} hint={`${stats?.reviews_last_5m ?? 0} reviewed in last 5 min`} />
        <Stat
          label="Median time to decision"
          value={stats?.median_minutes_to_decision.auto != null ? `${stats.median_minutes_to_decision.auto} min` : "–"}
          hint={`humans: ${stats?.median_minutes_to_decision.human != null ? stats.median_minutes_to_decision.human + " min" : "–"}`}
        />
      </section>

      <div className="panel">
        <div className="panel-head">
          <h2>Applications</h2>
          <span className="live"><i className="dot dot-green" />Live</span>
        </div>
        <div className="tabs">
          {TABS.map((t) => (
            <button key={t.key} className={t.key === tab ? "tab active" : "tab"} onClick={() => setParams({ tab: t.key })}>
              {t.label}
              {t.count && <span className="count">{t.count(counts, qaPending)}</span>}
            </button>
          ))}
        </div>
        <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Applicant</th>
              <th>Nationality</th>
              <th>Screening</th>
              <th>Status</th>
              <th>Agent</th>
              <th>Assignee</th>
              <th>Received</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">Nothing here.</td>
              </tr>
            )}
            {items.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link className="name" to={`/applications/${r.id}`}>{r.full_name}</Link>
                  <div className="sub">{r.external_id}</div>
                </td>
                <td>{r.nationality}</td>
                <td><ScreeningBadge tier={r.risk_tier} /></td>
                <td>
                  <StatusBadge status={r.status} />
                  {r.qa_status && <div className="sub">QA {r.qa_status}</div>}
                </td>
                <td className="soft">
                  {!r.ai ? (
                    "–"
                  ) : r.ai.recommendation === "approve" ? (
                    <>Approve · {pct(r.ai.confidence)}</>
                  ) : (
                    <>Escalated · {REASON_LABEL[r.ai.escalation_reason ?? "other"] ?? r.ai.escalation_reason}</>
                  )}
                </td>
                <td className="soft">{r.assignee ?? "–"}</td>
                <td className="soft">{ago(r.received_at)}</td>
                <td>{action(r, me)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        <div className="panel-foot">
          Showing {items.length} of {total} results
        </div>
      </div>
    </>
  );
}

function action(r: Row, me: Me) {
  const label =
    r.status === "needs_review" ? "Review case"
    : r.status === "pending_approval" && can(me, "kyc:approve") && r.proposed_by !== me.sub ? "Approve"
    : r.status === "in_review" && r.assignee === me.sub ? "Continue"
    : r.qa_status === "pending" && can(me, "kyc:qa") ? "QA check"
    : null;
  return label ? <Link className="btn-outline" to={`/applications/${r.id}`}>{label}</Link> : <span className="none">No action needed</span>;
}
