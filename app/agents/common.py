import json
import re
import time

from app.cost import call_cost
from app.llm import LLMResult, call_llm
from app.schemas.models import AgentLog, RunState


class AgentError(Exception):
    pass


def parse_json(text: str) -> dict:
    """Parse a model reply that should be a single JSON object (tolerates code fences)."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AgentError(f"model did not return valid JSON: {text[:120]!r}")


def log_for(state: RunState, name: str) -> AgentLog:
    for a in state.agents:
        if a.name == name:
            return a
    a = AgentLog(name=name)
    state.agents.append(a)
    return a


def llm(state: RunState, agent: str, system: str, user: str, json_mode: bool = False,
        max_tokens: int = 1500) -> LLMResult:
    """Call the model for one agent and record tokens, latency and cost on the run state."""
    res = call_llm(system, user, json_mode=json_mode, agent=agent, max_tokens=max_tokens)
    add_usage(state, agent, res)
    return res


def add_usage(state: RunState, agent: str, res: LLMResult):
    a = log_for(state, agent)
    c = call_cost(res.input_tokens, res.output_tokens)
    a.llm_calls += 1
    a.input_tokens += res.input_tokens
    a.output_tokens += res.output_tokens
    a.latency_ms += res.latency_ms
    a.cost_usd += c
    state.input_tokens += res.input_tokens
    state.output_tokens += res.output_tokens
    state.estimated_cost_usd += c


def evidence_block(evidence) -> str:
    """Retrieved text is untrusted DATA: wrap it so it cannot pass as instructions."""
    return "\n".join(
        f'<evidence id="{e.evidence_id}" source="{e.source}">{e.text}</evidence>' for e in evidence)


class Timer:
    def __init__(self, state: RunState, name: str):
        self.state, self.name = state, name

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *exc):
        # LLM latency is added per call; add the non-LLM remainder only for agents with no LLM call
        a = log_for(self.state, self.name)
        if a.llm_calls == 0:
            a.latency_ms += (time.perf_counter() - self.t0) * 1000
