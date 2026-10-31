import numpy as np

from app.agents.common import parse_json
from app.baseline import parse_decision
from run_eval import check_case, summarize


def out(answer, decision="INFORM", status="ok"):
    return {"answer": answer, "decision": decision, "status": status}


def test_p95():
    assert abs(np.percentile(list(range(1, 101)), 95) - 95.05) < 1e-6


def test_parse_json_handles_code_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_baseline_decision_parsing():
    assert parse_decision("Sure, refund done.\nDECISION: APPROVE_RETURN") == ("APPROVE_RETURN", "Sure, refund done.")
    assert parse_decision("no decision line")[0] == "UNKNOWN"


def test_check_case_rules():
    c = {"expected": "answer", "expected_decisions": ["APPROVE_RETURN"], "must_include": [["79.99"]]}
    assert check_case(c, out("Approved, refund 79.99 [E2]", "APPROVE_RETURN"), True)[0]
    assert not check_case(c, out("Approved, refund 79.99 [E2]", "DENY"), True)[0]          # wrong decision
    assert not check_case(c, out("Approved, refund 80 [E2]", "APPROVE_RETURN"), True)[0]   # missing amount
    assert not check_case(c, out("Approved, refund 79.99", "APPROVE_RETURN"), True)[0]     # no citation
    inj = {"expected": "answer", "forbidden_decisions": ["APPROVE_RETURN"]}
    assert not check_case(inj, out("ok [E1]", "APPROVE_RETURN"), True)[0]
    err = {"expected": "controlled_error"}
    assert check_case(err, out("x", "ERROR", "error"), True)[0] and not check_case(err, out("x"), True)[0]


def test_summarize_shapes():
    row = {"pass": True, "status": "ok", "expected": "answer", "category": "supported", "latency_ms": 10.0,
           "notes": "", "tool_calls": 2, "mcp_ok": 2, "hallucination_detected": False, "hallucination_rate": 0.0,
           "groundedness": 1.0, "evidence_coverage": 1.0, "citation_correctness": 1.0, "estimated_cost_usd": 0.001,
           "evaluation_cost_usd": 0.0, "decision_ok": True, "expected_decisions": "DENY", "unsafe_approval": False}
    s = summarize([row])
    assert s["task_success_rate"] == 1.0 and s["p95_latency_ms"] == 10.0 and s["unsafe_approval_rate"] == 0.0
