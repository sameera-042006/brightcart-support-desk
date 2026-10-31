"""Evaluation harness.

  python run_eval.py                              # baseline + multi_agent (MCP server must be running)
  python run_eval.py --systems multi_agent
  python run_eval.py --limit 5                    # quick smoke run
  python run_eval.py --api-url https://YOUR-API.onrender.com   # same suite against the deployed API

Outputs (results/): evaluation_results.csv, cost_log.csv, summary.json, comparison.md
Pass/fail is rule-based (decision field, keywords, regex). Audit a sample by hand as well (guide layer L7).
"""
import argparse
import csv
import json
import pathlib
import re
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from app import baseline  # noqa: E402
from app.agents.evaluator import INSUFFICIENT_MARKERS, evaluate_answer  # noqa: E402
from app.cost import call_cost, pricing  # noqa: E402
from app.gate import APPROVING  # noqa: E402
from app.logging_utils import new_run_id  # noqa: E402
from app.mcp_client.client import MCPToolClient  # noqa: E402
from app.orchestrator import run_pipeline  # noqa: E402
from app.schemas.models import Evidence, RunState  # noqa: E402
from mcp_server import tools  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CASES = ROOT / "data" / "test_cases.json"
NO_ANSWER = {"INSUFFICIENT_INFO", "ESCALATE", "DECLINE"}

CHALLENGE_MARKERS = INSUFFICIENT_MARKERS + ("not supported", "incorrect", "premise", "contradict", "cannot confirm",
    "not true", "unsupported", "no such", "there is no", "isn't", "is not", "not a ", "not accurate", "does not",
    "doesn't", "only", "actually", "however", "unfortunately", "cannot", "can't", "not available", "not offer")
CONFLICT_WORDS = ("conflict", "disagree", "differ", "contradict", "inconsisten", "discrepan", "whereas")

COLUMNS = ["test_id", "category", "system", "ticket", "expected", "expected_decisions", "decision", "decision_ok",
           "actual", "pass", "status", "input_tokens", "output_tokens", "tool_calls", "mcp_ok", "latency_ms",
           "estimated_cost_usd", "evaluation_cost_usd", "hallucination_detected", "unsafe_approval", "groundedness",
           "hallucination_rate", "evidence_coverage", "citation_correctness", "notes"]


def has(text, markers):
    t = text.lower()
    return any(m in t for m in markers)


def check_case(case, out, is_multi):
    answer, status, decision = out["answer"], out["status"], out["decision"]
    exp, a = case["expected"], out["answer"].lower()
    if exp == "controlled_error":
        return status == "error", "" if status == "error" else "expected a controlled error"
    if status == "error":
        return False, "unexpected error"
    for group in case.get("must_include", []):
        if not any(k.lower() in a for k in group):
            return False, f"missing one of {group}"
    if case.get("must_not_regex") and re.search(case["must_not_regex"], a):
        return False, "repeated injected text"
    allowed = case.get("expected_decisions")
    if allowed and decision not in allowed:
        return False, f"decision {decision} not in {allowed}"
    if decision in case.get("forbidden_decisions", []):
        return False, f"forbidden decision {decision}"
    if exp == "challenge_premise" and not has(a, CHALLENGE_MARKERS):
        return False, "premise should be challenged"
    if exp == "report_conflict" and not has(a, CONFLICT_WORDS):
        return False, "conflict should be reported"
    if exp == "answer" and is_multi and status == "ok" and "[E" not in answer:
        return False, "no evidence citation"
    return True, ""


def malformed_server():
    from mcp.server.mcpserver import MCPServer
    s = MCPServer("malformed")

    @s.tool()
    def get_order(order_id: str) -> dict:
        return {"order_id": 123}                           # violates the OrderResponse contract

    @s.tool()
    def search_policy(query: str, top_k: int = 4) -> dict:
        return {"results": [{"source": 123}]}              # violates the SearchResponse contract
    return s


def build_mcp(case):
    inj = case.get("inject")
    if inj == "mcp_down":
        return MCPToolClient(url="http://127.0.0.1:9/mcp", retries=1, backoff=0.1, timeout=3)
    if inj == "malformed_tool":
        return MCPToolClient(server=malformed_server(), retries=0)
    return MCPToolClient()


def _agent(state, name):
    return next((a for a in state.agents if a.name == name), None)


def run_multi_agent(case):
    state = run_pipeline(case["ticket"], mcp=build_mcp(case))
    ev = _agent(state, "evaluator")
    ev_cost = ev.cost_usd if ev else 0.0
    ev_in, ev_out, ev_ms = (ev.input_tokens, ev.output_tokens, ev.latency_ms) if ev else (0, 0, 0)
    return dict(answer=state.reply, status=state.status, decision=state.decision,
                input_tokens=state.input_tokens - ev_in, output_tokens=state.output_tokens - ev_out,
                tool_calls=len(state.mcp_calls), mcp_ok=sum(1 for m in state.mcp_calls if m.success),
                latency_ms=state.latency_ms - ev_ms, cost=state.estimated_cost_usd - ev_cost, eval_cost=ev_cost,
                metrics=state.metrics, agents=[(a.name, a.llm_calls, a.input_tokens, a.output_tokens, a.cost_usd)
                                               for a in state.agents])


def baseline_evidence(case):
    """The facts a tool-using system could have retrieved, so the baseline is judged against the same ground truth."""
    ev, n = [], 0
    for oid in sorted(set(re.findall(r"ORD-\d{4}", case["ticket"].upper()))):
        o = tools.get_order(oid)
        if "error" not in o:
            n += 1
            ev.append(Evidence(evidence_id=f"E{n}", source=f"order_db:{oid}", text=json.dumps(o)))
            n += 1
            ev.append(Evidence(evidence_id=f"E{n}", source=f"eligibility_tool:{oid}",
                               text=json.dumps(tools.check_return_eligibility(oid))))
    for h in tools.search_policy(case["ticket"])["results"]:
        n += 1
        ev.append(Evidence(evidence_id=f"E{n}", source=h["source"], text=h["text"]))
    return ev


def run_baseline(case):
    state = RunState(run_id=new_run_id(), ticket=case["ticket"])
    try:
        baseline.run(state)
    except Exception as exc:  # LLM failure
        return dict(answer=f"ERROR {exc}", status="error", decision="ERROR", input_tokens=0, output_tokens=0,
                    tool_calls=0, mcp_ok=0, latency_ms=0, cost=0, eval_cost=0, metrics={}, agents=[])
    m = evaluate_answer(state.reply, baseline_evidence(case), state=None, question=case["ticket"])
    j_in, j_out, _ = m.pop("judge_usage")
    j_cost = call_cost(j_in, j_out)
    return dict(answer=state.reply, status="ok", decision=state.decision, input_tokens=state.input_tokens,
                output_tokens=state.output_tokens, tool_calls=0, mcp_ok=0, latency_ms=state.latency_ms,
                cost=state.estimated_cost_usd, eval_cost=j_cost, metrics=m,
                agents=[("baseline", 1, state.input_tokens, state.output_tokens, state.estimated_cost_usd),
                        ("judge", 1, j_in, j_out, j_cost)])


def run_api(case, api_url):
    import httpx
    t0 = time.perf_counter()
    try:
        r = httpx.post(api_url.rstrip("/") + "/ticket", json={"ticket": case["ticket"]}, timeout=180)
    except httpx.HTTPError as exc:
        return dict(answer=f"ERROR {exc}", status="error", decision="ERROR", input_tokens=None, output_tokens=None,
                    tool_calls=0, mcp_ok=0, latency_ms=(time.perf_counter() - t0) * 1000, cost=0, eval_cost=0,
                    metrics={}, agents=[])
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        return dict(answer=f"HTTP {r.status_code}", status="error", decision="ERROR", input_tokens=None,
                    output_tokens=None, tool_calls=0, mcp_ok=0, latency_ms=ms, cost=0, eval_cost=0, metrics={}, agents=[])
    d = r.json()
    return dict(answer=d["reply"], status=d["status"], decision=d["decision"], input_tokens=None, output_tokens=None,
                tool_calls=d["metrics"].get("tool_calls", 0), mcp_ok=d["metrics"].get("tool_calls", 0), latency_ms=ms,
                cost=d["metrics"].get("cost_usd", 0), eval_cost=0,
                metrics={"groundedness": d["metrics"].get("groundedness"),
                         "hallucination_rate": d["metrics"].get("hallucination_rate")}, agents=[])


def one_case(case, system, api_url):
    if case.get("inject") and (system == "baseline" or api_url):
        return None                                           # failure injection needs the local multi-agent run
    out = run_api(case, api_url) if (api_url and system == "multi_agent") else \
        (run_baseline(case) if system == "baseline" else run_multi_agent(case))
    is_multi = system == "multi_agent"
    passed, note = check_case(case, out, is_multi)
    allowed = case.get("expected_decisions")
    decision_ok = (out["decision"] in allowed) if allowed else None
    unsafe = bool(allowed) and not (set(allowed) & APPROVING) and out["decision"] in APPROVING
    halluc = unsafe or "repeated" in note
    if allowed and set(allowed) <= NO_ANSWER and out["decision"] not in NO_ANSWER and out["status"] != "error":
        halluc = True                                         # answered as if the unknown were known
    if case["expected"] == "challenge_premise" and out["status"] != "error" and "premise" in note:
        halluc = True
    m = out["metrics"]
    if m.get("hallucination_rate"):
        halluc = True
    rec = {"test_id": case["test_id"], "category": case["category"], "system": system, "ticket": case["ticket"],
           "expected": case["expected"], "expected_decisions": "|".join(allowed or []), "decision": out["decision"],
           "decision_ok": decision_ok, "actual": out["answer"].replace("\n", " ")[:600], "pass": passed,
           "status": out["status"], "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
           "tool_calls": out["tool_calls"], "mcp_ok": out["mcp_ok"], "latency_ms": round(out["latency_ms"], 1),
           "estimated_cost_usd": round(out["cost"], 6), "evaluation_cost_usd": round(out["eval_cost"], 6),
           "hallucination_detected": halluc, "unsafe_approval": unsafe, "groundedness": m.get("groundedness"),
           "hallucination_rate": m.get("hallucination_rate"), "evidence_coverage": m.get("evidence_coverage"),
           "citation_correctness": m.get("citation_correctness"), "notes": note if not passed else ""}
    return rec, out["agents"]


def summarize(rows):
    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(float(np.mean(xs)), 4) if xs else None
    n = len(rows)
    lat = [r["latency_ms"] for r in rows if r["status"] != "error"] or [0]
    normal = [r for r in rows if r["category"] != "tool_failure"]
    calls, ok = sum(r["tool_calls"] for r in normal), sum(r["mcp_ok"] for r in normal)
    reliable = sum(1 for r in rows if r["status"] != "error" or r["expected"] == "controlled_error")
    graded = [r for r in rows if r["decision_ok"] is not None]
    no_approve = [r for r in graded if not (set(r["expected_decisions"].split("|")) & APPROVING)]
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], [0, 0]); c[0] += 1; c[1] += bool(r["pass"])
    return {
        "cases": n,
        "task_success_rate": round(sum(bool(r["pass"]) for r in rows) / n, 4),
        "decision_accuracy": round(sum(bool(r["decision_ok"]) for r in graded) / len(graded), 4) if graded else None,
        "unsafe_approval_rate": round(sum(bool(r["unsafe_approval"]) for r in no_approve) / len(no_approve), 4) if no_approve else None,
        "reliability": round(reliable / n, 4),
        "tool_success_rate_excl_injected_failures": round(ok / calls, 4) if calls else None,
        "case_level_hallucination_rate": round(sum(bool(r["hallucination_detected"]) for r in rows) / n, 4),
        "mean_claim_hallucination_rate": avg([r["hallucination_rate"] for r in rows]),
        "mean_groundedness": avg([r["groundedness"] for r in rows]),
        "mean_evidence_coverage": avg([r["evidence_coverage"] for r in rows]),
        "mean_citation_correctness": avg([r["citation_correctness"] for r in rows]),
        "mean_latency_ms": round(float(np.mean(lat)), 1),
        "p95_latency_ms": round(float(np.percentile(lat, 95)), 1),
        "mean_cost_per_query_usd": round(float(np.mean([r["estimated_cost_usd"] for r in rows])), 6),
        "total_answer_cost_usd": round(sum(r["estimated_cost_usd"] for r in rows), 6),
        "total_evaluation_cost_usd": round(sum(r["evaluation_cost_usd"] for r in rows), 6),
        "pass_by_category": {k: f"{v[1]}/{v[0]}" for k, v in cats.items()},
    }


def write_outputs(all_rows, cost_rows, summary):
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "evaluation_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS); w.writeheader(); w.writerows(all_rows)
    with (RESULTS / "cost_log.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test_id", "system", "agent", "llm_calls", "input_tokens", "output_tokens", "cost_usd"])
        w.writerows(cost_rows)
    (RESULTS / "summary.json").write_text(json.dumps({"pricing": pricing(), "systems": summary}, indent=2), encoding="utf-8")
    b, m = summary.get("baseline"), summary.get("multi_agent")
    if b and m:
        rows = [("Task success rate", "task_success_rate"), ("Decision accuracy", "decision_accuracy"),
                ("Unsafe approval rate (lower is better)", "unsafe_approval_rate"),
                ("Groundedness (mean)", "mean_groundedness"),
                ("Hallucination, case level", "case_level_hallucination_rate"),
                ("Hallucination, claim level (mean)", "mean_claim_hallucination_rate"),
                ("Mean latency (ms)", "mean_latency_ms"), ("P95 latency (ms)", "p95_latency_ms"),
                ("Cost/query (USD, equivalent paid tier)", "mean_cost_per_query_usd"),
                ("Tool success rate", "tool_success_rate_excl_injected_failures"), ("Reliability", "reliability")]
        lines = ["| Metric | Single-Agent Baseline | Multi-Agent + MCP |", "|---|---|---|"]
        lines += [f"| {lbl} | {b.get(k)} | {m.get(k)} |" for lbl, k in rows]
        (RESULTS / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(systems=None, limit=None, api_url=None):
    cases = json.loads(CASES.read_text(encoding="utf-8"))[: limit or None]
    systems = systems or ["baseline", "multi_agent"]
    all_rows, cost_rows, summary = [], [], {}
    for system in systems:
        rows = []
        for i, case in enumerate(cases, 1):
            res = one_case(case, system, api_url)
            if res is None:
                continue
            rec, agents = res
            rows.append(rec)
            for a in agents:
                cost_rows.append([case["test_id"], system, *a[:4], round(a[4], 6)])
            print(f"[{system}] {i}/{len(cases)} {case['test_id']} decision={rec['decision']} pass={rec['pass']} "
                  f"lat={rec['latency_ms']:.0f}ms {rec['notes']}", flush=True)
        all_rows += rows
        if rows:
            summary[system] = summarize(rows)
    write_outputs(all_rows, cost_rows, summary)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="baseline,multi_agent")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--api-url")
    a = ap.parse_args()
    main(a.systems.split(","), a.limit, a.api_url)