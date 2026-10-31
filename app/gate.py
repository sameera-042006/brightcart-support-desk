"""Deterministic decision gate. The LLM never decides refunds, eligibility or cancellations:
those come from MCP tool results (check_return_eligibility, get_order). The model only
extracts facts, verifies claims and writes the reply."""
from app.schemas.models import RunState

ORDER_INTENTS = {"return_refund", "order_status", "warranty", "cancellation"}
APPROVING = {"APPROVE_RETURN", "APPROVE_CANCELLATION"}

REASON_TEXT = {
    "within_window": "the order is within the 30-day return window",
    "window_expired": "the 30-day return window has expired",
    "damaged_item": "the item was reported damaged, which qualifies for a full refund including shipping",
    "gift_card_non_returnable": "gift cards are non-returnable and non-refundable",
    "not_delivered": "the order has not been delivered yet",
    "order_cancelled": "the order was cancelled",
}


def _set(state: RunState, decision: str, reason: str, refund: float | None = None) -> RunState:
    state.decision, state.decision_reason, state.refund_amount_usd = decision, reason, refund
    return state


def decide(state: RunState) -> RunState:
    # 1. conflicting sources or a request needing human judgment => a person decides
    if state.conflicts or state.needs_human:
        why = "sources disagree" if state.conflicts else "the request needs human judgment"
        return _set(state, "ESCALATE", why)

    intent = state.intent
    if intent in ORDER_INTENTS:
        if not state.orders:
            return _set(state, "INSUFFICIENT_INFO", "no matching order was found")
        oid = next((o for o in state.order_ids if o in state.orders), next(iter(state.orders)))
        o, e = state.orders[oid], state.eligibility.get(oid)
        oe = state.evidence_keys.get(f"order:{oid}", "")
        ee = state.evidence_keys.get(f"elig:{oid}", "")

        if intent == "order_status":
            return _set(state, "INFORM", f"Order {oid} has status {o['status']} [{oe}]")

        if intent == "cancellation":
            if o["cancellable"]:
                return _set(state, "APPROVE_CANCELLATION",
                            f"Order {oid} has status {o['status']}, so it has not shipped and can still be cancelled [{oe}]")
            if o["status"] == "cancelled":
                return _set(state, "INFORM", f"Order {oid} is already cancelled [{oe}]")
            return _set(state, "DENY",
                        f"Order {oid} has status {o['status']}, so it can no longer be cancelled [{oe}]")

        if e is None:
            return _set(state, "INSUFFICIENT_INFO", "the eligibility check is unavailable")

        if intent == "warranty":
            if e["warranty_active"]:
                return _set(state, "WARRANTY_CLAIM",
                            f"Order {oid} is {e['days_since_delivery']} days after delivery, inside the "
                            f"{e['warranty_days']}-day electronics warranty [{ee}]")
            return _set(state, "DENY",
                        f"Order {oid} has no active warranty (the warranty covers electronics for "
                        f"{e['warranty_days']} days from delivery) [{ee}]")

        # return_refund
        why = REASON_TEXT.get(e["reason_code"], e["reason_code"])
        days = e["days_since_delivery"]
        extra = f" ({days} days since delivery, window {e['return_window_days']} days)" if days is not None else ""
        if e["eligible"]:
            return _set(state, "APPROVE_RETURN", f"Return approved: {why}{extra} [{ee}]",
                        e["full_order_refund_usd"])
        return _set(state, "DENY", f"Return not possible: {why}{extra} [{ee}]")

    # policy_question
    usable = [c for c in state.claims if c.status in ("SUPPORTED", "PARTIALLY_SUPPORTED")]
    if usable:
        return _set(state, "INFORM", "answer from verified policy evidence")
    return _set(state, "INSUFFICIENT_INFO", "no verified evidence answers the question")
