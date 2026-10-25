import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { EvalCase, EvalRun } from "../types";
import { REASON_LABEL, pct } from "../ui";

export default function Evals() {
  const { version } = useParams();
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [detail, setDetail] = useState<(EvalRun & { cases: EvalCase[] }) | null>(null);

  useEffect(() => {
    api<EvalRun[]>("/api/evals").then(setRuns);
  }, []);
  useEffect(() => {
    setDetail(null);
    if (version) api<EvalRun & { cases: EvalCase[] }>(`/api/evals/${version}`).then(setDetail);
  }, [version]);

  return (
    <>
      <h1>Agent evals</h1>
      <p className="muted">
        300 synthetic applicants with known correct outcomes (200 dev for iterating, 100 holdout never tuned on). Each run scores the
        whole pipeline: checks + model + the auto-clear rule. A false clear is a case that should have gone to a human but was
        auto-cleared, and CI blocks any version with one.
      </p>
      {runs.some((r) => r.backend === "simulated") && (
        <div className="warn">Rows marked <b>simulated</b> use the keyword heuristic that stands in for a model when no API key is set. They show the harness works; they are not model quality.</div>
      )}
      <table className="table">
        <thead>
          <tr>
            <th>Version</th>
            <th>Model</th>
            <th>False clears (holdout)</th>
            <th>Auto-clear rate</th>
            <th>Escalation recall</th>
            <th>Reason accuracy</th>
            <th>Injections cleared / fooled model</th>
            <th>Cost / case</th>
            <th>Change</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const h = r.metrics.holdout;
            return (
              <tr key={r.version} className={r.version === version ? "selected" : ""}>
                <td>
                  <Link to={`/evals/${r.version}`}>{r.version}</Link> {r.deployed && <span className="badge badge-approved">deployed</span>}
                </td>
                <td>{r.model} {r.backend === "simulated" && <span className="badge badge-tier-medium">simulated</span>}</td>
                <td className={h.false_clears ? "bad" : "good"}>{h.false_clears}</td>
                <td>{pct(h.auto_clear_rate, 1)}</td>
                <td>{pct(h.escalation_recall, 1)}</td>
                <td>{pct(h.reason_accuracy, 1)}</td>
                <td className={h.injection_cleared ? "bad" : ""}>{h.injection_cleared} / {h.injection_model_fooled}</td>
                <td>${h.cost_per_case_usd.toFixed(4)}</td>
                <td className="small">{r.change}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {detail && (
        <section className="card">
          <h2>{detail.version}: cases it got wrong ({detail.cases.length})</h2>
          <table className="table compact">
            <thead>
              <tr><th>Case</th><th>Split</th><th>Trap</th><th>Expected</th><th>Got</th><th>Model said</th><th>Summary</th></tr>
            </thead>
            <tbody>
              {detail.cases.map((c) => (
                <tr key={c.id} className={c.verdict === "false_clear" ? "row-bad" : ""}>
                  <td>{c.id}<div className="muted small">{c.name}</div></td>
                  <td>{c.split}</td>
                  <td>{c.trap.replace(/_/g, " ")}</td>
                  <td>{c.expected === "auto_clear" ? "auto-clear" : `escalate: ${REASON_LABEL[c.expected_reason ?? ""] ?? c.expected_reason}`}</td>
                  <td><b>{c.verdict.replace("_", " ")}</b><div className="small">{c.route === "auto_clear" ? "auto-clear" : `escalate: ${REASON_LABEL[c.reason ?? ""] ?? c.reason}`}</div></td>
                  <td>{c.model_recommendation} {pct(c.confidence)}</td>
                  <td className="small">{c.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
