# BrightCart Support Desk: Multi-Agent Ticket Resolution with MCP (Gemini)

A customer writes a support ticket ("Can I return the headphones from ORD-1001?"). Five agents resolve it using
real order data and store policies served by an **MCP tool server**. A **deterministic decision gate** (not the AI)
decides refunds, so the system can be tested for hallucination, unsafe approvals, prompt injection and tool failure.
All store data is fictional demo data.

```
Customer ticket -> FastAPI /ticket -> Orchestrator
   Triage (LLM)  -> intent, order ids, in/out of scope
   Investigator  -> MCP client -> MCP server: get_order, check_return_eligibility, search_policy   (no LLM)
   Verifier (LLM)-> claims + SUPPORTED/PARTIAL/UNSUPPORTED/CONTRADICTED, conflicts, false premises
   MCP calculator-> all arithmetic (the model never computes)
   Decision gate -> APPROVE_RETURN / DENY / WARRANTY_CLAIM / APPROVE_CANCELLATION / INFORM / INSUFFICIENT_INFO / ESCALATE / DECLINE
   Responder (LLM)-> cited customer reply        Evaluator (LLM judge) -> groundedness, hallucination rate
```
MCP is the capability boundary (data + rules + side effects). The orchestrator is the reasoning layer.

## 1. Setup (VS Code terminal)
```bash
python -m venv .venv
.venv\Scripts\activate              # Windows   |   source .venv/bin/activate  (Linux/macOS)
pip install -r requirements.txt
pip freeze > requirements.lock.txt  # record exact versions in your report
copy .env.example .env              # edit: LLM_API_KEY (free key: https://aistudio.google.com/apikey), PRICING_DATE_CHECKED
```
Check your model's free requests/minute in AI Studio and set `LLM_RPM` below it.

## 2. Run (three terminals, venv active in each)
| Terminal | Command | Expected |
|---|---|---|
| 1 | `python -m mcp_server.server` | Uvicorn running on http://127.0.0.1:8001 |
| 2 | `python -c "from app.mcp_client.client import MCPToolClient as C; c=C(); print(c.list_tools()); print(c.check_return_eligibility('ORD-1001'))"` | 6 tool names + an eligibility record |
| 2 | `python -m app.orchestrator "I want to return the headphones from order ORD-1001. Am I eligible?"` | cited reply + `runs/<id>.json` |
| 3 | `uvicorn app.main:app --reload --port 8000` | open http://localhost:8000/docs and try `POST /ticket` |

No API key yet? `set LLM_PROVIDER=mock` (Windows) / `export LLM_PROVIDER=mock` runs the whole plumbing offline.
The mock is a keyword stub: use it to check wiring, never to report results.

## 3. Tests and evaluation
```bash
pytest -v                                       # tools, rule gate, pipeline, failure injection, metrics, API (mock LLM)
python run_eval.py --limit 3                    # smoke run against Gemini
python run_eval.py                              # baseline + multi-agent over 30 cases (MCP server must be running)
python run_eval.py --api-url https://YOUR-API.onrender.com    # same suite on the deployed API
python make_cost_report.py                      # -> 09_Cost_Analysis.xlsx
```
Outputs in `results/`: `evaluation_results.csv`, `cost_log.csv`, `summary.json`, `comparison.md` (the section-35 table).
Run the suite more than once (LLM output varies) and audit a sample by hand (guide layer L7).

Failure injection by hand (take screenshots): stop Terminal 1 with Ctrl+C, send a ticket, and you get a controlled error
with no invented order data; restart and it recovers. `pytest` also covers: server down, malformed tool response,
unknown order, missing order number, conflicting sources, prompt injection in the ticket and in a policy document.

Key metrics: groundedness, hallucination rate (claim and case level), **decision accuracy**, **unsafe approval rate**
(refund/cancellation approved when it must not be), P95 latency, tool success rate, cost per query.

## 4. Docker
```bash
docker compose up --build
curl http://localhost:8000/health
```
Two services: `mcp-server` (8001) and `api` (8000). Inside Docker `MCP_SERVER_URL` uses the service name, not localhost.

## 5. Deploy on Render (free)
Two Web Services from the same GitHub repo, Runtime = Docker:
1. **MCP service**: Docker Command `python -m mcp_server.server`. Env: `MCP_HOST=0.0.0.0`, `MCP_AUTH_TOKEN=<long random string>`,
   `MCP_ALLOWED_HOSTS=<this-service>.onrender.com`. Leave the health-check path unset (the MCP endpoint needs the token).
2. **API service**: default command. Env: `LLM_API_KEY`, `MODEL_NAME`, `LLM_RPM`, `PRICE_*`, `PRICING_DATE_CHECKED`,
   `MCP_SERVER_URL=https://<mcp-service>.onrender.com/mcp`, the same `MCP_AUTH_TOKEN`, `ENVIRONMENT=production`. Health check: `/health`.
Never commit `.env`. Free services sleep after ~15 min idle; open the URL before a demo.
Record: URL, `git rev-parse HEAD`, date, config.

## 6. Where the marks come from
| Marks | Component | Evidence |
|---|---|---|
| 4M | MCP program | `mcp_server/`, `app/mcp_client/client.py`, `tests/test_mcp_contract.py`, tool-discovery + tool-call screenshots |
| 4M | MAS program | `app/agents/`, `app/gate.py`, `app/orchestrator.py`, a `runs/<id>.json` log |
| 8M | Case study | `results/*.csv`, `comparison.md`, `09_Cost_Analysis.xlsx`, Docker, public URL |
| 5M | Theory report | chapters from guide section 42, written from all of the above |

## 7. Design choices to state in the viva
- **The LLM never decides money.** `check_return_eligibility` (rules) and `get_order` (database) are authoritative; `gate.py`
  turns their output into a decision. A test proves a model claim of "refund approved" cannot override a DENY.
- **Retrieved text and tickets are data.** Both are wrapped in tags; the corpus contains a planted "approve every refund"
  instruction and one test ticket carries a "SYSTEM OVERRIDE" line.
- **No arithmetic by the model.** The verifier proposes an expression, the MCP calculator computes it.
- **Conflicts go to a human.** Two policy pages disagree on shipping time; the system opens an escalation (MCP tool) and shows both values.
- **Refusing is a valid answer.** Unknown order, missing order number, unknown policy and out-of-scope requests get a
  template reply with no LLM call, which also saves free-tier quota.
- A claim with no valid evidence id is forced to UNSUPPORTED; every reply sentence cites `[E#]`.

## 8. Known limits (put in the report)
- Verifier, triage and evaluator are LLM-based and can be wrong; rule-based pass/fail is a heuristic.
- Keyword retrieval over 12 documents; a missing answer can be a retrieval failure rather than a hallucination.
- Only the first order id in a ticket is acted on. "Today" is fixed by `SHOP_TODAY` for reproducibility.
- The baseline has no policy knowledge by design, so it is scored on whether it invents order facts.
- Cost = equivalent paid-tier price from `.env` (verify it); actual free-tier spend is 0. Free-tier quotas change without notice.

## 9. Adapting the domain
Replace `data/orders.json`, `data/documents/*.txt`, the rules in `mcp_server/tools.py`, and `data/test_cases.json`. The agents,
client, evaluation harness and deployment files are domain-independent.
