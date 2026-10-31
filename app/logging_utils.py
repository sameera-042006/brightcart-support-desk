import json
import logging
import os
import pathlib
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
for noisy in ("httpx", "httpx2", "httpcore", "mcp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("mas")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def save_run(state) -> pathlib.Path:
    """Write runs/<run_id>.json in the section-24 log format (no secrets, no API keys)."""
    RUNS.mkdir(exist_ok=True)
    doc = {
        "run_id": state.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticket": state.ticket,
        "intent": state.intent,
        "decision": state.decision,
        "decision_reason": state.decision_reason,
        "refund_amount_usd": state.refund_amount_usd,
        "escalation_ref": state.escalation_ref,
        "status": state.status,
        "error": state.error,
        "agents": [{"name": a.name, "latency_ms": round(a.latency_ms, 1), "llm_calls": a.llm_calls,
                    "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
                    "tokens": a.input_tokens + a.output_tokens, "cost_usd": round(a.cost_usd, 6)}
                   for a in state.agents],
        "mcp_calls": [m.model_dump() for m in state.mcp_calls],
        "order_ids": state.order_ids,
        "evidence": [e.model_dump() for e in state.evidence],
        "claims": [c.model_dump() for c in state.claims],
        "conflicts": state.conflicts,
        "unsupported_premises": state.unsupported_premises,
        "reply": state.reply,
        "total_tokens": state.input_tokens + state.output_tokens,
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "total_cost_usd": round(state.estimated_cost_usd, 6),
        "latency_ms": round(state.latency_ms, 1),
        "hallucination_rate": state.metrics.get("hallucination_rate"),
        "groundedness": state.metrics.get("groundedness"),
        "metrics": state.metrics,
    }
    path = RUNS / f"{state.run_id}.json"
    path.write_text(json.dumps(doc, indent=2))
    return path
