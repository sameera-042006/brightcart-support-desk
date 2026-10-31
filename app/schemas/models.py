from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ClaimStatus = Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
Intent = Literal["return_refund", "order_status", "warranty", "cancellation", "policy_question"]
Decision = Literal["APPROVE_RETURN", "DENY", "WARRANTY_CLAIM", "APPROVE_CANCELLATION", "INFORM",
                   "INSUFFICIENT_INFO", "ESCALATE", "DECLINE", "ERROR", ""]


# ---- contracts for MCP tool responses (validated by the MCP client) --------------------
class SearchHit(BaseModel):
    source: str
    title: str = ""
    text: str
    relevance: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)


class SearchResponse(BaseModel):
    results: list[SearchHit] = []
    error: Optional[str] = None


class OrderItem(BaseModel):
    sku: str
    name: str
    unit_price_usd: float
    quantity: int


class OrderResponse(BaseModel):
    order_id: str
    error: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    items: list[OrderItem] = []
    shipping_fee_usd: float = 0.0
    delivery_date: Optional[str] = None
    expected_delivery: Optional[str] = None
    damage_reported: bool = False
    payment_method: str = ""
    cancellable: bool = False

    @model_validator(mode="after")
    def _complete(self):
        if self.error is None and (self.status is None or not self.items):
            raise ValueError("order response is missing status or items")
        return self


class EligibilityResponse(BaseModel):
    order_id: str
    error: Optional[str] = None
    reference_date: Optional[str] = None
    eligible: bool = False
    reason_code: str = ""
    days_since_delivery: Optional[int] = None
    return_window_days: int = 30
    warranty_days: int = 365
    full_order_refund_usd: float = 0.0
    warranty_active: bool = False

    @model_validator(mode="after")
    def _complete(self):
        if self.error is None and (self.reference_date is None or not self.reason_code):
            raise ValueError("eligibility response is missing reference_date or reason_code")
        return self


# ---- run state ------------------------------------------------------------------------
class Evidence(BaseModel):
    evidence_id: str
    source: str
    text: str
    relevance: float = 1.0
    source_quality: float = 1.0


class Claim(BaseModel):
    claim_id: str
    statement: str
    evidence_ids: list[str] = []
    status: ClaimStatus = "UNSUPPORTED"
    supported: bool = False
    confidence: float = 0.0


class AgentLog(BaseModel):
    name: str
    latency_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0


class McpCallLog(BaseModel):
    tool: str
    success: bool
    latency_ms: float
    attempts: int = 1
    error: str = ""


class RunState(BaseModel):
    run_id: str
    ticket: str
    # triage
    in_domain: bool = True
    intent: str = "policy_question"
    order_ids: list[str] = []
    search_terms: str = ""
    # investigation (raw tool results kept for the deterministic gate)
    orders: dict[str, dict] = {}
    eligibility: dict[str, dict] = {}
    evidence: list[Evidence] = []
    evidence_keys: dict[str, str] = {}
    missing_evidence_for: list[str] = []
    # verification
    claims: list[Claim] = []
    conflicts: list[str] = []
    unsupported_premises: list[str] = []
    calculations: list[dict] = []
    needs_human: bool = False
    # decision + reply
    decision: str = ""
    decision_reason: str = ""
    refund_amount_usd: Optional[float] = None
    escalation_ref: str = ""
    reply: str = ""
    status: Literal["ok", "insufficient_info", "escalated", "declined", "error"] = "ok"
    error: str = ""
    # accounting
    agents: list[AgentLog] = []
    mcp_calls: list[McpCallLog] = []
    tool_calls: int = 0
    latency_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    metrics: dict = {}


class TicketRequest(BaseModel):
    ticket: str = Field(min_length=3, max_length=2000)
