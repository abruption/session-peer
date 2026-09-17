"""Optional stdio MCP adapter; the standalone CLI remains dependency-free."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

import session_peer as core


class PolicyError(ValueError):
    pass


def load_policy(path: str | None) -> dict:
    if path is None:
        return {"local": {"capabilities": ["list"], "agents": list(core.AGENTS.names()),
                          "codexHome": str(Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve())}}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"schemaVersion", "destinations"} or raw["schemaVersion"] != 1:
        raise PolicyError("Expected schemaVersion: 1 and destinations")
    destinations = raw["destinations"]
    if not isinstance(destinations, dict) or not destinations:
        raise PolicyError("destinations must be a nonempty object")
    for name, entry in destinations.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise PolicyError("Invalid destination")
        if set(entry) - {"host", "codexHome", "agents", "capabilities"}:
            raise PolicyError(f"Unknown settings for {name}")
        for key, allowed in (("agents", set(core.AGENTS.names())), ("capabilities", {"list", "send", "wake"})):
            values = entry.get(key)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or v not in allowed for v in values):
                raise PolicyError(f"Invalid {key} for {name}")
        host = entry.get("host")
        if host is not None:
            if not isinstance(host, str) or not host or any(c.isspace() for c in host):
                raise PolicyError("host must be an SSH destination")
            core.check_ssh_argument(host, "host")
        home = entry.get("codexHome")
        if "codex" in entry["agents"] and (not isinstance(home, str) or not home.startswith("/") or "\0" in home):
            raise PolicyError("Codex destinations require an absolute codexHome")
    return destinations


class Adapter:
    def __init__(self, destinations: dict):
        self.destinations = destinations

    def authorize(self, destination: str, capability: str, agent: str | None) -> dict:
        entry = self.destinations.get(destination)
        if entry is None or capability not in entry["capabilities"]:
            raise PolicyError(f"Destination does not allow {capability}")
        if agent is not None and agent not in entry["agents"]:
            raise PolicyError("Agent is not allowed at this destination")
        return entry

    def route(self, entry: dict) -> list[str]:
        argv = []
        if entry.get("host"):
            argv += ["--host", entry["host"]]
        if entry.get("codexHome"):
            argv += ["--codex-home", entry["codexHome"]]
        return argv

    async def invoke(self, argv: list[str], message: str | None = None) -> dict:
        # Use this distribution, not a possibly different executable on PATH.
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(core.__file__).resolve()), *argv,
            "--json", "--no-update-notice",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(None if message is None else message.encode("utf-8")), 130)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 8)
                except asyncio.TimeoutError:
                    process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return {"ok": False, "error": "CLI timed out; submission outcome unknown; do not automatically retry",
                    "reason": "outcome_unknown"}
        try:
            result = json.loads(stdout)
        except (ValueError, UnicodeError):
            return {"ok": False, "error": "CLI returned invalid JSON; do not automatically retry",
                    "reason": "invalid_cli_response"}
        if not isinstance(result, dict):
            return {"ok": False, "error": "Unexpected CLI response", "reason": "invalid_cli_response"}
        if process.returncode and result.get("ok") is not False:
            return {**result, "ok": False, "reason": "cli_failed"}
        return result

    async def list_sessions(self, destination: str = "local", agent: str | None = None,
                            include_inactive: bool = False) -> dict:
        entry = self.authorize(destination, "list", agent)
        argv = ["list", *self.route(entry)]
        if agent is None and len(entry["agents"]) == 1:
            agent = entry["agents"][0]
        if agent:
            argv += ["--agent", agent]
        if include_inactive:
            argv.append("--all")
        return await self.invoke(argv)

    async def send_message(self, destination: str, target: str, message: str,
                           dry_run: bool = False, wake: bool = False, wake_timeout: int = 30) -> dict:
        address = core.parse_reply_address(target)
        agent = address["agent"] if address else core.AGENTS.for_target(target).name
        entry = self.authorize(destination, "send", agent)
        if wake:
            self.authorize(destination, "wake", agent)
            if not core.AGENTS.get(agent).capabilities.wake:
                raise PolicyError("wake requires a Codex target")
        if not 1 <= wake_timeout <= 60:
            raise PolicyError("wake_timeout must be between 1 and 60")
        if address:
            # Exact configured routes are intentional: never follow a URI to a
            # different host/home, even if DNS says it is another local alias.
            if address.get("host") != entry.get("host"):
                raise PolicyError("Reply URI host does not match configured destination")
            if address.get("codexHome") not in (None, entry.get("codexHome")):
                raise PolicyError("Reply URI home does not match configured destination")
            target = address["target"]
            if core.AGENTS.for_target(target).name != agent:
                raise PolicyError("Reply URI agent conflicts with target")
        if not target or target.startswith("-") or target.startswith("session-peer:"):
            raise PolicyError("Invalid target")
        core.AGENTS.get(agent).identity(target, core.ExecutionContext(
            entry.get("host", "local"), argparse.Namespace(codex_home=entry.get("codexHome"))))
        core.check_message(message, remote=bool(entry.get("host")))
        # Keep the validated URI intact so the CLI retains its self-host
        # normalization and addressResolution metadata. Its host is already
        # authorized above; passing --host alongside a URI is not supported.
        route_entry = dict(entry)
        if address:
            route_entry.pop("host", None)
        argv = ["send", *self.route(route_entry), "--to", address["uri"] if address else target,
                "--no-from", "--no-reply-to"]
        if dry_run:
            argv.append("--dry-run")
        if wake:
            argv += ["--wake", "--wake-timeout", str(wake_timeout)]
        # A shared MCP process cannot authenticate the invoking thread. Never
        # advertise the session that happened to launch it as the caller.
        return await self.invoke(argv, "From: session-peer MCP (caller session unavailable)\n\n" + message)


def create_server(adapter: Adapter):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import CallToolResult, TextContent, ToolAnnotations

    server = FastMCP("session-peer", instructions=(
        "List and message configured coding-agent destinations. Queued is not received. "
        "Never retry an ambiguous send automatically. Caller identity and reply route are unavailable. "
        "Only destination capabilities explicitly configured by the operator are allowed."))

    async def result(call):
        try:
            value = await call
        except (PolicyError, core.CcPeerError) as exc:
            value = {"ok": False, "reason": "request_rejected", "error": str(exc)}
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                              structuredContent=value, isError=value.get("ok") is False)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def list_sessions(destination: str = "local", agent: str | None = None,
                            include_inactive: bool = False):
        """List sessions on an operator-configured destination; agent is claude or codex."""
        return await result(adapter.list_sessions(destination, agent, include_inactive))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                           idempotentHint=False, openWorldHint=True))
    async def send_message(destination: str, target: str, message: str,
                           dry_run: bool = False, wake: bool = False, wake_timeout: int = 30):
        """Send once to a configured destination. Submission does not confirm consumption."""
        return await result(adapter.send_message(destination, target, message, dry_run, wake, wake_timeout))

    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("SESSION_PEER_MCP_CONFIG"))
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 10):
            raise PolicyError("MCP requires Python 3.10+; standalone CLI supports Python 3.9")
        create_server(Adapter(load_policy(args.config))).run(transport="stdio")
    except (ImportError, ValueError, OSError, core.CcPeerError) as exc:
        print(f"session-peer-mcp: {exc}; install session-peer[mcp] and check policy", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
