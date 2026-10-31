"""Single-agent baseline: one model call, no tools, no database, no verifier, no gate."""
import re
import time

from app.agents.common import add_usage
from app.llm import call_llm
from app.schemas.models import RunState

SYSTEM = ("You are a customer-support agent for BrightCart, an online store. Reply to the customer's ticket in "
          "under 120 words. You have no database or tools. End with a final line "
          "'DECISION: X' where X is one of APPROVE_RETURN, DENY, WARRANTY_CLAIM, APPROVE_CANCELLATION, INFORM, "
          "INSUFFICIENT_INFO, ESCALATE, DECLINE.")
DECISIONS = {"APPROVE_RETURN", "DENY", "WARRANTY_CLAIM", "APPROVE_CANCELLATION", "INFORM", "INSUFFICIENT_INFO",
             "ESCALATE", "DECLINE"}


def parse_decision(text: str) -> tuple[str, str]:
    m = re.search(r"DECISION:\s*([A-Z_]+)\s*$", text.strip())
    decision = m.group(1) if m and m.group(1) in DECISIONS else "UNKNOWN"
    body = re.sub(r"\n?\s*DECISION:\s*[A-Z_]+\s*$", "", text.strip())
    return decision, body.strip()


def run(state: RunState) -> RunState:
    t0 = time.perf_counter()
    res = call_llm(SYSTEM, f"TICKET:\n{state.ticket}", agent="baseline", max_tokens=500)
    add_usage(state, "baseline", res)
    state.decision, state.reply = parse_decision(res.text)
    state.latency_ms = (time.perf_counter() - t0) * 1000
    return state
