#!/usr/bin/env sh
# Single-container entrypoint: run the MCP tool server on loopback and the web
# API on the platform-provided port. The API reaches MCP via 127.0.0.1 inside
# this same container, so MCP is never exposed publicly.
set -e

mkdir -p runs results

export MCP_HOST=127.0.0.1
export MCP_PORT=8001
export MCP_SERVER_URL="http://127.0.0.1:8001/mcp"

python -m mcp_server.server &
MCP_PID=$!
trap 'kill "$MCP_PID" 2>/dev/null' EXIT INT TERM

# Wait up to ~15s for the MCP port to start accepting connections.
python - <<'PY'
import socket, sys, time
for _ in range(60):
    try:
        socket.create_connection(("127.0.0.1", 8001), 0.5).close()
        sys.exit(0)
    except OSError:
        time.sleep(0.25)
print("warning: MCP server did not become ready in time", file=sys.stderr)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
