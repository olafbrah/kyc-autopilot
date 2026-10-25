from evals.run import gate, load_dataset, metrics, score_case
from kyc.agent.agent import get_config
from kyc.agent.llm import ScriptedLLM


def test_dataset_is_reproducible_and_split():
    cases = load_dataset()
    assert len(cases) == 300 and sum(c["split"] == "holdout" for c in cases) == 100
    assert len({c["applicant"]["external_id"] for c in cases}) == 300


def test_scoring_counts_a_model_that_approves_everything_as_unsafe():
    yes = ScriptedLLM(fn=lambda m: {"recommendation": "approve", "confidence": 0.99})
    rows = [score_case(yes, get_config("v1"), c) for c in load_dataset()[:200]]
    m = metrics(rows)
    assert m["false_clears"] > 0 and m["auto_clear_rate"] == 1.0
    assert all(r["verdict"] != "false_clear" for r in rows if r["trap"] in ("sanctions_hit", "pep", "expired_id"))
    assert gate({"metrics": {"dev": m}}, None)


def test_scoring_a_model_that_escalates_everything_is_safe_but_useless():
    no = ScriptedLLM(fn=lambda m: {"recommendation": "escalate", "escalation_reason": "other", "confidence": 0.9})
    m = metrics([score_case(no, get_config("v1"), c) for c in load_dataset()[:100]])
    assert m["false_clears"] == 0 and m["auto_clear_rate"] == 0.0
