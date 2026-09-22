class AgentRegistry:
    def __init__(self):
        self._adapters: dict[str, AgentAdapter] = {}

    def register(self, adapter: AgentAdapter) -> None:
        name = getattr(adapter, "name", "")
        if (not isinstance(adapter, AgentAdapter) or not isinstance(name, str)
                or not re.fullmatch(r"[a-z][a-z0-9_-]*", name)
                or type(adapter.contract_version) is not int
                or adapter.contract_version != ADAPTER_CONTRACT_VERSION
                or not isinstance(adapter.capabilities, AgentCapabilities)
                or any(type(value) is not bool for value in adapter.capabilities)
                or type(adapter).list is AgentAdapter.list
                or type(adapter).submit is AgentAdapter.submit
                or any(not callable(getattr(adapter, method, None)) for method in
                       ("list", "submit", "diagnose", "identity", "target", "validate_send",
                        "remote_options", "render", "display_row", "listing_notes", "diagnostic_text",
                        "submission_text", "remote_submission"))):
            raise AdapterError(name, "invalid_adapter_contract", "Invalid or incompatible agent adapter")
        if name in self._adapters:
            raise AdapterError(name, "duplicate_agent", "Agent already registered")
        self._adapters[name] = adapter

    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def get(self, name: str) -> AgentAdapter:
        if name not in self._adapters:
            raise AdapterError(name, "unknown_agent", f"Unknown agent: {name}")
        return self._adapters[name]

    def for_target(self, target: str) -> AgentAdapter:
        prefix, separator, _ = target.partition(":")
        # Unregistered prefixes remain literal Claude names for compatibility.
        if separator and prefix in self._adapters and prefix != "claude":
            return self.get(prefix)
        return self.get("claude")


AGENTS = AgentRegistry()
AGENTS.register(ClaudeAdapter())
AGENTS.register(CodexAdapter())
AGENTS.register(AntigravityAdapter())


class LocalTransport:
    def execute(self, operation: str, adapter: AgentAdapter,
                args: argparse.Namespace, text: str | None = None) -> dict:
        context = ExecutionContext("local", args)
        try:
            if operation == "list":
                if not adapter.capabilities.list:
                    raise AdapterError(adapter.name, "unsupported_capability", "Agent does not support list")
                result = adapter.list(context)
                if (not isinstance(result, dict)
                        or not isinstance(result.get("sessions"), list)
                        or not isinstance(result.get("discovery"), dict)
                        or result["discovery"].get("status") not in ("ok", "error", "not_installed")
                        or (result["discovery"].get("status") == "error"
                            and not isinstance(result["discovery"].get("error"), str))
                        or any(not isinstance(row, dict) or row.get("agent") != adapter.name
                               for row in result["sessions"])):
                    raise AdapterError(adapter.name, "invalid_adapter_result", "Invalid discovery result")
                # Validate rendering before aggregating so malformed rows cannot
                # destroy successful results from other adapters, even in JSON mode.
                for row in result["sessions"]:
                    adapter.display_row(row)
                return result
            if operation == "send":
                adapter.validate_send(args, text)
                result = adapter.submit(context, text)
                if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                    raise AdapterError(adapter.name, "outcome_unknown",
                                       "Invalid submission result; do not automatically retry")
                return result
            if operation == "doctor":
                result = adapter.diagnose(context)
                if not isinstance(result, dict) or not isinstance(result.get("status"), str):
                    raise AdapterError(adapter.name, "invalid_adapter_result", "Invalid diagnostic result")
                return result
            raise AdapterError(adapter.name, "unsupported_capability", "Unsupported operation")
        except CcPeerError:
            raise
        except OSError:
            raise
        except Exception as exc:
            # Do not echo arbitrary adapter exceptions (which may contain secrets).
            code = "outcome_unknown" if operation == "send" else "adapter_failed"
            message = ("Submission outcome unknown; do not automatically retry"
                       if operation == "send" else "Agent operation failed")
            raise AdapterError(adapter.name, code, message) from exc


class SshTransport:
    def __init__(self, requested_host: str, args: argparse.Namespace, status: dict):
        self.requested_host = requested_host
        self.host = resolve_ssh_destination(requested_host, status)
        self.ssh_opts = tailscale_ssh_options(requested_host, self.host) + args.ssh_opt

    def execute(self, argv: list[str]) -> dict:
        return run_remote(self.requested_host, argv, self.ssh_opts)


def validate_agent_send(adapter: AgentAdapter, args: argparse.Namespace,
                        text: str | None = None) -> None:
    try:
        adapter.validate_send(args, text)
    except CcPeerError:
        raise
    except Exception as exc:
        raise AdapterError(adapter.name, "adapter_failed", "Agent validation failed") from exc


def agent_remote_options(args: argparse.Namespace, selected: str | None = None) -> list[str]:
    options = []
    for name in ([selected] if selected else AGENTS.names()):
        options.extend(AGENTS.get(name).remote_options(args))
    return options


def collect_listing(args: argparse.Namespace) -> dict:
    selected = getattr(args, "agent", None)
    payload = {"sessions": [], "version": __version__, "discovery": {}, "ok": True}
    for agent in ([selected] if selected else AGENTS.names()):
        try:
            listing = LocalTransport().execute("list", AGENTS.get(agent), args)
            payload["sessions"].extend(listing["sessions"])
            payload["discovery"][agent] = listing["discovery"]
            for key, value in listing.items():
                if key not in {"sessions", "discovery", "ok", "error", "version"}:
                    payload[key] = value
            if listing["discovery"]["status"] == "error":
                payload["ok"] = False
        except (CcPeerError, OSError) as exc:
            payload["ok"] = False
            payload["discovery"][agent] = {"status": "error", "error": str(exc)}
    failed = [agent for agent, info in payload["discovery"].items()
              if info["status"] == "error"]
    if failed:
        payload["error"] = "Discovery failed for: " + ", ".join(failed)
    return payload


def render_listing(payload: dict, where: str, selected: str | None) -> str:
    sessions = payload["sessions"]
    if selected:
        human = AGENTS.get(selected).render(sessions, where)
    else:
        rows = ["AGENT  NAME  ID/PID  STATUS  CWD  CODEX HOME"]
        for session in sessions:
            identifier, status = AGENTS.get(session["agent"]).display_row(session)
            rows.append(f"{session['agent']}  {session.get('name') or '(unnamed)'}  "
                        f"{identifier}  {status}  {session.get('cwd') or '-'}  {session.get('codexHome') or '-'}")
        human = f"Sessions on {where}:\n" + "\n".join(rows)
    for name in payload.get("discovery", {}):
        for note in AGENTS.get(name).listing_notes(payload):
            human += "\n" + note
    for agent, info in payload.get("discovery", {}).items():
        if info["status"] == "error":
            human += f"\n{agent} discovery failed: {info['error']}"
    return human
