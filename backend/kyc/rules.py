"""The auto-clear rule. Enforced by the API (not the agent), and reused by the eval runner so evals score the real route."""
import re

INJECTION_RE = re.compile(
    r"(ignore|disregard|override)\b.{0,60}\b(checks?|instructions?|rules?|policy|previous)\b|\bsystem\s*(note|prompt)?\s*:|"
    r"pre-?approved|auto-?approve|approve (this|immediately)|confidence (of )?1(\.0)?\b|you are (an?|the) (ai|assistant|model)",
    re.I)
TEXT_FIELDS = ("notes", "occupation", "employer", "source_of_funds", "account_purpose", "address")


def injection_suspected(applicant: dict) -> bool:
    return any(INJECTION_RE.search(str(applicant.get(f) or "")) for f in TEXT_FIELDS)


def auto_clear_blockers(checks: dict, risk_tier: str, applicant: dict, review: dict, threshold: float) -> list[str]:
    """Empty list means the case may be auto-cleared. Every reason it can't is listed (shown to humans and audited)."""
    blockers = [f"check:{name}" for name, c in checks.items() if c["status"] not in ("clear", "info")]
    if risk_tier != "low":
        blockers.append(f"risk_tier:{risk_tier}")
    if review.get("recommendation") != "approve":
        blockers.append(f"ai_escalated:{review.get('escalation_reason') or 'other'}")
    if float(review.get("confidence") or 0) < threshold:
        blockers.append("low_confidence")
    if review.get("risk_flags"):
        blockers.append("ai_risk_flags")
    if injection_suspected(applicant):
        blockers.append("injection_suspected")
    return blockers
