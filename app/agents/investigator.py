"""Investigator: gathers order facts, rule-engine results and policy text through the MCP client.
No LLM call. An empty or failed lookup is recorded as MISSING evidence, never turned into a fact."""
from app.agents.common import Timer
from app.gate import REASON_TEXT
from app.mcp_client.client import MCPToolClient, MCPToolError
from app.schemas.models import Evidence, RunState

MAX_POLICY = 4


def order_text(o) -> str:
    items = "; ".join(f"{i.quantity} x {i.name} (SKU {i.sku}) at {i.unit_price_usd:.2f} USD each" for i in o.items)
    if o.delivery_date:
        when = f"delivered on {o.delivery_date}"
    elif o.expected_delivery:
        when = f"expected delivery on {o.expected_delivery}"
    else:
        when = "not delivered yet"
    return (f"Order {o.order_id}: status {o.status}; {when}; category {o.category}; items: {items}; "
            f"shipping fee {o.shipping_fee_usd:.2f} USD; payment by {o.payment_method}; "
            f"damage reported: {'yes' if o.damage_reported else 'no'}.")


def elig_text(e) -> str:
    days = e.days_since_delivery if e.days_since_delivery is not None else "n/a"
    return (f"Eligibility check for {e.order_id} (reference date {e.reference_date}): "
            f"eligible for return = {'yes' if e.eligible else 'no'}; reason: {REASON_TEXT.get(e.reason_code, e.reason_code)}; "
            f"days since delivery = {days}; return window = {e.return_window_days} days; "
            f"refund if the whole order is returned = {e.full_order_refund_usd:.2f} USD; "
            f"warranty active = {'yes' if e.warranty_active else 'no'} (electronics, {e.warranty_days} days from delivery).")


def run(state: RunState, mcp: MCPToolClient) -> RunState:
    with Timer(state, "investigator"):
        attempts = failures = 0
        evidence: list[Evidence] = []

        def add(source: str, text: str, key: str = "", rel: float = 1.0, q: float = 1.0):
            eid = f"E{len(evidence) + 1}"
            evidence.append(Evidence(evidence_id=eid, source=source, text=text, relevance=rel, source_quality=q))
            if key:
                state.evidence_keys[key] = eid

        for oid in state.order_ids:
            attempts += 1
            try:
                o = mcp.get_order(oid)
            except MCPToolError:
                failures += 1
                state.missing_evidence_for.append(f"{oid} (tool failure)")
                continue
            if o.error:
                state.missing_evidence_for.append(f"{oid} ({o.error})")
                continue
            state.orders[oid] = o.model_dump()
            add(f"order_db:{oid}", order_text(o), key=f"order:{oid}")
            if state.intent in ("return_refund", "warranty"):
                attempts += 1
                try:
                    e = mcp.check_return_eligibility(oid)
                except MCPToolError:
                    failures += 1
                    state.missing_evidence_for.append(f"{oid} eligibility (tool failure)")
                    continue
                if not e.error:
                    state.eligibility[oid] = e.model_dump()
                    add(f"eligibility_tool:{oid}", elig_text(e), key=f"elig:{oid}")

        if state.intent != "order_status":
            attempts += 1
            query = state.search_terms.strip() or state.ticket
            try:
                hits = mcp.search_policy(query, MAX_POLICY).results
            except MCPToolError:
                failures += 1
                hits = []
                state.missing_evidence_for.append("policy search (tool failure)")
            if not hits:
                state.missing_evidence_for.append(f"policy: {query}")
            for h in hits:
                add(h.source, h.text, rel=h.relevance, q=h.source_quality)

        if attempts and failures == attempts:
            raise MCPToolError("all MCP lookups failed; refusing to answer without tool results")
        state.evidence = evidence
        if evidence:
            try:
                mcp.save_evidence(state.run_id, {"evidence": [e.model_dump() for e in evidence]})
            except MCPToolError:
                pass                      # audit trail is best-effort; the failure shows up in mcp_calls
    return state
