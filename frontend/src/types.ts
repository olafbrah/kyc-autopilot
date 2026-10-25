export type Me = { sub: string; name: string; roles: string[]; permissions: string[] };

export type AiSummary = { recommendation: string; escalation_reason: string | null; confidence: number; outcome: string };

export type Row = {
  id: number;
  external_id: string;
  full_name: string;
  nationality: string;
  risk_tier: "low" | "medium" | "high";
  status: string;
  assignee: string | null;
  proposed_by: string | null;
  decision: string | null;
  qa_status: string | null;
  received_at: string;
  decided_at: string | null;
  ai: AiSummary | null;
};

export type Check = { status: "clear" | "info" | "review" | "fail"; detail: string; [k: string]: unknown };

export type AiReview = {
  agent_version: string;
  model: string;
  recommendation: string;
  escalation_reason: string | null;
  confidence: number;
  summary: string;
  reasons: string[];
  risk_flags: string[];
  input_hash: string;
  latency_ms: number;
  cost_usd: number;
  mode: string;
  outcome: string;
  blockers: string[];
  created_at: string;
};

export type AuditEvent = {
  id: number;
  ts: string;
  actor: string;
  actor_type: string;
  action: string;
  outcome: string;
  changes: Record<string, [unknown, unknown]>;
  details: Record<string, unknown>;
};

export type Detail = Row & {
  applicant: Record<string, any>;
  checks: Record<string, Check>;
  decision_note: string | null;
  approved_by: string | null;
  qa_by: string | null;
  ai_review: AiReview | null;
  history: AuditEvent[];
  can: { work: boolean; approve: boolean; qa: boolean };
};

export type Stats = {
  counts: Record<string, number>;
  reviews: number;
  auto_mode_reviews: number;
  auto_cleared: number;
  auto_clear_rate: number | null;
  blockers: [string, number][];
  escalation_reasons: [string, number][];
  reviews_last_5m: number;
  reviews_last_60m: number;
  median_minutes_to_decision: { auto: number | null; human: number | null };
  cost_usd: number;
  avg_latency_ms: number | null;
  qa: Record<string, number>;
  agent_versions: [string, number][];
};

export type AgentSettings = { mode: "auto" | "shadow" | "off"; threshold: number; qa_rate: number; updated_by: string | null; updated_at: string };

export type EvalMetrics = {
  cases: number;
  false_clears: number;
  auto_clear_rate: number;
  escalation_recall: number;
  reason_accuracy: number;
  model_judgement_recall: number;
  injection_cleared: number;
  injection_model_fooled: number;
  cost_per_case_usd: number;
  p50_latency_ms: number;
  by_trap: Record<string, Record<string, number>>;
};

export type EvalRun = {
  version: string;
  model: string;
  backend: string;
  change: string;
  created_at: string;
  deployed: boolean;
  metrics: { dev: EvalMetrics; holdout: EvalMetrics };
};

export type EvalCase = {
  id: string;
  split: string;
  trap: string;
  name: string;
  expected: string;
  expected_reason: string | null;
  route: string;
  reason: string | null;
  verdict: string;
  blockers: string[];
  model_recommendation: string;
  confidence: number;
  summary: string;
};
