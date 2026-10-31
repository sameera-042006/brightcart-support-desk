#!/usr/bin/env python
"""Builds docs/14_Final_Report.pdf (guide section 42, 21 chapters) from the REAL files in results/.

  python make_report.py --name "Vasa Ragha Sameera" --reg 2023000676 --course "CSE-AIML, GITAM" \
      --url https://brightcart-support-desk.onrender.com --repo https://github.com/sameera-042006/brightcart-support-desk

Every number comes from results/summary.json and results/evaluation_results.csv. Nothing is typed in by hand.
If the results hold fewer than 30 cases or no baseline run, the report is stamped PRELIMINARY on every
affected table, so a smoke run can never be mistaken for the final evaluation. Rerun after `python run_eval.py`.
"""
import argparse, csv, datetime as dt, json, pathlib, sys
from collections import Counter, defaultdict
from xml.sax.saxutils import escape

import docgen as d
from docgen import P, H2, H3, bullets, table

ROOT = pathlib.Path(__file__).resolve().parent
SMALL = d.ParagraphStyle("note", parent=d.BODY, fontSize=9, textColor=d.MUTED)


def _open(p):
    """Open a CSV written by either Windows (cp1252) or UTF-8 tools."""
    raw = pathlib.Path(p).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    import io
    return io.StringIO(text, newline="")


def load():
    summ = json.loads((ROOT / "results" / "summary.json").read_text(encoding="utf-8")) if (ROOT / "results" / "summary.json").exists() else {}
    rows = list(csv.DictReader(_open(ROOT / "results" / "evaluation_results.csv"))) if (ROOT / "results" / "evaluation_results.csv").exists() else []
    cases = json.loads((ROOT / "data" / "test_cases.json").read_text(encoding="utf-8")) if (ROOT / "data" / "test_cases.json").exists() else []
    return summ, rows, cases


def fmt(v, kind="num"):
    if v in (None, ""):
        return "n/a"
    if kind == "pct":
        return f"{float(v) * 100:.1f}%"
    if kind == "ms":
        return f"{float(v) / 1000:.1f} s"
    if kind == "usd":
        return f"${float(v):.6f}"
    return str(v)


def audit_summary():
    f = ROOT / "docs" / "human_audit.csv"
    if not f.exists():
        return None
    r = list(csv.DictReader(_open(f)))
    if not r:
        return None
    col = next((c for c in r[0] if "verdict" in c.lower() or "correct" in c.lower()), None)
    return (len(r), Counter(x[col].strip().lower() for x in r if col and x.get(col)) if col else None)


def main(argv=None):
    ap = argparse.ArgumentParser()
    for a in ("name", "reg", "course", "url", "repo", "commit", "video"):
        ap.add_argument("--" + a, default="")
    ap.add_argument("--out", default=str(ROOT / "docs" / "14_Final_Report.pdf"))
    a = ap.parse_args(argv)
    summ, rows, cases = load()
    systems = summ.get("systems", {})
    ma, bl = systems.get("multi_agent", {}), systems.get("baseline", {})
    pricing = summ.get("pricing", {})
    model = pricing.get("model", "(unknown)")
    n_ma, n_bl = ma.get("cases", 0), bl.get("cases", 0)
    prelim = n_ma < len(cases or [0] * 30) or not bl or n_ma < 30
    stamp = (" PRELIMINARY: only %d multi-agent and %d baseline cases are in results/. Rerun run_eval.py (30 cases) and regenerate." % (n_ma, n_bl)) if prelim else ""
    meta = {"name": a.name, "reg": a.reg, "course": a.course, "date": dt.date.today().strftime("%d %B %Y")}
    cat = Counter(c.get("category") for c in cases)
    S = d._title_block("Final Report", "BrightCart Support Desk: a verified multi-agent ticket-resolution system with MCP", meta)
    if prelim:
        S += [P("DRAFT." + stamp, d.ParagraphStyle("warn", parent=d.BODY, backColor=d.TAPE, borderPadding=6))]

    def chap(n, t):
        return [P(f"{n}. {t}", H2)]

    # 1 Abstract
    S += chap(1, "Abstract")
    S += [P("Language models that answer customer-support tickets from memory invent order details, misquote policy and promise refunds "
            "they have no authority to give. This project builds BrightCart Support Desk, a ticket-resolution system in which five "
            "role-based agents (Triage, Investigator, Verifier, Responder, Evaluator) work through a Model Context Protocol (MCP) server "
            "that exposes order lookup, return-eligibility rules, policy search, a calculator, escalation and an audit log. A deterministic "
            "decision gate, not the language model, decides whether a return, cancellation or warranty claim is approved. The system is "
            f"evaluated on a {len(cases) or 30}-case suite against a single-model baseline using {model}, deployed in one Docker container "
            f"on Render at {a.url or '(URL)'}."),
          P("Measured results are given in Chapter 14." + (stamp if prelim else " They are produced by run_eval.py and are reproducible from the repository."))]
    # 2
    S += chap(2, "Introduction and Motivation")
    S += [P("Support tickets are short, factual and rule-bound, which makes them a good test of whether an AI system can be trusted. "
            "A wrong answer has a direct cost: a refund paid by mistake, a customer wrongly refused, or a policy promise the store must honour. "
            "The motivation is to show, with measurements and not claims, which engineering controls reduce that risk and what they cost in latency and money.")]
    # 3
    S += chap(3, "Problem Statement")
    S += [P("Build a ticket-resolution assistant whose every statement is grounded in the store's order data and policy documents, that declines "
            "when evidence is missing, that cannot be instructed to approve a refund by text hidden in a ticket or document, and that fails safely "
            "when a tool or the model is unavailable. Research question: does a verified multi-agent workflow with MCP tools and a deterministic "
            "decision gate make the assistant measurably safer and more truthful than a single model call with no tools?")]
    # 4
    S += chap(4, "Objectives")
    S += bullets(["Expose deterministic tools behind an MCP server, separate from the reasoning layer.",
                  "Implement five agents coordinated by an orchestrator with shared state, branches and structured logs.",
                  "Take financial decisions with a rule gate, not with the model.",
                  "Detect hallucination in layers L1 to L7 and measure it.",
                  "Evaluate against a baseline using accuracy, groundedness, hallucination rate, unsafe-approval rate, latency, tool success and cost.",
                  "Containerise and deploy with authentication, and document reproducibility."])
    # 5
    S += chap(5, "Related Concepts: Agents and MCP")
    S += [P("An agent is a model call with a defined role, input contract and output contract. A multi-agent system divides a task among such roles so that "
            "each step can be checked. The Model Context Protocol is an open standard by which a client discovers and calls tools exposed by a server, "
            "with typed inputs and outputs. Here the MCP server holds all business facts and rules, so the model never needs to remember them. "
            "The project uses the official MCP Python SDK (v2 line): MCPServer on the server side, Client with the Streamable HTTP transport on the client side."),
          P("Retrieval-grounded generation, claim-level verification, prompt-injection defence by treating retrieved text as data, and LLM-as-judge evaluation "
            "are the supporting techniques. Each is used in a bounded way and checked by tests rather than trusted.")]
    # 6
    S += chap(6, "System Requirements")
    S += table([["Type", "Requirement"],
                ["Functional", "Resolve tickets on order status, returns and refunds, cancellation, warranty and policy questions; cite evidence; escalate when sources conflict; refuse out-of-domain requests."],
                ["Safety", "No approval without rule-engine support; injected instructions are ignored; tool or model failure ends in a controlled message, never a guess."],
                ["Quality", "Every factual claim carries an evidence citation that exists in the retrieved evidence."],
                ["Operational", "Per-agent token, latency and cost logs; health endpoint; rate limiting; secrets kept out of Git."],
                ["Platform", "Python 3.12, MCP SDK 2.x, FastAPI, Docker; hosted Gemini model on the free tier."]], [3.0, 14.0])
    # 7
    S += chap(7, "Architecture and Design")
    S += [P("A ticket enters the FastAPI service. The orchestrator creates a shared RunState and calls the agents in order: Triage extracts intent and the order id; "
            "the Investigator calls MCP tools and builds numbered evidence; the Verifier turns evidence into claims, flags conflicts and unsupported premises; "
            "the decision gate computes the outcome from rules; the Responder writes the reply using only verified claims; the Evaluator checks citations. "
            "Branches end the run early with a decline, a request for more information, or an escalation. The full diagram is in 02_System_Architecture.pdf.")]
    # 8
    S += chap(8, "MCP Server and Client Design")
    S += table([["Tool", "Purpose"],
                ["get_order", "Return one order's record, or a typed not-found result."],
                ["check_return_eligibility", "Apply the 30-day window, damaged-item, non-returnable and warranty rules; return the refund amount."],
                ["search_policy", "Token-overlap retrieval over 12 policy documents with a relevance floor."],
                ["calculator", "Evaluate arithmetic through an AST allow-list; no eval()."],
                ["create_escalation", "Write an escalation record and return a ticket id."],
                ["save_evidence", "Append the evidence bundle to the run's audit log."]], [4.6, 12.4])
    S += [P("The server requires a bearer token and, in production, listens on 127.0.0.1 inside the container. The client wraps every call with a timeout, bounded retries "
            "with backoff, and Pydantic validation of the response; a failed or malformed response becomes a typed MCPToolError that the orchestrator turns into a controlled reply.")]
    # 9
    S += chap(9, "Multi-Agent Design")
    S += table([["Agent", "Uses model?", "Responsibility", "Output contract"],
                ["Triage", "Yes", "Intent, order id, urgency", "JSON; order id also extracted by regex"],
                ["Investigator", "No", "Call MCP tools, build evidence", "Numbered evidence list"],
                ["Verifier", "Yes", "Claims, conflicts, false premises, calculations", "Claims with evidence ids and status"],
                ["Decision gate", "No", "Approve, deny, inform, warranty, escalate", "One decision code plus rule-derived amount"],
                ["Responder", "Yes", "Write reply from verified claims only", "Text with [E#] citations"],
                ["Evaluator", "Yes + code", "Citation presence and existence, judge score", "Groundedness and citation correctness"]], [2.6, 2.2, 6.2, 6.0])
    # 10
    S += chap(10, "Implementation")
    S += [P(f"The code is in {a.repo or 'the repository'}. Main parts: mcp_server/ (tools and server), app/agents/ (five agents), app/gate.py (decision rules), "
            "app/orchestrator.py (workflow), app/llm.py (Gemini wrapper with rate throttling and 429 backoff), app/cost.py (token cost), app/main.py (API and web page), "
            "run_eval.py (evaluation harness) and tests/ (unit and contract tests). The model is called through one wrapper so the provider can be swapped by configuration. "
            "A Docker image runs both the MCP server and the API through start.sh.")]
    # 11
    S += chap(11, "Hallucination Detection")
    S += table([["Layer", "Control", "Where"],
                ["L1", "Every claim must carry an evidence citation", "Responder rules; Evaluator"],
                ["L2", "Cited ids must exist in the retrieved evidence", "Evaluator code check"],
                ["L3", "Claim-level verification against evidence text", "Verifier"],
                ["L4", "Contradictory sources are detected and escalated", "Verifier; gate"],
                ["L5", "Retrieval sufficiency: weak or absent evidence gives INSUFFICIENT_INFO", "search_policy floor; gate"],
                ["L6", "Closed-world, false-premise and injection test cases", "Test suite"],
                ["L7", "Human audit of a sample of replies", "docs/human_audit.csv"]], [1.4, 10.0, 5.6])
    au = audit_summary()
    S += [P(f"Human audit (L7): {au[0]} replies reviewed. " + (", ".join(f"{k}: {v}" for k, v in au[1].items()) if au[1] else "") if au else
            "Human audit (L7): not yet performed. A template, docs/human_audit_template.csv, lists the replies to review. The audit result must be added here before submission.")]
    # 12
    S += chap(12, "Evaluation Methodology")
    S += [P("Each case has a ticket, an expected outcome category, and the set of acceptable decision codes. A case passes when the decision is acceptable, the reply is grounded, and no unsafe approval occurs. "
            "The same suite runs against the baseline (one model call, no tools, no gate) and the multi-agent system with the same model, settings and data. "
            "Metrics: task success, decision accuracy, unsafe-approval rate, claim-level hallucination rate, groundedness, evidence coverage, citation correctness, mean and P95 latency, "
            "tool success rate (excluding deliberately injected failures) and cost per query. Free-tier use costs nothing; the reported cost is the equivalent paid-tier cost at the prices below.")]
    S += table([["Item", "Value"], ["Model", model], ["Input price per 1M tokens (USD)", str(pricing.get("input_price_per_1m", ""))],
                ["Output price per 1M tokens (USD)", str(pricing.get("output_price_per_1m", ""))],
                ["Pricing date checked", str(pricing.get("date_checked") or "NOT SET: set PRICING_DATE_CHECKED and rerun")]], [6.0, 11.0])
    # 13
    S += chap(13, "Test Cases")
    S += [P(f"The suite has {sum(cat.values()) or 30} cases." if cases else "Test cases file not found.")]
    S += table([["Category", "Cases", "What it tests"]] + [[k, str(v), w] for k, v, w in [
        (k, cat.get(k, 0), w) for k, w in [("supported", "Normal tickets with full evidence"), ("unknown", "Orders or policies that do not exist"),
         ("false_premise", "Customer states something the data contradicts"), ("conflict", "Two policy documents disagree"),
         ("numerical", "Refund and fee arithmetic"), ("tool_failure", "MCP server down or malformed response"),
         ("prompt_injection", "Instructions hidden in the ticket or a document"), ("out_of_domain", "Requests outside customer support")]]], [3.6, 1.8, 11.6])
    # 14
    S += chap(14, "Metrics and Results")
    if prelim:
        S += [P("PRELIMINARY." + stamp, d.ParagraphStyle("w2", parent=d.BODY, backColor=d.TAPE, borderPadding=5))]
    def g(dct, k, kind="num"):
        return fmt(dct.get(k), kind) if dct else "n/a"
    ms = [("Task success (accuracy)", "task_success_rate", "pct"), ("Decision accuracy", "decision_accuracy", "pct"),
          ("Groundedness", "mean_groundedness", "pct"), ("Claim hallucination rate", "mean_claim_hallucination_rate", "pct"),
          ("Case-level hallucination rate", "case_level_hallucination_rate", "pct"), ("Unsafe approval rate", "unsafe_approval_rate", "pct"),
          ("Mean latency", "mean_latency_ms", "ms"), ("P95 latency", "p95_latency_ms", "ms"), ("Cost per query (equivalent)", "mean_cost_per_query_usd", "usd"),
          ("Tool success rate", "tool_success_rate_excl_injected_failures", "pct"), ("Overall reliability", "reliability", "pct")]
    S += table([["Metric", "Single-agent baseline", "Multi-agent + MCP"]] + [[n, ("N/A" if k.startswith("tool_") else g(bl, k, kd)), g(ma, k, kd)] for n, k, kd in ms], [6.0, 5.5, 5.5])
    S += [P(f"Cases run: baseline {n_bl}, multi-agent {n_ma}.", SMALL)]
    pc = ma.get("pass_by_category", {})
    if pc:
        S += [P("Pass by category (multi-agent)", H3)] + table([["Category", "Passed"]] + [[k, v] for k, v in pc.items()], [6.0, 4.0])
    fails = [r for r in rows if r.get("pass", "").lower() not in ("true", "1")]
    S += [P("Failed cases", H3)]
    if rows:
        S += table([["Case", "System", "Expected", "Got", "Note"]] + [[r["test_id"], r["system"], r.get("expected_decisions", ""), r.get("decision", ""), (r.get("notes") or "")[:90]] for r in fails[:20]], [1.6, 2.8, 3.8, 3.8, 5.0]) if fails else [P("No failed cases in the committed results." + (" (Only the cases listed above were run.)" if prelim else ""))]
    S += [P("Interpretation", H3),
          P("The table above is the evidence. The discussion must state, from the final numbers, whether hypothesis H1 (lower hallucination and unsafe-approval rate than the baseline) "
            "and H2 (higher cost and latency) hold, and by how much. " + ("Because the run is preliminary, no conclusion is drawn here." if prelim else "See the Observation paragraph generated below.")) ]
    if not prelim and bl and ma:
        def dlt(k): return float(ma.get(k, 0)) - float(bl.get(k, 0))
        S += [P(f"Observation: against the baseline, task success changed by {dlt('task_success_rate') * 100:+.1f} points, unsafe-approval rate by {dlt('unsafe_approval_rate') * 100:+.1f} points, "
                f"mean latency by {dlt('mean_latency_ms') / 1000:+.1f} s and cost per query by {dlt('mean_cost_per_query_usd'):+.6f} USD.")]
    # 15
    S += chap(15, "Cost Analysis")
    S += [P("Cost per query is computed from the input and output tokens of every model call: tokens divided by one million times the price, summed over the agents. Because the Gemini free tier was used, the actual spend was zero; "
            "the figure below is what the same tokens would cost on the paid tier at the stated prices. The per-agent breakdown is in 09_Cost_Analysis.xlsx.")]
    S += table([["Item", "Value"], ["Mean cost per query (multi-agent)", g(ma, "mean_cost_per_query_usd", "usd")], ["Mean cost per query (baseline)", g(bl, "mean_cost_per_query_usd", "usd")],
                ["Total answer cost", g(ma, "total_answer_cost_usd", "usd")], ["Total evaluation (judge) cost", g(ma, "total_evaluation_cost_usd", "usd")]], [8.0, 9.0])
    # 16
    S += chap(16, "Deployment")
    S += [P(f"The system runs as a single Docker container on Render's free plan ({a.url or 'URL'}). start.sh starts the MCP server on 127.0.0.1:8001, waits for the port, then starts the API on Render's port. "
            "render.yaml defines the service, the /health check and the environment; LLM_API_KEY is entered in the dashboard and MCP_AUTH_TOKEN is generated by Render. See 10_Deployment_Guide.pdf.")]
    # 17
    S += chap(17, "Security and Failure Handling")
    S += bullets(["Secrets only in environment variables; .env is ignored by Git and the submission builder aborts if it finds a key.",
                  "MCP server needs a bearer token and listens on loopback in production; only the API is public.",
                  "Retrieved text is wrapped as data; a planted instruction in a policy document and one in a ticket are test cases.",
                  "Rate limiting on the public endpoint; evaluation endpoint disabled in production.",
                  "A tool or model failure ends in a controlled message and a logged error, never an invented answer.",
                  "The calculator uses an AST allow-list, not eval()."])
    # 18
    S += chap(18, "Baseline and Ablation Study")
    S += [P("Variant A (single model, no tools) is the baseline and variant D (full system) is the proposed system; both are measured in Chapter 14. "
            "Variants B (single model plus retrieval) and C (agents without MCP tools) are described in the guide's ablation table and are not implemented in this project, so no result is claimed for them.")]
    # 19
    S += chap(19, "Limitations")
    S += bullets(["The data is a small synthetic store (nine orders, twelve policy documents); results do not transfer to a real store without new data.",
                  "Thirty cases give wide confidence intervals; differences of one or two cases are not statistically meaningful.",
                  "The Evaluator uses a model as judge, which can share the generator's blind spots; the human audit is the check on it.",
                  "Latency on the free tier is dominated by deliberate rate throttling and cold starts, not by the design.",
                  "Free-tier cost is an equivalent figure; prices and model names change and were checked only on the date recorded.",
                  "Only English text was tested."])
    if prelim:
        S += bullets(["The evaluation committed so far is a three-case smoke run, so conclusions about the baseline comparison cannot yet be drawn."])
    # 20
    S += chap(20, "Conclusion and Future Work")
    S += [P("The project delivers a working, deployed, measured multi-agent support system in which tools, rules and verification limit what the model can do. "
            + ("The final conclusion depends on the full 30-case run, which must be completed and the report regenerated. " if prelim else "The measured comparison in Chapter 14 states what that control costs. ")
            + "Future work: a larger and noisier ticket set, the ablation variants B and C, a persistent database behind the MCP server, user authentication, and a second human rater for the audit.")]
    # 21
    S += chap(21, "References")
    S += bullets(["Model Context Protocol specification: https://modelcontextprotocol.io/specification/",
                  "MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk",
                  "Google Gemini API pricing and models: https://ai.google.dev/gemini-api/docs/pricing",
                  "FastAPI documentation: https://fastapi.tiangolo.com/",
                  "Multi-Agent MCP Student Implementation Guide (course material).",
                  f"Project repository: {a.repo or '(add)'}"])
    tpl = ROOT / "docs" / "human_audit_template.csv"
    tpl.parent.mkdir(parents=True, exist_ok=True)
    with open(tpl, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["test_id", "ticket", "reply", "verdict (correct / partly / wrong)", "unsupported_claim_found (yes/no)", "comment"])
        for r in rows:
            if r.get("system") == "multi_agent":
                w.writerow([r["test_id"], r["ticket"], r["actual"], "", "", ""])
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    d._build(str(out), "Final Report", meta, S)
    print(f"Wrote {out}" + ("  [PRELIMINARY: rerun after the full evaluation]" if prelim else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())