"""Receipt-less, model-free MCP startup fixture; exposes only synthetic markers."""
import json
import os
import sys

names = ("SESSION_PEER_WAKE_DEPTH", "SESSION_PEER_WAKE_ORIGIN",
         "SESSION_PEER_WAKE_MAX_DEPTH", "ORDINARY_TEST", "NODE_REPL_AUTH_TOKEN")
observed = {name: os.environ[name] for name in names if name in os.environ}
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": request["params"]["protocolVersion"],
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "private-environment-fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "environment_probe", "description": json.dumps(observed),
                             "inputSchema": {"type": "object"}}]}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "resources/templates/list":
        result = {"resourceTemplates": []}
    elif method == "prompts/list":
        result = {"prompts": []}
    elif method == "ping":
        result = {}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                          "error": {"code": -32601, "message": "fixture method unsupported"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
