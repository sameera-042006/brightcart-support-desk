import os
import pathlib
import sys

os.environ["LLM_PROVIDER"] = "mock"            # tests must never spend API quota
os.environ.setdefault("LLM_RPM", "100000")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.mcp_client.client import MCPToolClient  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


@pytest.fixture
def client():
    """In-memory MCP client: exercises the real server code without a network port."""
    return MCPToolClient(server=mcp, retries=0)
