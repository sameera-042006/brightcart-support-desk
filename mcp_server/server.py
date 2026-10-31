"""BrightCart support MCP server (SDK v2: MCPServer). Deterministic tools only, no LLM inside.

Run locally:  python -m mcp_server.server
Env vars:     MCP_HOST (127.0.0.1), MCP_PORT / PORT (8001), MCP_AUTH_TOKEN (bearer token, recommended when deployed),
              MCP_ALLOWED_HOSTS (comma list; turns on Host-header allow-listing), SHOP_TODAY (reference date)
"""
import os

from mcp.server.mcpserver import MCPServer

from mcp_server import tools

mcp = MCPServer("brightcart-support-tools")


@mcp.tool()
def search_policy(query: str, top_k: int = 4) -> dict:
    """Keyword search over the store policy documents. Returns {"results": [{source, title, text, relevance, source_quality}]}."""
    return tools.search_policy(query, top_k)


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Look up an order (format ORD-1234): status, items, prices, dates, shipping fee."""
    return tools.get_order(order_id)


@mcp.tool()
def check_return_eligibility(order_id: str) -> dict:
    """Apply the return/warranty rules to an order: eligible, reason_code, days_since_delivery, refund amount, warranty_active."""
    return tools.check_return_eligibility(order_id)


@mcp.tool()
def calculator(expression: str) -> dict:
    """Safe arithmetic (+ - * / ** %). No eval()."""
    return tools.calculator(expression)


@mcp.tool()
def create_escalation(run_id: str, reason: str, summary: str) -> dict:
    """Hand a case to a human agent; returns a ticket reference."""
    return tools.create_escalation(run_id, reason, summary)


@mcp.tool()
def save_evidence(run_id: str, evidence: dict) -> dict:
    """Append an evidence record to runs/<run_id>_evidence.jsonl."""
    return tools.save_evidence(run_id, evidence)


class BearerAuth:
    """Tiny ASGI wrapper: reject requests without the shared bearer token."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization", b"").decode() != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def build_app():
    """MCP_HOST must be 0.0.0.0 in Docker/Render, otherwise the SDK only accepts localhost Host headers.
    Optional MCP_ALLOWED_HOSTS="my-mcp.onrender.com,mcp-server:8001" keeps DNS-rebinding protection on."""
    host = os.getenv("MCP_HOST", "127.0.0.1")
    allowed = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if allowed:
        from mcp.server.transport_security import TransportSecuritySettings
        sec = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                        allowed_hosts=allowed + ["127.0.0.1:*", "localhost:*"], allowed_origins=[])
        app = mcp.streamable_http_app(host=host, transport_security=sec)
    else:
        app = mcp.streamable_http_app(host=host)
    token = os.getenv("MCP_AUTH_TOKEN")
    return BearerAuth(app, token) if token else app


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT") or os.getenv("PORT") or 8001)
    uvicorn.run(build_app(), host=host, port=port)
