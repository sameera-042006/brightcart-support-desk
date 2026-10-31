import json
import os
import pathlib
import re
import time
from collections import defaultdict, deque

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

from app.logging_utils import RUNS, log  # noqa: E402
from app.orchestrator import run_pipeline  # noqa: E402
from app.schemas.models import TicketRequest  # noqa: E402

app = FastAPI(title="BrightCart Support - Multi-Agent System with MCP")
RESULTS = pathlib.Path(__file__).resolve().parent.parent / "results"
STATIC = pathlib.Path(__file__).resolve().parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", media_type="text/html")

_hits: dict[str, deque] = defaultdict(deque)       # tiny in-memory rate limiter (per client IP per minute)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in ("/ticket", "/evaluation/run"):
        limit = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        q.append(now)
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok", "environment": os.getenv("ENVIRONMENT", "development")}


@app.post("/ticket")
def ticket(req: TicketRequest):
    state = run_pipeline(req.ticket)
    if state.status == "error":
        log.error("ticket failed: %s", state.error)
        raise HTTPException(status_code=502, detail="a required component failed; see run log")
    return {
        "run_id": state.run_id,
        "decision": state.decision,
        "status": state.status,
        "reply": state.reply,
        "reply_for_customer": re.sub(r"\s*\[E\d+\]", "", state.reply).strip(),
        "refund_amount_usd": state.refund_amount_usd,
        "escalation_ref": state.escalation_ref or None,
        "claims": [c.model_dump() for c in state.claims],
        "metrics": {
            "latency_ms": round(state.latency_ms, 1),
            "cost_usd": round(state.estimated_cost_usd, 6),
            "tokens": state.input_tokens + state.output_tokens,
            "tool_calls": state.tool_calls,
            "groundedness": state.metrics.get("groundedness"),
            "hallucination_rate": state.metrics.get("hallucination_rate"),
        },
    }


@app.get("/metrics/{run_id}")
def metrics(run_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")
    p = RUNS / f"{run_id}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return json.loads(p.read_text())


@app.post("/evaluation/run")
def evaluation_run():
    # Long-running: prefer `python run_eval.py` from a terminal. Enabled only when ALLOW_EVAL_ENDPOINT=1.
    if os.getenv("ALLOW_EVAL_ENDPOINT") != "1":
        raise HTTPException(status_code=403, detail="disabled; set ALLOW_EVAL_ENDPOINT=1 or run run_eval.py")
    import run_eval
    return run_eval.main(systems=["multi_agent"])


@app.get("/evaluation/results")
def evaluation_results():
    p = RESULTS / "summary.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no evaluation has been run yet")
    return json.loads(p.read_text())
