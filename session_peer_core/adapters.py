# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


# Internal extension contract. Keep this in the streamed standalone source.
ADAPTER_CONTRACT_VERSION = 1


class SessionIdentity(NamedTuple):
    agent: str
    host: str
    identifier: str
    codex_home: str | None = None


class ExecutionContext(NamedTuple):
    host: str
    options: argparse.Namespace


class DiscoveryResult(TypedDict):
    sessions: list[dict]
    discovery: dict


class SubmissionResult(TypedDict, total=False):
    # Native payloads may additionally carry target, chars, home and wake data.
    ok: bool
    status: str
    submitted: bool
    consumptionConfirmed: bool
    queueId: str


class AgentCapabilities(NamedTuple):
    list: bool = True
    send: bool = True
    wake: bool = False
    wait: bool = False
    ack: bool = False


class AdapterError(CcPeerError):
    def __init__(self, agent: str, code: str, message: str):
        super().__init__(message, {"agent": agent, "reason": code})


class AgentAdapter:
    """Internal v1 contract; native result dictionaries retain their wire shape.

    list returns sessions/discovery plus optional top-level metadata; submit
    returns the existing agent-specific payload. Neither implies consumption.
    Only source-registered adapters run; there is no external plugin loader.
    """
    contract_version = ADAPTER_CONTRACT_VERSION
    name = ""
    capabilities = AgentCapabilities()

    def target(self, identifier: str) -> str:
        return f"{self.name}:{identifier}"

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        prefix = self.name + ":"
        if not target.startswith(prefix) or not target[len(prefix):]:
            raise AdapterError(self.name, "invalid_target", "Invalid agent target")
        return SessionIdentity(self.name, context.host, target[len(prefix):])

    def validate_send(self, args: argparse.Namespace, text: str | None = None) -> None:
        if not self.capabilities.send:
            raise AdapterError(self.name, "unsupported_capability", "Agent does not support send")
        if getattr(args, "wake", False) and not self.capabilities.wake:
            raise wake_refused("unsupported_agent", "--wake requires a Codex target")
        self.identity(args.to, ExecutionContext("local", args))

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        raise NotImplementedError

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        raise NotImplementedError

    def diagnose(self, context: ExecutionContext) -> dict:
        return {"status": "unavailable", "checks": []}

    def diagnostic_text(self, result: dict) -> str:
        return f"{self.name}: {result['status']}"

    def remote_options(self, args: argparse.Namespace) -> list[str]:
        return []

    def display_row(self, session: dict) -> tuple[str, str]:
        return str(session["id"]), str(session.get("status", "unknown"))

    def render(self, sessions: list[dict], where: str) -> str:
        return f"Sessions on {where}:\n" + "\n".join(
            f"{self.name}  {self.display_row(row)[0]}  {self.display_row(row)[1]}"
            for row in sessions)

    def listing_notes(self, payload: dict) -> list[str]:
        return []

    def submission_text(self, result: dict, where: str) -> str:
        return f"{self.name} submission on {where}: {result.get('status', 'unknown')}"

    def remote_submission(self, result: dict, args: argparse.Namespace, text: str) -> dict:
        return result


class ClaudeAdapter(AgentAdapter):
    name = "claude"

    def target(self, identifier: str) -> str:
        return identifier

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        if not target:
            raise AdapterError(self.name, "invalid_target", "Empty Claude target")
        return SessionIdentity(self.name, context.host, target)

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        return {"sessions": [{**row, "agent": self.name} for row in
                             discover(include_unreachable=context.options.all)],
                "discovery": {"status": "ok"}}

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        args = context.options
        session = resolve_target(discover(include_unreachable=True), args.to)
        if not args.dry_run:
            post_to_socket(session["socket"], text, pid=session["pid"])
        return {"ok": True, "target": {"pid": session["pid"], "name": session["name"]},
                "chars": len(text), "dryRun": args.dry_run}

    def diagnose(self, context: ExecutionContext) -> dict:
        return diagnose_claude()

    def diagnostic_text(self, result: dict) -> str:
        return f"Claude inbox: {result['status']}"

    def display_row(self, session: dict) -> tuple[str, str]:
        status = session.get("status") or "-"
        if not session["reachable"]:
            status = "no inbox" if session["alive"] else "stale record"
        return str(session["pid"]), status

    def render(self, sessions: list[dict], where: str) -> str:
        return render_sessions(sessions, where)

    def submission_text(self, result: dict, where: str) -> str:
        target = result.get("target", {})
        name = target.get("name") or target.get("pid")
        verb = "Would post to" if result["dryRun"] else "Posted to"
        return f"{verb} {name}'s inbox on {where} ({result['chars']} chars)."

    def remote_submission(self, result: dict, args: argparse.Namespace, text: str) -> dict:
        return {"target": result.get("target", {}), **ssh_metadata_from(result),
                "chars": len(text), "dryRun": args.dry_run}


class CodexAdapter(AgentAdapter):
    name = "codex"
    capabilities = AgentCapabilities(wake=True)

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        return SessionIdentity(self.name, context.host, codex_thread(target),
                               str(codex_home(context.options)))

    def validate_send(self, args: argparse.Namespace, text: str | None = None) -> None:
        super().validate_send(args, text)
        if text is not None:
            check_codex_message(text)

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        return collect_codex_listing(context.options)

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        return queue_codex(context.options, text)

    def diagnose(self, context: ExecutionContext) -> dict:
        return diagnose_codex(context.options)

    def diagnostic_text(self, result: dict) -> str:
        return f"Codex: {result['status']} ({result.get('selectedHome', 'unknown')})"

    def remote_options(self, args: argparse.Namespace) -> list[str]:
        return codex_remote_options(args)

    def display_row(self, session: dict) -> tuple[str, str]:
        return session["id"], ("archived; execution unknown" if session["archived"]
                               else "execution unknown")

    def render(self, sessions: list[dict], where: str) -> str:
        return render_codex(sessions, where)

    def listing_notes(self, payload: dict) -> list[str]:
        notes = []
        if "codexHome" in payload:
            notes.append(f"Codex home: {payload['codexHome']} (single candidate home).")
        info = payload.get("discovery", {}).get(self.name, {})
        if info.get("status") == "not_installed":
            notes.append("No Codex installation found in known homes.")
        for item in info.get("homes", []):
            if item["status"] == "error":
                notes.append(f"Codex home {item['codexHome']}: {item['code']}: {item['error']}")
        for error in info.get("errors", []):
            notes.append(f"Codex {error['source']}: {error['code']}: {error['error']}")
        return notes

    def submission_text(self, result: dict, where: str) -> str:
        return codex_submission_text(result, where)
