import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import app.orchestrator as orch  # noqa: E402
from app.main import app  # noqa: E402
from app.mcp_client.client import MCPToolClient  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(orch, "MCPToolClient", lambda: MCPToolClient(server=mcp, retries=0))
    return TestClient(app)


def test_health(api):
    assert api.get("/health").json()["status"] == "ok"


def test_ticket_ok_and_metrics_endpoint(api):
    r = api.post("/ticket", json={"ticket": "Where is my order ORD-1003?"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "INFORM" and "[E" not in body["reply_for_customer"] and body["metrics"]["latency_ms"] >= 0
    assert api.get(f"/metrics/{body['run_id']}").status_code == 200


def test_invalid_input_returns_422_not_crash(api):
    assert api.post("/ticket", json={"ticket": ""}).status_code == 422
    assert api.post("/ticket", json={"ticket": "x" * 5000}).status_code == 422


def test_metrics_rejects_bad_run_id(api):
    assert api.get("/metrics/..%2F..%2Fetc").status_code in (400, 404)
    assert api.get("/metrics/does-not-exist").status_code == 404


def test_evaluation_endpoint_disabled_by_default(api):
    assert api.post("/evaluation/run").status_code == 403
