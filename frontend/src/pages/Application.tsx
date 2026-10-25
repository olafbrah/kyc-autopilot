import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useMe } from "../App";
import type { Detail } from "../types";
import { Badge, REASON_LABEL, StatusBadge, TierBadge, blockerLabel, pct } from "../ui";

const CHECK_LABEL: Record<string, string> = {
  sanctions: "Sanctions screening",
  pep: "PEP screening",
  id_document: "ID document",
  identity_match: "Name / DOB match",
  country_risk: "Country risk",
  expected_volume: "Expected volume",
  adverse_media: "Adverse media",
};

const FIELDS: [string, string][] = [
  ["date_of_birth", "Date of birth"],
  ["nationality", "Nationality"],
  ["country_of_residence", "Residence"],
  ["city", "City"],
  ["address", "Address"],
  ["occupation", "Occupation"],
  ["employer", "Employer"],
  ["expected_monthly_volume", "Expected monthly volume"],
  ["source_of_funds", "Source of funds"],
  ["account_purpose", "Account purpose"],
  ["notes", "Applicant notes"],
];

const fmt = (v: unknown) =>
  v == null || v === "" ? "–" : typeof v === "number" ? v.toLocaleString() : typeof v === "object" ? JSON.stringify(v) : String(v);

export default function Application() {
  const { id } = useParams();
  const me = useMe();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(() => api<Detail>(`/api/applications/${id}`).then(setD), [id]);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setError("");
    try {
      await api(`/api/applications/${id}/${path}`, { body });
      setNote("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!d) return <div className="loading">{error || "Loading…"}</div>;
  const a = d.applicant;
  const r = d.ai_review;

  return (
    <>
      <div className="crumbs"><Link to="/queue">← Queue</Link></div>
      <div className="title-row">
        <h1>{d.full_name}</h1>
        <StatusBadge status={d.status} />
        <TierBadge tier={d.risk_tier} />
        <span className="muted">{d.external_id}</span>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="grid">
        <div className="col">
          <section className="card">
            <h2>Applicant</h2>
            <dl className="fields">
              {FIELDS.map(([k, label]) => (
                <div key={k}>
                  <dt>{label}</dt>
                  <dd className={k === "notes" && a.notes ? "untrusted" : ""}>{fmt(a[k])}</dd>
                </div>
              ))}
              <div>
                <dt>ID document</dt>
                <dd>
                  {a.id_document?.type} {a.id_document?.number} · {a.id_document?.issuing_country} · expires {a.id_document?.expiry}
                  <div className="muted small">On document: {a.id_document?.name_on_document}, born {a.id_document?.dob_on_document}</div>
                </dd>
              </div>
            </dl>
            {(a.adverse_media ?? []).length > 0 && (
              <>
                <h3>Media screening hits</h3>
                <ul className="media">
                  {a.adverse_media.map((m: { source: string; headline: string }, i: number) => (
                    <li key={i}><span className="muted small">{m.source}</span> {m.headline}</li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section className="card">
            <h2>Automated checks</h2>
            <table className="table compact">
              <tbody>
                {Object.entries(d.checks).map(([k, c]) => (
                  <tr key={k}>
                    <td>{CHECK_LABEL[k] ?? k}</td>
                    <td><Badge kind={`check-${c.status}`}>{c.status}</Badge></td>
                    <td className="small">{c.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>

        <div className="col">
          <section className={`card ai ${r?.outcome === "auto_cleared" ? "ai-cleared" : r ? "ai-escalated" : ""}`}>
            <h2>Agent review</h2>
            {!r ? (
              <p className="muted">{d.status === "new" ? "Waiting for the agent…" : "No agent review (agent was off)."}</p>
            ) : (
              <>
                <div className="ai-head">
                  <strong>
                    {r.recommendation === "approve" ? "Recommends approve" : `Escalated: ${REASON_LABEL[r.escalation_reason ?? "other"] ?? r.escalation_reason}`}
                  </strong>
                  <span className="muted"> confidence {pct(r.confidence)}</span>
                </div>
                <p>{r.summary}</p>
                {r.reasons.length > 0 && <ul>{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                {r.risk_flags.length > 0 && <p className="small">Risk flags: {r.risk_flags.join(", ")}</p>}
                <div className="decision">
                  {r.outcome === "auto_cleared" ? (
                    <><strong>Auto-cleared.</strong> All checks clear, low risk, confidence at or above the threshold.</>
                  ) : r.outcome === "shadow" ? (
                    <><strong>Shadow mode:</strong> recommendation recorded, a human decides.</>
                  ) : (
                    <>
                      <strong>Why a human is needed:</strong>
                      <ul>{r.blockers.map((b) => <li key={b}>{blockerLabel(b)}</li>)}</ul>
                    </>
                  )}
                </div>
                <div className="muted small">
                  {r.agent_version} · {r.model} · {r.latency_ms} ms · ${r.cost_usd.toFixed(4)} · input {r.input_hash.slice(0, 12)}
                </div>
              </>
            )}
          </section>

          <section className="card">
            <h2>Decision</h2>
            {d.decision && (
              <p>
                <strong>{d.decision}</strong>
                {d.proposed_by && <> proposed by {d.proposed_by}</>}
                {d.approved_by && <>, {d.status === "pending_approval" ? "" : "approved by "}{d.status !== "pending_approval" && d.approved_by}</>}
                {d.decision_note && <span className="muted"> · {d.decision_note}</span>}
              </p>
            )}
            <Actions d={d} me={me.sub} note={note} setNote={setNote} act={act} />
          </section>

          <section className="card">
            <h2>Audit trail</h2>
            <ol className="timeline">
              {d.history.map((e) => (
                <li key={e.id} className={e.outcome !== "success" ? "denied" : ""}>
                  <div>
                    <strong>{e.action.replace("application.", "").replace(/_/g, " ")}</strong>{" "}
                    <span className={e.actor_type === "service" ? "actor-svc" : ""}>{e.actor}</span>
                    {e.outcome !== "success" && <Badge kind="check-fail">{e.outcome}</Badge>}
                    <span className="muted small"> {new Date(e.ts).toLocaleString()}</span>
                  </div>
                  {Object.keys(e.changes).length > 0 && (
                    <div className="small muted">
                      {Object.entries(e.changes).map(([k, [from, to]]) => `${k}: ${fmt(from)} → ${fmt(to)}`).join(" · ")}
                    </div>
                  )}
                  {e.action === "application.ai_review" && (
                    <div className="small muted">
                      {String(e.details.agent_version)} / {String(e.details.model)} · threshold {String(e.details.threshold)} · mode {String(e.details.mode)}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </>
  );
}

function Actions({ d, me, note, setNote, act }: {
  d: Detail; me: string; note: string; setNote: (s: string) => void; act: (p: string, b?: unknown) => Promise<void>;
}) {
  if (d.status === "needs_review" && d.can.work) return <button className="primary" onClick={() => act("claim")}>Claim</button>;
  if (d.status === "in_review" && d.assignee === me)
    return (
      <div className="actions">
        <textarea placeholder="Justification (required)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="primary" disabled={!note.trim()} onClick={() => act("propose", { decision: "approve", note })}>Propose approve</button>
        <button className="danger" disabled={!note.trim()} onClick={() => act("propose", { decision: "reject", note })}>Propose reject</button>
      </div>
    );
  if (d.status === "pending_approval" && d.can.approve)
    return (
      <div className="actions">
        {d.proposed_by === me && <p className="muted small">You proposed this; another lead must approve it (four-eyes).</p>}
        <button className="primary" onClick={() => act("approve")}>Approve {d.decision}</button>
        <textarea placeholder="Reason for sending back" value={note} onChange={(e) => setNote(e.target.value)} />
        <button onClick={() => act("send-back", { note })}>Send back</button>
      </div>
    );
  if (d.status === "auto_cleared" && d.qa_status === "pending" && d.can.qa)
    return (
      <div className="actions">
        <p className="small">This auto-clear was sampled for QA.</p>
        <textarea placeholder="QA note" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="primary" onClick={() => act("qa", { verdict: "confirm", note })}>Confirm</button>
        <button className="danger" onClick={() => act("qa", { verdict: "reopen", note })}>Reopen to human queue</button>
      </div>
    );
  return <p className="muted small">No actions available to you.</p>;
}
