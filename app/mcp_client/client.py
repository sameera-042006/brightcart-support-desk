"""MCP client wrapper (SDK v2). Adds timeout, bounded retry with backoff,
per-call logging and response-schema validation. Never fabricates a result:
after the final failed attempt it raises MCPToolError."""
import asyncio
import json
import os
import time
from typing import Any, Optional

from pydantic import ValidationError

from app.schemas.models import EligibilityResponse, McpCallLog, OrderResponse, SearchResponse


class MCPToolError(Exception):
    pass


def _leaf(exc: BaseException) -> BaseException:
    """Unwrap ExceptionGroups (anyio task groups) so the real cause (401, refused, timeout) is shown."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


class MCPToolClient:
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None,
                 timeout: float = 15.0, retries: int = 2, backoff: float = 0.5,
                 server: Any = None):
        self.url = url or os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")
        self.token = token if token is not None else os.getenv("MCP_AUTH_TOKEN")
        self.timeout, self.retries, self.backoff = timeout, retries, backoff
        self.server = server            # an MCPServer instance => in-memory (tests)
        self.calls: list[McpCallLog] = []

    # ---- connection -------------------------------------------------------
    def _open(self):
        from mcp.client import Client
        if self.server is not None:
            return Client(self.server)
        if self.token:
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
            http = create_mcp_http_client(headers={"Authorization": f"Bearer {self.token}"})
            return Client(streamable_http_client(self.url, http_client=http))
        return Client(self.url)

    async def _once(self, name: Optional[str], args: Optional[dict]):
        async with self._open() as c:
            if name is None:
                return [t.name for t in (await c.list_tools()).tools]
            res = await c.call_tool(name, args or {}, read_timeout_seconds=self.timeout)
            if res.is_error:
                raise MCPToolError(f"tool {name} reported an error")
            texts = [b.text for b in res.content if getattr(b, "text", None) is not None]
            if not texts:
                raise MCPToolError(f"tool {name} returned no content")
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError as exc:
                raise MCPToolError(f"tool {name} returned non-JSON content") from exc

    def _run(self, name, args, label):
        t0, last = time.perf_counter(), ""
        for attempt in range(1, self.retries + 2):
            try:
                out = asyncio.run(asyncio.wait_for(self._once(name, args), self.timeout + 5))
                self.calls.append(McpCallLog(tool=label, success=True, attempts=attempt,
                                             latency_ms=(time.perf_counter() - t0) * 1000))
                return out
            except Exception as exc:  # connection refused, timeout, protocol error...
                leaf = _leaf(exc)
                last = f"{type(leaf).__name__}: {leaf}"
                if attempt <= self.retries:
                    time.sleep(self.backoff * 2 ** (attempt - 1))
        self.calls.append(McpCallLog(tool=label, success=False, attempts=self.retries + 1, error=last,
                                     latency_ms=(time.perf_counter() - t0) * 1000))
        raise MCPToolError(f"MCP call '{label}' failed after {self.retries + 1} attempts: {last}")

    # ---- public API -------------------------------------------------------
    def list_tools(self) -> list[str]:
        return self._run(None, None, "list_tools")

    def call_tool(self, name: str, args: dict) -> dict:
        return self._run(name, args, name)

    def _validate(self, model, raw: dict, label: str):
        try:
            return model.model_validate(raw)
        except ValidationError as exc:       # malformed tool response => reject, never trust it
            self.calls[-1].success = False
            self.calls[-1].error = "schema validation failed"
            raise MCPToolError(f"malformed {label} response: {exc.errors()[:1]}") from exc

    def search_policy(self, query: str, top_k: int = 4) -> SearchResponse:
        return self._validate(SearchResponse, self.call_tool("search_policy", {"query": query, "top_k": top_k}),
                              "search_policy")

    def get_order(self, order_id: str) -> OrderResponse:
        return self._validate(OrderResponse, self.call_tool("get_order", {"order_id": order_id}), "get_order")

    def check_return_eligibility(self, order_id: str) -> EligibilityResponse:
        return self._validate(EligibilityResponse,
                              self.call_tool("check_return_eligibility", {"order_id": order_id}),
                              "check_return_eligibility")

    def calculator(self, expression: str) -> dict:
        return self.call_tool("calculator", {"expression": expression})

    def create_escalation(self, run_id: str, reason: str, summary: str) -> dict:
        out = self.call_tool("create_escalation", {"run_id": run_id, "reason": reason, "summary": summary})
        if not out.get("created"):
            self.calls[-1].success = False
            raise MCPToolError(f"escalation was not created: {out.get('error', 'unknown error')}")
        return out

    def save_evidence(self, run_id: str, evidence: dict) -> dict:
        return self.call_tool("save_evidence", {"run_id": run_id, "evidence": evidence})
