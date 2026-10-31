"""Conditional workflow with shared state:
triage -> [declined?] -> investigator (MCP) -> [no order / no evidence?] -> verifier -> calculator (MCP)
       -> deterministic gate -> [escalate? create_escalation (MCP)] | responder -> evaluator"""
import sys
import time
from typing import Optional

from app import gate
from app.agents import evaluator, investigator, responder, triage, verifier
from app.agents.common import AgentError
from app.llm import LLMError
from app.logging_utils import log, new_run_id, save_run
from app.mcp_client.client import MCPToolClient, MCPToolError
from app.schemas.models import Claim, Evidence, RunState

MAX_CALCULATIONS = 3

DECLINE_REPLY = ("I'm sorry, I can only help with BrightCart orders, returns, refunds, warranty, cancellations, "
                 "shipping and store policies. Please ask me about one of those.")
NO_ORDER_REPLY = ("I couldn't find an order number in your message. Please send your order number "
                  "(it looks like ORD-1234) and I'll check it for you.")
NOT_FOUND_REPLY = ("I couldn't find an order with the number {ids}. Please double-check it and reply with the "
                   "correct order number.")
UNKNOWN_REPLY = ("I'm sorry, I don't have verified information to answer that, so I won't guess. "
                 "I can pass your question to a human support agent if you like.")


def _finish(state: RunState, decision: str, status: str, reply: str, reason: str = "") -> None:
    state.decision, state.status, state.reply = decision, status, reply
    if reason:
        state.decision_reason = reason


def _run_calculations(state: RunState, mcp: MCPToolClient) -> None:
    """The model never does arithmetic: it requests an expression and MCP computes it."""
    for calc in state.calculations[:MAX_CALCULATIONS]:
        expr = str(calc.get("expression", "")).strip()
        if not expr:
            continue
        out = mcp.calculator(expr)
        if "result" not in out:
            continue                                        # invalid expression => no invented number
        eid = f"E{len(state.evidence) + 1}"
        meaning = str(calc.get("meaning", "computed value"))
        value = round(out["result"], 4) if isinstance(out["result"], float) else out["result"]
        state.evidence.append(Evidence(evidence_id=eid, source="calculator", text=f"{meaning}: {expr} = {value:.2f}"
                                       if isinstance(value, float) else f"{meaning}: {expr} = {value}"))
        state.claims.append(Claim(claim_id=f"C{len(state.claims) + 1}", statement=f"{meaning} = {value}",
                                  evidence_ids=[eid], status="SUPPORTED", supported=True, confidence=1.0))


def _escalation_reply(state: RunState) -> str:
    msg = f"I've passed your case to a human support agent (reference {state.escalation_ref})."
    if state.conflicts:
        msg += " Our information sources disagree on this: " + "; ".join(state.conflicts)
    return msg


def run_pipeline(ticket: str, mcp: Optional[MCPToolClient] = None, evaluate: bool = True) -> RunState:
    state = RunState(run_id=new_run_id(), ticket=ticket)
    mcp = mcp or MCPToolClient()
    t0 = time.perf_counter()
    try:
        state = triage.run(state)
        if not state.in_domain:                                           # branch 1: out of scope, no tools used
            _finish(state, "DECLINE", "declined", DECLINE_REPLY, "request is outside customer-support scope")
        else:
            state = investigator.run(state, mcp)
            if state.intent in gate.ORDER_INTENTS and not state.orders:   # branch 2: order missing or unknown
                reply = NOT_FOUND_REPLY.format(ids=", ".join(state.order_ids)) if state.order_ids else NO_ORDER_REPLY
                _finish(state, "INSUFFICIENT_INFO", "insufficient_info", reply, "no matching order")
            elif not state.evidence:                                      # branch 3: nothing to ground an answer on
                _finish(state, "INSUFFICIENT_INFO", "insufficient_info", UNKNOWN_REPLY, "no evidence found")
            else:
                state = verifier.run(state)
                _run_calculations(state, mcp)
                state = gate.decide(state)
                if state.decision == "ESCALATE":                          # branch 4: human takes over
                    esc = mcp.create_escalation(state.run_id, state.decision_reason, state.ticket[:500])
                    state.escalation_ref = esc.get("ticket_ref", "")
                    _finish(state, "ESCALATE", "escalated", _escalation_reply(state))
                elif state.decision == "INSUFFICIENT_INFO":
                    _finish(state, "INSUFFICIENT_INFO", "insufficient_info", UNKNOWN_REPLY)
                else:
                    state = responder.run(state)
        if evaluate:
            state = evaluator.run(state)
    except (MCPToolError, LLMError, AgentError) as exc:                   # controlled failure, nothing fabricated
        state.decision, state.status = "ERROR", "error"
        state.error = f"{type(exc).__name__}: {exc}"
        state.reply = "We could not process this request right now because a required system failed. No answer was produced."
        log.error("run %s failed: %s", state.run_id, state.error)
    state.latency_ms = (time.perf_counter() - t0) * 1000
    state.mcp_calls = list(mcp.calls)
    state.tool_calls = len(mcp.calls)
    save_run(state)
    return state


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "I want to return the headphones from order ORD-1001. Am I eligible?"
    s = run_pipeline(q)
    print(s.reply)
    print(f"\nrun_id={s.run_id} decision={s.decision} status={s.status} latency={s.latency_ms:.0f}ms "
          f"tokens={s.input_tokens}+{s.output_tokens} cost=${s.estimated_cost_usd:.6f} metrics={s.metrics}")
