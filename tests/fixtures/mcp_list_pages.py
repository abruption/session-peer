"""Offline fixture for bounded MCP listing: never reads native sessions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def listing(count=1000):
    return {"ok": True, "sessions": [{"agent": "codex", "id": "fixture-%04d" % index,
        "name": "한글🪼" * 200, "codexHome": "/PRIVATE_HOME", "cwd": "/PRIVATE_CWD",
        "transcript": "PRIVATE_TRANSCRIPT"} for index in range(count)],
        "discovery": {"codex": {"status": "ok"}}}


def cli():
    mode = os.environ.get("SESSION_PEER_PAGE_FIXTURE", "normal")
    marker = os.environ.get("SESSION_PEER_PAGE_MARKER")
    if marker:
        with open(marker, "a") as stream:
            stream.write(str(os.getpid()) + "\n")
    if mode == "sleep":
        time.sleep(60)
    if mode == "descendant":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        if marker:
            Path(marker + ".child").write_text(str(child.pid))
        time.sleep(60)
    if mode == "stdout":
        os.write(1, b"x" * (4 * 1024 * 1024 + 1))
        return
    if mode == "stderr":
        os.write(2, b"x" * (64 * 1024 + 1))
        return
    if mode == "invalid":
        print("PRIVATE_INVALID_JSON")
        return
    value = listing(50 if mode == "huge" else 1000)
    if '--agent' in sys.argv and sys.argv[sys.argv.index('--agent') + 1] == 'claude':
        for index, row in enumerate(value['sessions']):
            row.update(agent='claude', pid=index + 1000)
            row.pop('id')
        value['discovery'] = {'claude': {'status': 'ok'}}
    if mode == "huge":
        for index, row in enumerate(value["sessions"]):
            row["id"] = str(index) + "🪼" * 1900
    if mode == "partial":
        value.update(ok=False, error="PRIVATE_ERROR")
        value["discovery"]["codex"] = {"status": "error", "error": "PRIVATE_ERROR"}
    print(json.dumps(value, ensure_ascii=False))
    if mode == "nonzero":
        raise SystemExit(1)


if __name__ == "__main__":
    if "--fixture-server" in sys.argv:
        sys.path.insert(0, str(ROOT))
        import session_peer_mcp as peer
        if '--legacy-baseline' in sys.argv:
            from importlib.metadata import version
            if version('mcp').startswith('1.'):
                from mcp.server.fastmcp import FastMCP
                peer._sdk_server_factory = lambda: FastMCP
            else:
                from functools import partial
                from mcp.server.mcpserver import MCPServer
                peer._sdk_server_factory = lambda: partial(MCPServer, subscriptions=False)
        # All legacy and paged collection use this synthetic CLI source. This is
        # a local fixture override, never a production API or native discovery.
        peer.core.__file__ = str(Path(__file__).resolve())
        adapter = peer.Adapter({"local": {"agents": ["codex", "claude"], "capabilities": ["list"],
                                           "codexHome": "/PRIVATE_HOME"}})
        peer.create_server(adapter).run(transport="stdio")
    else:
        cli()
