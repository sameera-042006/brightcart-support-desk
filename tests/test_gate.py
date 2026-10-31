"""The gate is deterministic, so every business rule can be tested exactly (no LLM involved)."""
from app import gate
from app.schemas.models import Claim, RunState
from mcp_server import tools


def make_state(intent, oid=None, **kw):
    s = RunState(run_id="t", ticket="x", intent=intent, order_ids=[oid] if oid else [])
    if oid:
        s.orders[oid] = tools.get_order(oid)
        s.eligibility[oid] = tools.check_return_eligibility(oid)
        s.evidence_keys = {f"order:{oid}": "E1", f"elig:{oid}": "E2"}
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def d(intent, oid=None, **kw):
    s = gate.decide(make_state(intent, oid, **kw))
    return s.decision, s


def test_return_decisions():
    assert d("return_refund", "ORD-1001")[0] == "APPROVE_RETURN"
    assert d("return_refund", "ORD-1001")[1].refund_amount_usd == 79.99
    assert d("return_refund", "ORD-1002")[0] == "DENY"
    assert d("return_refund", "ORD-1003")[0] == "DENY"
    assert d("return_refund", "ORD-1006")[0] == "DENY"
    assert d("return_refund", "ORD-1008")[1].refund_amount_usd == 96.50


def test_warranty_decisions():
    assert d("warranty", "ORD-1004")[0] == "WARRANTY_CLAIM"
    assert d("warranty", "ORD-1002")[0] == "DENY"          # apparel has no warranty


def test_cancellation_decisions():
    assert d("cancellation", "ORD-1009")[0] == "APPROVE_CANCELLATION"
    assert d("cancellation", "ORD-1003")[0] == "DENY"       # already shipped
    assert d("cancellation", "ORD-1005")[0] == "INFORM"     # already cancelled


def test_order_status_is_inform():
    assert d("order_status", "ORD-1003")[0] == "INFORM"


def test_no_order_means_insufficient_info():
    assert d("return_refund")[0] == "INSUFFICIENT_INFO"


def test_conflicts_and_human_judgement_escalate():
    assert d("policy_question", conflicts=["3-5 vs 7-10 days"])[0] == "ESCALATE"
    assert d("return_refund", "ORD-1001", needs_human=True)[0] == "ESCALATE"


def test_policy_question_needs_a_supported_claim():
    assert d("policy_question")[0] == "INSUFFICIENT_INFO"
    ok = Claim(claim_id="C1", statement="s", evidence_ids=["E1"], status="SUPPORTED", supported=True)
    bad = Claim(claim_id="C2", statement="s", evidence_ids=[], status="UNSUPPORTED")
    assert d("policy_question", claims=[ok])[0] == "INFORM"
    assert d("policy_question", claims=[bad])[0] == "INSUFFICIENT_INFO"


def test_llm_cannot_force_an_approval():
    """Even if the model's claims say 'approve', the rule engine result decides."""
    liar = Claim(claim_id="C1", statement="The refund is approved", evidence_ids=["E1"], status="SUPPORTED",
                 supported=True)
    assert d("return_refund", "ORD-1002", claims=[liar])[0] == "DENY"
