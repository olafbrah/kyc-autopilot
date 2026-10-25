import type { ReactNode } from "react";

export const STATUS_LABEL: Record<string, string> = {
  new: "With agent",
  needs_review: "Needs review",
  in_review: "In review",
  pending_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  auto_cleared: "Auto-cleared",
};

export const REASON_LABEL: Record<string, string> = {
  sanctions: "Sanctions",
  pep: "PEP",
  document: "ID document",
  identity: "Identity mismatch",
  country: "High-risk country",
  volume: "High volume",
  profile: "Implausible profile",
  source_of_funds: "Source of funds",
  adverse_media: "Adverse media",
  injection: "Prompt injection",
  other: "Other",
};

export function blockerLabel(b: string): string {
  if (b.startsWith("check:")) return `Check not clear: ${b.slice(6).replace(/_/g, " ")}`;
  if (b.startsWith("risk_tier")) return `Screening: ${SCREENING_LABEL[b.split(":")[1]] ?? b.split(":")[1] ?? ""}`;
  if (b.startsWith("ai_escalated:")) return `Agent escalated: ${REASON_LABEL[b.slice(13)] ?? b.slice(13)}`;
  return (
    { low_confidence: "Agent confidence below threshold", ai_risk_flags: "Agent raised risk flags", injection_suspected: "Instructions found in applicant text" }[b] ?? b
  );
}

export function Badge({ kind, children }: { kind: string; children: ReactNode }) {
  return <span className={`badge badge-${kind}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge kind={status}>{STATUS_LABEL[status] ?? status}</Badge>;
}

// risk_tier is a roll-up of the automated checks, not a customer risk rating, so the UI shows it as a screening result.
export const SCREENING_LABEL: Record<string, string> = { low: "Clear", medium: "Flagged", high: "Hit" };

export function ScreeningBadge({ tier }: { tier: string }) {
  return <Badge kind={`tier-${tier}`}>{SCREENING_LABEL[tier] ?? tier}</Badge>;
}

export const pct = (x: number | null | undefined, digits = 0) => (x == null ? "–" : `${(x * 100).toFixed(digits)}%`);

export function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.max(0, Math.round(s))}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
