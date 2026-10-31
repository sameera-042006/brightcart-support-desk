"""Single entry point for every model call, so token usage, latency, throttling
and retries are handled in one place.

LLM_PROVIDER=gemini (default) uses the google-genai SDK:  pip install google-genai
LLM_PROVIDER=mock   offline stub for testing the plumbing (NOT for results).
"""
import os
import re
import threading
import time
from dataclasses import dataclass

MODEL_NAME = lambda: os.getenv("MODEL_NAME", "gemini-2.5-flash-lite")  # noqa: E731


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


_lock = threading.Lock()
_last_call = 0.0
_client = None


def _throttle():
    """Stay under the free-tier requests-per-minute limit (LLM_RPM, default 10)."""
    global _last_call
    min_gap = 60.0 / float(os.getenv("LLM_RPM", "10"))
    with _lock:
        wait = _last_call + min_gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _gemini(system: str, user: str, json_mode: bool, max_tokens: int) -> LLMResult:
    global _client
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise LLMError("google-genai is not installed: pip install google-genai") from exc
    key = os.getenv("LLM_API_KEY")
    if not key:
        raise LLMError("LLM_API_KEY is not set (see .env.example)")
    if _client is None:
        _client = genai.Client(api_key=key)
    cfg = dict(system_instruction=system, temperature=0.0, max_output_tokens=max_tokens)
    if json_mode:
        cfg["response_mime_type"] = "application/json"
    budget = os.getenv("GEMINI_THINKING_BUDGET")       # e.g. 0 to disable thinking on Flash
    if budget not in (None, ""):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=int(budget))
    t0 = time.perf_counter()
    resp = _client.models.generate_content(
        model=MODEL_NAME(), contents=user, config=types.GenerateContentConfig(**cfg))
    ms = (time.perf_counter() - t0) * 1000
    u = resp.usage_metadata
    in_tok = getattr(u, "prompt_token_count", 0) or 0
    # thinking tokens are billed as output tokens
    out_tok = (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
    return LLMResult(resp.text or "", in_tok, out_tok, ms)


def _mock(agent: str, system: str, user: str, json_mode: bool) -> LLMResult:
    """Offline stub for testing the plumbing ONLY (keyword rules, no intelligence). Never report its numbers."""
    import json
    if agent == "triage":
        t = re.search(r"<ticket>(.*?)</ticket>", user, re.S).group(1)
        low = t.lower()
        ood = any(w in low for w in ("poem", "prime minister", "world cup", "recipe"))
        if re.search(r"warranty|stopped working|broke", low):
            intent = "warranty"
        elif "cancel" in low and "cancelled" not in low:
            intent = "cancellation"
        elif re.search(r"return|refund|damaged|cracked|get back", low):
            intent = "return_refund"
        elif re.search(r"where is|status|how much|paid|total|why was my order", low):
            intent = "order_status"
        else:
            intent = "policy_question"
        out = json.dumps({"in_domain": not ood, "intent": intent, "order_ids": re.findall(r"ORD-\d{4}", t),
                          "search_terms": re.sub(r"ORD-\d{4}", "", t)[:80]})
    elif agent == "verifier":
        ev = re.findall(r'<evidence id="(E\d+)" source="([^"]*)">(.*?)</evidence>', user, re.S)
        claims = [{"statement": t.strip().split(". ")[0], "evidence_ids": [i], "status": "SUPPORTED",
                   "confidence": 0.9} for i, _, t in ev[:4]]
        srcs = {src: i for i, src, _ in ev}
        conflicts = []
        if "shipping_standard_a" in srcs and "shipping_standard_b" in srcs:
            conflicts = [f"Standard shipping time differs: 3-5 business days [{srcs['shipping_standard_a']}] "
                         f"versus 7-10 business days [{srcs['shipping_standard_b']}]"]
        out = json.dumps({"claims": claims, "calculations": [], "conflicts": conflicts,
                          "unsupported_premises": [], "needs_human": False})
    elif agent == "responder":
        dec = re.search(r"DECISION:\s*(\w+)", user).group(1)
        reason = re.search(r"DECISION REASON:\s*(.*)", user).group(1)
        cl = re.findall(r"\[(C\d+)\] (.*?) \(evidence: ([^)]*)\)", user)
        out = f"Decision {dec}. {reason} " + " ".join(f"{st} [{e}]" for _, st, e in cl[:3])
    elif agent == "evaluator":
        text = re.search(r"ANSWER:\s*(.*)", user, re.S).group(1)
        ids = set(re.findall(r'<evidence id="(E\d+)"', user))
        cites = re.findall(r"\[(E\d+)\]", text)
        out = json.dumps({"claims": [{"statement": "mock", "status": "SUPPORTED" if c in ids else "UNSUPPORTED",
                                      "evidence_ids": [c]} for c in cites]})
    else:
        out = "Mock baseline reply.\nDECISION: INFORM"
    return LLMResult(out, max(1, (len(system) + len(user)) // 4), max(1, len(out) // 4), 1.0)


def call_llm(system: str, user: str, json_mode: bool = False, agent: str = "",
             max_tokens: int = 1500) -> LLMResult:
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "mock":
        return _mock(agent, system, user, json_mode)
    retries = int(os.getenv("LLM_MAX_RETRIES", "4"))
    last = ""
    for attempt in range(retries + 1):
        _throttle()
        try:
            return _gemini(system, user, json_mode, max_tokens)
        except LLMError:
            raise
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            code = getattr(exc, "code", None)
            retryable = code in (429, 500, 502, 503, 504) or any(
                s in last for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "timed out"))
            if not retryable or attempt == retries:
                break
            time.sleep(min(60, 4 * 2 ** attempt))      # exponential backoff: 4, 8, 16, 32 s
    raise LLMError(f"LLM call failed ({agent or 'unnamed'}): {last}")
