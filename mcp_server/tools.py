"""Deterministic tool logic for the BrightCart support MCP server. No LLM calls live here.
All data is fictional demo data. 'Today' is fixed by SHOP_TODAY (default 2026-10-31) so results are reproducible."""
import ast
import json
import operator
import os
import pathlib
import re
from datetime import date, datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "data" / "documents"
RUNS_DIR = ROOT / "runs"
RETURN_WINDOW_DAYS = 30
WARRANTY_DAYS = 365

STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "to", "in", "on", "for", "is", "are", "be", "what", "which", "how",
    "why", "does", "do", "did", "with", "by", "as", "at", "it", "its", "that", "this", "than", "from",
    "about", "can", "should", "would", "will", "i", "you", "we", "my", "me", "your", "our", "am", "was",
    "were", "have", "has", "had", "please", "help", "hi", "hello", "thanks", "thank", "want", "need",
    "know", "tell", "get", "much", "many", "long", "take", "takes", "there", "any", "if", "when", "then",
    "so", "but", "not", "no", "yes", "ord",
}


def today() -> date:
    return date.fromisoformat(os.getenv("SHOP_TODAY", "2026-10-31"))


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOPWORDS or len(w) < 2:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.add(w)
    return out


def load_policies() -> dict[str, dict]:
    meta_path = ROOT / "data" / "sources.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    corpus = {}
    for p in sorted(DOCS_DIR.glob("*.txt")):
        info = meta.get(p.stem, {})
        text = p.read_text().strip()
        title = info.get("title", p.stem)
        corpus[p.stem] = {"title": title, "text": text,
                          "source_quality": float(info.get("source_quality", 0.5)),
                          "tokens": _tokens(title + " " + text)}
    return corpus


def load_orders() -> dict[str, dict]:
    p = ROOT / "data" / "orders.json"
    return json.loads(p.read_text()) if p.exists() else {}


POLICIES = load_policies()
ORDERS = load_orders()
ORDER_ID_RE = re.compile(r"ORD-\d{4}")


# ----------------------------------------------------------------- policy search
def search_policy(query: str, top_k: int = 4) -> dict:
    if not isinstance(query, str) or not query.strip():
        return {"error": "query must be a non-empty string", "results": []}
    if len(query) > 500:
        return {"error": "query too long (max 500 chars)", "results": []}
    q = _tokens(query)
    if not q:
        return {"results": []}
    hits = []
    for doc_id, doc in POLICIES.items():
        overlap = len(q & doc["tokens"])
        if overlap == 0:
            continue
        rel = min(1.0, overlap / max(1, min(len(q), 5)))
        hits.append({"source": doc_id, "title": doc["title"], "text": doc["text"][:700],
                     "relevance": round(rel, 3), "source_quality": doc["source_quality"]})
    hits.sort(key=lambda h: (-h["relevance"], -h["source_quality"]))
    best = hits[0]["relevance"] if hits else 0
    hits = [h for h in hits if h["relevance"] >= max(0.2, 0.6 * best)]   # drop weak matches next to a strong one
    return {"results": hits[: max(1, min(int(top_k), 6))]}


# ----------------------------------------------------------------- orders
def _norm_id(order_id) -> str:
    return str(order_id).strip().upper()


def _items_total(o: dict) -> float:
    return round(sum(i["unit_price_usd"] * i["quantity"] for i in o["items"]), 2)


def get_order(order_id: str) -> dict:
    oid = _norm_id(order_id)
    if not ORDER_ID_RE.fullmatch(oid):
        return {"error": "invalid_order_id", "order_id": oid}
    o = ORDERS.get(oid)
    if o is None:
        return {"error": "not_found", "order_id": oid}
    return {"order_id": oid, "status": o["status"], "category": o["category"], "items": o["items"],
            "shipping_fee_usd": o["shipping_fee_usd"], "delivery_date": o.get("delivery_date"),
            "expected_delivery": o.get("expected_delivery"), "damage_reported": o.get("damage_reported", False),
            "payment_method": o.get("payment_method", ""), "cancellable": o["status"] == "processing"}


def check_return_eligibility(order_id: str) -> dict:
    """Authoritative rule engine for returns and warranty. The LLM never decides eligibility."""
    base = get_order(order_id)
    if "error" in base:
        return base
    oid, o, ref = base["order_id"], ORDERS[base["order_id"]], today()
    out = {"order_id": oid, "reference_date": ref.isoformat(), "return_window_days": RETURN_WINDOW_DAYS,
           "warranty_days": WARRANTY_DAYS, "eligible": False, "reason_code": "", "days_since_delivery": None,
           "full_order_refund_usd": 0.0, "warranty_active": False}
    status = o["status"]
    if status == "cancelled":
        out["reason_code"] = "order_cancelled"
    elif status in ("processing", "shipped"):
        out["reason_code"] = "not_delivered"
    elif o["category"] == "gift_card":
        out["reason_code"] = "gift_card_non_returnable"
    else:
        days = (ref - date.fromisoformat(o["delivery_date"])).days
        out["days_since_delivery"] = days
        if o.get("damage_reported"):
            out.update(eligible=True, reason_code="damaged_item",
                       full_order_refund_usd=round(_items_total(o) + o["shipping_fee_usd"], 2))
        elif days <= RETURN_WINDOW_DAYS:
            out.update(eligible=True, reason_code="within_window", full_order_refund_usd=_items_total(o))
        else:
            out["reason_code"] = "window_expired"
        if o["category"] == "electronics" and days <= WARRANTY_DAYS:
            out["warranty_active"] = True
    return out


# ----------------------------------------------------------------- calculator
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calculator(expression: str) -> dict:
    """Allow-listed arithmetic only (+ - * / ** %). Never uses eval()."""
    try:
        if not isinstance(expression, str) or len(expression) > 200:
            raise ValueError("expression must be a string up to 200 chars")
        return {"expression": expression, "result": _eval(ast.parse(expression.strip(), mode="eval").body)}
    except ZeroDivisionError:
        return {"expression": expression, "error": "division by zero"}
    except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
        return {"expression": expression, "error": f"invalid expression: {exc}"}


# ----------------------------------------------------------------- logging tools
def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", run_id or ""):
        raise ValueError("invalid run_id")
    return run_id


def save_evidence(run_id: str, evidence: dict) -> dict:
    try:
        run_id = _safe_run_id(run_id)
    except ValueError as exc:
        return {"saved": False, "error": str(exc)}
    RUNS_DIR.mkdir(exist_ok=True)
    with (RUNS_DIR / f"{run_id}_evidence.jsonl").open("a") as f:
        f.write(json.dumps(evidence) + "\n")
    return {"saved": True, "run_id": run_id}


def create_escalation(run_id: str, reason: str, summary: str) -> dict:
    """Hand the case to a human agent. Writes runs/escalations.jsonl."""
    try:
        run_id = _safe_run_id(run_id)
    except ValueError as exc:
        return {"created": False, "error": str(exc)}
    RUNS_DIR.mkdir(exist_ok=True)
    ref = f"ESC-{run_id[-6:].upper()}"
    rec = {"ticket_ref": ref, "run_id": run_id, "reason": str(reason)[:300], "summary": str(summary)[:1000],
           "created_at": datetime.now(timezone.utc).isoformat()}
    with (RUNS_DIR / "escalations.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"created": True, "ticket_ref": ref}
