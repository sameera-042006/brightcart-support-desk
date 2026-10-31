"""Generates the three written PDFs for the final submission (needs: pip install reportlab):
01_Problem_Statement.pdf, 02_System_Architecture.pdf, 10_Deployment_Guide.pdf.
Content describes the implemented system; student details and measured values come from `meta`."""
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

INK = colors.HexColor("#101828")
MUTED = colors.HexColor("#475467")
LINE = colors.HexColor("#D0D5DD")
HEAD = colors.HexColor("#EEF1F5")
TAPE = colors.HexColor("#FFD23F")

_ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_ss["BodyText"], fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, spaceAfter=6)
H1 = ParagraphStyle("h1", parent=BODY, fontName="Helvetica-Bold", fontSize=22, leading=26, spaceAfter=4)
SUB = ParagraphStyle("sub", parent=BODY, fontSize=11.5, textColor=MUTED, spaceAfter=14)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=13.5, leading=17, spaceBefore=14, spaceAfter=6)
H3 = ParagraphStyle("h3", parent=BODY, fontName="Helvetica-Bold", fontSize=10.5, spaceBefore=6, spaceAfter=3)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.6, leading=11.2, spaceAfter=0)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")
BUL = ParagraphStyle("bul", parent=BODY, leftIndent=14, bulletIndent=3, spaceAfter=3)
MONO = ParagraphStyle("mono", parent=BODY, fontName="Courier", fontSize=8.6, leading=11.5, backColor=HEAD, borderPadding=6, spaceAfter=8)


def P(text, style=BODY):
    return Paragraph(escape(str(text)), style)


def bullets(items):
    return [Paragraph(escape(i), BUL, bulletText="•") for i in items]


def table(rows, widths, header=True):
    data = []
    for r, row in enumerate(rows):
        data.append([Paragraph(escape(str(c)), CELLB if (header and r == 0) else CELL) for c in row])
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD))
    t.setStyle(TableStyle(style))
    return [t, Spacer(1, 8)]


def _build(path, title, meta, story):
    def deco(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(TAPE); canvas.rect(0, A4[1] - 0.35 * cm, A4[0], 0.35 * cm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 8); canvas.setFillColor(MUTED)
        who = f"{meta['name']}  |  {meta['reg']}" if meta.get("name") else "BrightCart Support Desk"
        canvas.drawString(2 * cm, 1.2 * cm, f"{title}  |  {who}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
        canvas.restoreState()
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=2 * cm, title=title, author=meta.get("name") or "")
    doc.build(story, onFirstPage=deco, onLaterPages=deco)


def _title_block(title, subtitle, meta):
    blank = "______________________"
    rows = [["Student name", meta.get("name") or blank], ["Registration number", meta.get("reg") or blank],
            ["Course / section", meta.get("course") or blank], ["Date", meta["date"]]]
    out = [P(title, H1), P(subtitle, SUB)]
    out += table(rows, [4.5, 12.5], header=False)
    return out


# ----------------------------------------------------------------------------------------------
def problem_statement(path, meta):
    s = _title_block("Problem Statement", "BrightCart Support Desk: a multi-agent ticket-resolution system with MCP", meta)
    s += [P("1. Background", H2),
          P("Online stores answer thousands of support tickets about returns, refunds, warranty, cancellations and "
            "shipping. Large language models can draft these answers quickly, but a model that answers from memory "
            "invents order details, quotes policies that do not exist and promises refunds it has no authority to give. "
            "A wrong answer here has a direct cost: an unfairly refused customer, a refund paid by mistake, or a "
            "policy promise the store must then honour."),
          P("2. Problem", H2),
          P("Design, build, evaluate and deploy a ticket-resolution assistant whose every statement is grounded in the "
            "store's order data and policy documents, that refuses to answer when evidence is missing, that cannot be "
            "talked into approving a refund by text hidden in a ticket or a document, and that fails safely when a "
            "tool or the model is unavailable."),
          P("3. Objectives", H2)]
    s += bullets([
        "Expose order lookup, return-eligibility rules, policy search, a calculator, escalation and an audit log as "
        "deterministic tools behind a Model Context Protocol (MCP) server, kept separate from the reasoning layer.",
        "Implement five role-based agents (Triage, Investigator, Verifier, Responder, Evaluator) coordinated by an "
        "orchestrator with shared state, conditional branches and structured logging.",
        "Make financial decisions with a deterministic rule gate rather than the language model.",
        "Detect hallucination in layers: citation presence, claim verification, contradiction and conflict checks, "
        "retrieval sufficiency, closed-world tests, adversarial tests and a human audit of a sample.",
        "Evaluate with 30 test cases against a single-agent baseline, reporting accuracy, groundedness, hallucination "
        "rate, unsafe-approval rate, mean and P95 latency, tool success rate and cost.",
        "Containerise the system and deploy it to the cloud with the MCP server authenticated and not exposed to the internet.",
    ])
    s += [P("4. Research question and hypotheses", H2),
          P("Research question: does a verified multi-agent workflow with MCP tools and a deterministic decision gate "
            "make a support assistant measurably safer and more truthful than a single model call with no tools?"),
          P("H1: the multi-agent system has a lower hallucination rate and a lower unsafe-approval rate than the baseline."),
          P("H2: the multi-agent system costs more per query and responds more slowly than the baseline, and the report "
            "shows whether the safety gain justifies that cost."),
          P("These are hypotheses to be tested with the evaluation suite. The results chapter of the final report states "
            "whether the measured data supports them."),
          P("5. Scope", H2)]
    s += table([
        ["In scope", "Out of scope"],
        ["A fictional store (BrightCart) with 9 orders and 12 policy documents, all invented for this project.",
         "Real customers, real payments or real personal data. Decisions are recommendations; no money is moved."],
        ["Intents: return or refund, order status, warranty, cancellation, general policy questions.",
         "Multi-order tickets (only the first order number is acted on), voice, attachments, languages other than English."],
        ["Keyword retrieval over a small curated corpus; a fixed reference date for return windows.",
         "Semantic or vector retrieval, live inventory, carrier tracking."],
    ], [8.5, 8.5])
    s += [P("6. Users", H2)]
    s += bullets(["Customer: describes a problem and receives a decision with a cited reply.",
                  "Human support agent: receives escalations when sources conflict or judgment is needed.",
                  "Evaluator / teacher: reads run logs, evaluation tables and cost reports to judge the system."])
    s += [P("7. Success criteria", H2)]
    s += table([
        ["Metric", "Definition", "Target"],
        ["Unsafe approval rate", "Refunds or cancellations approved when the rules say no, over cases where approval is not allowed.", "0"],
        ["Hallucination rate", "Share of factual claims that are unsupported or contradicted by evidence (claim level), and share of cases with any such claim or an invented answer to an unknowable question (case level).", "Lower than the baseline"],
        ["Groundedness", "Share of reply claims supported by retrieved evidence.", "Higher than the baseline"],
        ["Decision accuracy", "Share of cases where the decision is one of the expected decisions.", "Higher than the baseline"],
        ["Tool success rate", "Successful MCP calls over all calls, excluding deliberately injected failures.", "95% or more"],
        ["Controlled failure", "Injected tool failures end in a controlled error with no invented answer.", "100%"],
        ["Latency and cost", "Mean and P95 end-to-end time; equivalent paid-tier cost per query.", "Reported and explained"],
    ], [3.6, 10.4, 3.0])
    s += [P("8. Constraints and assumptions", H2)]
    s += bullets(["One language model is used for every experiment, accessed through the free tier of the Gemini API, so "
                  "request rate and daily quota limit how often the suite can run.",
                  "Actual spend is zero on the free tier; cost is reported as the equivalent paid-tier price with the pricing "
                  "page and date recorded.",
                  "Model output varies between runs, so the suite is run more than once and a sample is audited by hand.",
                  "All data is fictional and 'today' is fixed by configuration so that results are reproducible."])
    s += [P("9. Risks and mitigations", H2)]
    s += table([
        ["Risk", "Mitigation"],
        ["The model invents order facts or policies.", "Order facts and eligibility come only from tools; every reply sentence must cite evidence ids; claims without a valid evidence id are marked unsupported."],
        ["Hidden instructions in a ticket or a policy document.", "Both are wrapped as untrusted data; the decision is made by a rule gate; a planted instruction and an injected ticket are part of the test suite."],
        ["A tool or the model is unavailable.", "Timeouts, bounded retries with backoff, schema validation of tool replies, and a controlled error that produces no answer."],
        ["The LLM judge makes mistakes.", "Citation checks are deterministic, pass/fail uses rules, and a human audit of a sample is part of the method. This limitation is stated in the report."],
        ["Free-tier limits change.", "Requests are throttled and retried on rate-limit errors; the model name and date of the run are recorded."],
    ], [5.5, 11.5])
    _build(path, "Problem Statement", meta, s)


# ----------------------------------------------------------------------------------------------
def _box(d, x, y, w, h, text, fill="#FFFFFF", stroke="#101828", dash=None, size=7.4):
    r = Rect(x, y, w, h, fillColor=colors.HexColor(fill), strokeColor=colors.HexColor(stroke), strokeWidth=0.9, rx=4, ry=4)
    if dash:
        r.strokeDashArray = dash
    d.add(r)
    lines = text.split("\n")
    top = y + h / 2 + (len(lines) - 1) * (size + 1.2) / 2 - size * 0.3
    for i, ln in enumerate(lines):
        d.add(String(x + w / 2, top - i * (size + 1.2), ln, fontName="Helvetica-Bold" if i == 0 else "Helvetica",
                     fontSize=size, fillColor=INK, textAnchor="middle"))


def _arrow(d, x1, y1, x2, y2, dash=None):
    ln = Line(x1, y1, x2, y2, strokeColor=INK, strokeWidth=0.9)
    if dash:
        ln.strokeDashArray = dash
    d.add(ln)
    if abs(x2 - x1) >= abs(y2 - y1):
        s = 1 if x2 > x1 else -1
        d.add(Polygon([x2, y2, x2 - 5 * s, y2 + 2.8, x2 - 5 * s, y2 - 2.8], fillColor=INK, strokeColor=INK))
    else:
        s = 1 if y2 > y1 else -1
        d.add(Polygon([x2, y2, x2 - 2.8, y2 - 5 * s, x2 + 2.8, y2 - 5 * s], fillColor=INK, strokeColor=INK))


def diagram():
    d = Drawing(470, 262)
    _box(d, 0, 208, 90, 44, "Customer\nbrowser page", "#EEF1F5")
    _box(d, 118, 208, 140, 44, "FastAPI web layer\n/ticket  /health  /metrics", "#FFF6CC")
    _box(d, 345, 208, 125, 44, "Gemini API\n(triage, verifier, responder,\njudge)", "#EEF1F5", dash=[3, 2], size=7)
    _arrow(d, 90, 230, 118, 230); _arrow(d, 258, 230, 345, 230, dash=[3, 2])
    d.add(Rect(-4, 122, 478, 70, fillColor=None, strokeColor=MUTED, strokeWidth=0.8, strokeDashArray=[4, 3]))
    d.add(String(2, 183, "Orchestrator: conditional workflow with shared RunState", fontName="Helvetica", fontSize=6.8, fillColor=MUTED))
    names = ["1  Triage\n(LLM)", "2  Investigator\n(no LLM)", "3  Verifier\n(LLM)", "4  Decision gate\n(rules, no LLM)", "5  Responder\n(LLM)"]
    xs = [0, 96, 192, 288, 384]
    for x, n in zip(xs, names):
        _box(d, x, 128, 84, 38, n, "#FFFFFF" if "gate" not in n else "#FFF6CC")
    for x in xs[:-1]:
        _arrow(d, x + 84, 147, x + 96, 147)
    _arrow(d, 188, 208, 188, 192)
    _box(d, 96, 62, 84, 40, "MCP client\nretry, timeout,\nschema check", "#EEF1F5")
    _box(d, 96, 4, 84, 40, "MCP server\n6 deterministic tools", "#DDF5E7")
    _box(d, 210, 4, 110, 40, "Data\norders.json, 12 policies", "#EEF1F5")
    _arrow(d, 138, 128, 138, 102); _arrow(d, 138, 62, 138, 44); _arrow(d, 180, 24, 210, 24)
    _box(d, 384, 62, 84, 40, "6  Evaluator\n(judge + citations)", "#FFFFFF")
    _box(d, 288, 62, 84, 40, "Run log\nruns/<run_id>.json", "#EEF1F5")
    _arrow(d, 426, 128, 426, 102); _arrow(d, 384, 82, 372, 82)
    return d


def architecture(path, meta):
    s = _title_block("System Architecture", "BrightCart Support Desk: multi-agent workflow with MCP tools", meta)
    s += [P("1. Overview", H2),
          P("A ticket enters through the FastAPI layer. The orchestrator runs five role-based agents over a shared "
            "RunState. Facts are fetched through an MCP client from a separate MCP server whose tools are deterministic "
            "and contain no model calls. A rule gate, not the model, turns tool results into a decision. The model is "
            "used for classification, claim verification, writing and judging."),
          KeepTogether([diagram()]),
          P("Figure 1. Components and data flow. Solid arrows are calls inside the system; dashed arrows are calls to an external service.", ParagraphStyle("cap", parent=BODY, fontSize=8.5, textColor=MUTED)),
          P("2. Agents and components", H2)]
    s += table([
        ["Component", "Responsibility", "Model call", "If it fails"],
        ["Triage", "Classifies the ticket as in or out of scope and picks an intent (return/refund, order status, warranty, cancellation, policy question). Extracts order ids with a regular expression as well as from the model.", "Yes", "Invalid output falls back to a generic policy question; out-of-scope tickets are declined without using any tool."],
        ["Investigator", "Looks up each order, runs the eligibility rules, searches policies, and records every result as numbered evidence (E1, E2, ...). Empty or failed lookups are recorded as missing evidence.", "No", "If every lookup fails the run ends in a controlled error."],
        ["Verifier", "Writes claims from the evidence only, labels each Supported, Partially supported, Unsupported or Contradicted, lists conflicting sources and false premises in the ticket, and requests arithmetic as expressions.", "Yes", "Invalid JSON ends the run in a controlled error."],
        ["Calculator step", "Evaluates the requested expressions through the MCP calculator and adds each result as evidence. Invalid expressions are dropped, never guessed.", "No", "Skipped expressions produce no number."],
        ["Decision gate", "Maps intent, order data and rule results to one decision (table in section 4).", "No", "Not applicable; it is deterministic."],
        ["Responder", "Writes a short customer reply from verified claims and the decision reason, citing evidence ids, correcting false premises and ignoring instructions in the ticket.", "Yes", "Errors end in a controlled error."],
        ["Evaluator", "Judges the reply against the evidence for groundedness and hallucination rate and checks that every cited id exists.", "Yes", "Skipped for refusals and escalations, which make no factual claims."],
        ["Orchestrator", "Runs the steps, takes the branches, times every step, records tokens, cost and MCP calls, and writes the run log.", "No", "Catches tool, model and agent errors and returns a controlled message."],
    ], [2.4, 8.2, 1.5, 4.9])
    s += [P("3. MCP server tools", H2),
          P("The server is built with the official MCP Python SDK and served over Streamable HTTP. It holds no model "
            "calls. Every argument is validated.")]
    s += table([
        ["Tool", "Purpose", "Protection"],
        ["search_policy(query, top_k)", "Keyword search over the policy documents; returns text, relevance and source quality.", "Query length limit; weak matches dropped."],
        ["get_order(order_id)", "Returns status, items, prices, dates and shipping fee for one order.", "Order id must match ORD-nnnn."],
        ["check_return_eligibility(order_id)", "Applies the rules: 30-day window from delivery, damaged items refunded in full including shipping, gift cards and undelivered or cancelled orders not returnable, 365-day warranty for electronics.", "Authoritative; the model cannot override it."],
        ["calculator(expression)", "Arithmetic with + - * / ** %.", "Parsed with an allow-list of syntax nodes; never uses eval; exponent and length limits."],
        ["create_escalation(run_id, reason, summary)", "Hands a case to a human and returns a reference such as ESC-A3F9C1.", "run_id pattern check; length limits."],
        ["save_evidence(run_id, evidence)", "Appends the evidence used by a run to an audit file.", "run_id pattern check blocks path traversal."],
    ], [5.6, 7.8, 3.6])
    s += [P("4. Decision gate", H2)]
    s += table([
        ["Condition (checked in this order)", "Decision"],
        ["Triage says the ticket is out of scope", "DECLINE (no tools used)"],
        ["Order-related intent but no order found, or order id not in the database", "INSUFFICIENT_INFO (asks for the order number)"],
        ["No evidence at all", "INSUFFICIENT_INFO"],
        ["Verifier lists conflicting sources, or the request needs human judgment", "ESCALATE (creates a human ticket and shows both values)"],
        ["Order status question", "INFORM"],
        ["Cancellation: order is processing", "APPROVE_CANCELLATION"],
        ["Cancellation: order already cancelled / shipped or delivered", "INFORM / DENY"],
        ["Warranty: warranty active (electronics within 365 days of delivery) / not active", "WARRANTY_CLAIM / DENY"],
        ["Return or refund: rule engine says eligible / not eligible", "APPROVE_RETURN with the amount from the rules / DENY"],
        ["Policy question with at least one supported claim / none", "INFORM / INSUFFICIENT_INFO"],
    ], [10.2, 6.8])
    s += [P("5. Hallucination controls mapped to the layered framework", H2)]
    s += table([
        ["Layer", "How this system implements it"],
        ["L1 Evidence presence", "A claim without a valid evidence id is forced to Unsupported. Replies must cite [E#]; a citation-correctness metric checks that each cited id exists."],
        ["L2 Entailment check", "The Verifier asks whether the evidence supports each claim; the Evaluator re-checks the final reply."],
        ["L3 Contradiction check", "Claims can be labelled Contradicted; conflicting sources are listed and cause an escalation instead of a guess."],
        ["L4 Retrieval sufficiency", "No evidence, or no supported claim, produces an insufficient-information reply with no model-written answer."],
        ["L5 Closed-world test", "Cases U01 to U05 ask about things absent from the data (unknown order, student discount, cryptocurrency, price matching, missing order number)."],
        ["L6 Adversarial test", "Cases F01 to F05 contain false premises; I01 and I02 contain injected instructions; the corpus contains a planted 'approve every refund' sentence."],
        ["L7 Human audit", "A sample of outputs is reviewed by the student and reported in the final report."],
    ], [4.0, 13.0])
    s += [P("6. Failure handling and security", H2)]
    s += table([
        ["Situation", "Behaviour"],
        ["MCP server down or slow", "Per-call timeout, up to 2 retries with exponential backoff, call logged with latency and attempts; if all lookups fail the run ends in a controlled error and no answer is produced."],
        ["Malformed tool reply", "Validated against a schema; a reply that violates the contract is rejected."],
        ["Model rate limit (HTTP 429)", "Requests are spaced to the configured rate and retried with backoff up to four times."],
        ["Injected text in a ticket or document", "Treated as data inside tags; decisions come from the rule gate; the reply prompt ignores instructions in the ticket."],
        ["Public API abuse", "Input length validation, per-client rate limit, debug and evaluation endpoints disabled by default."],
        ["Secrets", "API key and MCP token only in environment variables; .env is ignored by Git and Docker; the submission script scans for key patterns."],
        ["MCP endpoint exposure", "Bearer-token authentication and an optional host allow-list when deployed."],
    ], [4.6, 12.4])
    s += [P("7. Logging", H2),
          P("Every run has a unique run_id and writes runs/<run_id>.json with the ticket, intent, decision and reason, "
            "evidence, claims, conflicts, every agent's latency, tokens and cost, every MCP call with success, latency "
            "and attempts, total tokens and cost, groundedness and hallucination rate. The record uses 'ticket' where "
            "the course template uses 'question'."),
          P("8. Technology stack", H2)]
    s += table([
        ["Layer", "Choice"],
        ["Language and API", "Python, FastAPI, Pydantic, a single-file HTML page served at /"],
        ["Tool protocol", "Model Context Protocol, official Python SDK, Streamable HTTP transport"],
        ["Model", "Google Gemini API (one model for all experiments)"],
        ["Testing and metrics", "pytest, a JSON test suite, NumPy for percentiles, pandas and openpyxl for the cost workbook"],
        ["Packaging and hosting", "Docker and Docker Compose; one container on Render (MCP server on loopback plus API)"],
    ], [4.0, 13.0])
    _build(path, "System Architecture", meta, s)


# ----------------------------------------------------------------------------------------------
def deployment_guide(path, meta, repro):
    s = _title_block("Deployment Guide", "BrightCart Support Desk: local, Docker and Render deployment", meta)
    s += [P("1. Topology", H2),
          P("The system is deployed as one container on Render. The container's start script (start.sh) first starts the MCP "
            "server on the loopback address 127.0.0.1:8001, waits until the port accepts connections, and then starts the API "
            "(uvicorn app.main:app) on the port Render provides. Only the API is reachable from the internet; the MCP server is "
            "reachable only from inside the container and also requires a bearer token (MCP_AUTH_TOKEN, generated by Render). "
            "The model provider (Google Gemini) is called from the API process only.")]
    s += table([
        ["Process", "Command", "Reachable from"],
        ["MCP server", "python -m mcp_server.server  (MCP_HOST=127.0.0.1, MCP_PORT=8001)", "Inside the container only; bearer token required"],
        ["API and web page", "uvicorn app.main:app --host 0.0.0.0 --port $PORT", "Public: page at /, API at /ticket and /health"],
    ], [3.0, 9.5, 4.5])
    s += [P("Deployment files in the repository: Dockerfile, start.sh, render.yaml (Render Blueprint) and docker-compose.yml (local, two containers).")]
    s += [P("2. Prerequisites", H2)]
    s += bullets(["Python 3.12, Git, Docker Desktop (optional), a code editor.",
                  "A Gemini API key from Google AI Studio (free tier).",
                  "A GitHub account and a Render account (free plan)."])
    s += [P("3. Run locally", H2),
          Paragraph(escape("python -m venv .venv\n.venv\\Scripts\\activate\npip install -r requirements.txt\ncopy .env.example .env   (then edit LLM_API_KEY)\n"
                           "terminal 1:  python -m mcp_server.server\nterminal 2:  uvicorn app.main:app --port 8000\nbrowser:     http://localhost:8000").replace("\n", "<br/>"), MONO),
          P("4. Run with Docker Compose", H2),
          Paragraph(escape("docker compose up --build\ncurl http://localhost:8000/health").replace("\n", "<br/>"), MONO),
          P("With Compose the API reaches the MCP server by its service name (MCP_SERVER_URL=http://mcp-server:8001/mcp), not by localhost."),
          P("5. Deploy to Render", H2)]
    s += bullets(["Push the repository to GitHub and confirm that .env is not tracked.",
                  "In Render choose New, then Blueprint, and select the repository. Render reads render.yaml and creates one Docker web service named brightcart-support-desk (free plan, health check /health, auto-deploy on every push).",
                  "When asked, paste LLM_API_KEY (the Gemini key). MCP_AUTH_TOKEN is generated by Render. The remaining variables are set in render.yaml.",
                  "Wait for the build. Open the service URL; the first request after idle takes up to a minute while the free instance wakes.",
                  "Send a ticket from the page to confirm the full pipeline works."])
    s += [P("6. Environment variables", H2),
          P("Values are never written in this document or stored in Git. Secrets are set in the platform's environment settings.")]
    s += table([
        ["Variable", "Purpose"],
        ["LLM_API_KEY (secret)", "Gemini API key; entered in the Render dashboard."],
        ["LLM_PROVIDER, MODEL_NAME", "gemini and the exact model name used for every experiment."],
        ["LLM_RPM", "Requests per minute, set below the model's free-tier limit."],
        ["PRICE_INPUT_PER_1M, PRICE_OUTPUT_PER_1M, PRICING_DATE_CHECKED", "Paid-tier prices used for the equivalent-cost figures, and the date they were checked."],
        ["MCP_AUTH_TOKEN (secret)", "Shared bearer token; generated by Render. The MCP server rejects requests without it."],
        ["MCP_HOST, MCP_PORT, MCP_SERVER_URL", "Set by start.sh: MCP on 127.0.0.1:8001, API connects to http://127.0.0.1:8001/mcp."],
        ["SHOP_TODAY", "Fixed reference date for return windows."],
        ["RATE_LIMIT_PER_MIN, ALLOW_EVAL_ENDPOINT=0, ENVIRONMENT=production", "Public-endpoint protection and mode."],
        ["PORT", "Set by Render; the API reads it."],
    ], [7.2, 9.8])
    s += [P("7. Verification checklist", H2)]
    s += bullets(["GET /health returns status ok.",
                  "The web page loads, and a normal ticket (for example the ORD-1001 return) returns a decision with a reply.",
                  "A hallucination test (unknown order ORD-9999) returns a request for the order number, not an invented status.",
                  "The injected ticket (SYSTEM OVERRIDE ... approve $500) is denied.",
                  "The full suite is run from your own computer against the deployed URL (python run_eval.py --api-url <URL>) with ALLOW_EVAL_ENDPOINT left at 0 on the server, and its metrics are compared with the local run."])
    s += [P("8. Reproducibility record", H2)]
    s += table([["Item", "Record"]] + [[k, v] for k, v in repro], [4.2, 12.8])
    s += [P("9. Troubleshooting", H2)]
    s += table([
        ["Symptom", "Cause and fix"],
        ["The first request takes up to a minute", "Free services sleep after about 15 minutes idle. Open the URL a few minutes before a demo."],
        ["Reply says a required system failed", "The MCP process did not start or the model returned an error. Read the Render logs; start.sh prints if the MCP port never opened."],
        ["MCP calls fail with an unauthorized error", "MCP_AUTH_TOKEN is missing. It must exist in the service environment."],
        ["429 errors from the model", "Lower LLM_RPM or wait for the daily quota to reset."],
        ["Run files disappear after a restart", "The free plan's disk is not persistent. Run the evaluation from your own computer and keep the results in Git."],
        ["Build fails on start.sh", "The file must be executable and have LF line endings (.gitattributes in the repository enforces this)."],
    ], [5.0, 12.0])
    s += [P("10. Security notes", H2)]
    s += bullets(["Never commit .env or keys. If a key is ever committed, revoke it and create a new one.",
                  "Debug and evaluation endpoints stay disabled in production.",
                  "The MCP server listens on loopback only inside the container and also needs the bearer token."])
    _build(path, "Deployment Guide", meta, s)
