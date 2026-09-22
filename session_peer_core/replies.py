
# --------------------------------------------------------------------------
# Reply address. A cross-machine message carries no reply address of its own,
# so the receiving Claude has no way to know answering is even possible. This
# appends one line saying where to send an answer.
#
# It grants nothing: the far side can only reply if it could already SSH here.
# What it adds is knowing that, which is what the receiver otherwise lacks.
# --------------------------------------------------------------------------


def is_tailnet_address(candidate: str) -> bool:
    parts = candidate.split(".")
    if len(parts) != 4 or not all(p.isdigit() and len(p) <= 3 for p in parts):
        return False
    octets = [int(p) for p in parts]
    if any(o > 255 for o in octets):
        return False
    return octets[0] == 100 and octets[1] in TAILNET_SECOND_OCTET


def _run(command: list[str]) -> str:
    try:
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=DETECT_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def tailscale_status() -> dict | None:
    """Return the local tailnet map when the Tailscale CLI is available."""
    commands = [["tailscale", "status", "--json"]]
    if sys.platform == "darwin":
        commands.append([
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
            "status", "--json",
        ])
    for command in commands:
        try:
            done = subprocess.run(
                command, capture_output=True, encoding="utf-8", errors="replace",
                timeout=DETECT_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode:
            continue
        try:
            status = json.loads(done.stdout)
        except ValueError:
            continue
        if isinstance(status, dict) and status.get("BackendState") == "Running":
            return status
    return None


def _magicdns_enabled(status: dict) -> bool:
    tailnet = status.get("CurrentTailnet")
    return isinstance(tailnet, dict) and tailnet.get("MagicDNSEnabled") is True


def _tailnet_nodes(status: dict) -> list[dict]:
    nodes = []
    own = status.get("Self")
    if isinstance(own, dict):
        nodes.append(own)
    peers = status.get("Peer")
    if isinstance(peers, dict):
        nodes.extend(peer for peer in peers.values() if isinstance(peer, dict))
    return nodes


def _node_names(node: dict) -> set[str]:
    names = set()
    dns_name = str(node.get("DNSName") or "").rstrip(".").lower()
    hostname = str(node.get("HostName") or "").rstrip(".").lower()
    if dns_name:
        names.add(dns_name)
        names.add(dns_name.split(".", 1)[0])
    if hostname:
        names.add(hostname)
    addresses = node.get("TailscaleIPs")
    if isinstance(addresses, list):
        names.update(str(address).lower() for address in addresses)
    return names


def resolve_ssh_destination(destination: str, status: dict | None = None) -> str:
    """Resolve a known online Tailscale peer's canonical MagicDNS identity.

    A destination that is not in the local tailnet map remains an ordinary SSH
    destination. Callers keep the requested value as SSH's destination alias and
    override HostName with this result, preserving Host/User/Port/IdentityFile
    configuration while connecting to the verified MagicDNS name.
    """
    check_ssh_argument(destination, "--host")
    user, separator, host = destination.rpartition("@")
    if not separator:
        user, host = "", destination
    lookup = host.strip("[]").rstrip(".").lower()
    status = tailscale_status() if status is None else status
    if not status or not _magicdns_enabled(status):
        return destination

    matches = [node for node in _tailnet_nodes(status) if lookup in _node_names(node)]
    if not matches:
        return destination
    unique = {str(node.get("ID") or node.get("PublicKey") or id(node)): node for node in matches}
    if len(unique) != 1:
        raise CcPeerError(
            f"Tailscale destination {host!r} is ambiguous; use its full MagicDNS name"
        )
    node = next(iter(unique.values()))
    dns_name = str(node.get("DNSName") or "").rstrip(".")
    if not dns_name:
        return destination
    if node.get("Online") is False:
        raise CcPeerError(f"Tailscale peer {dns_name} is offline")
    return f"{user}@{dns_name}" if user else dns_name


def is_self_ssh_destination(destination: str, status: dict | None = None) -> bool:
    """Whether an SSH destination names this OS user on this machine."""
    user, separator, host = destination.rpartition("@")
    if not separator:
        user, host = "", destination
    if user and user != getpass.getuser():
        return False
    lookup = host.strip("[]").rstrip(".").lower()
    local_names = {
        "localhost", "127.0.0.1", "::1",
        socket.gethostname().rstrip(".").lower(),
    }
    status = tailscale_status() if status is None else status
    if status:
        own = status.get("Self")
        if isinstance(own, dict):
            local_names.update(_node_names(own))
    return lookup in local_names


def detect_reply_host() -> str | None:
    """This machine's tailnet address, or None if it can't be determined.

    Prefer the canonical MagicDNS name from `tailscale status --json`. Fall back
    to a Tailscale IPv4 address for older/unavailable clients, then interfaces.
    """
    status = tailscale_status()
    if status:
        own = status.get("Self")
        if isinstance(own, dict):
            dns_name = str(own.get("DNSName") or "").rstrip(".")
            if dns_name and _magicdns_enabled(status):
                return dns_name
            addresses = own.get("TailscaleIPs")
            if isinstance(addresses, list):
                for candidate in addresses:
                    if is_tailnet_address(str(candidate)):
                        return str(candidate)
    for command in (["tailscale", "ip", "-4"], ["ip", "-4", "-o", "addr", "show"], ["ifconfig"]):
        for candidate in re.findall(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", _run(command)):
            if is_tailnet_address(candidate):
                return candidate
    return None


def own_session() -> dict | None:
    """The session this process is running inside, if any.

    Claude Code exports the session's own inbox socket path, which carries its
    pid; the registry turns that into a name. Empty when run from a plain shell.
    """
    socket_path = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    match = re.search(r"(\d+)\.sock$", socket_path)
    if not match:
        return None
    pid = int(match.group(1))
    for session in discover(include_unreachable=True):
        if session["pid"] == pid:
            return session
    return None


def sender_agent() -> dict | None:
    """The agent session running this process, when its environment says so."""
    session = own_session()
    if session is not None:
        name = session["name"] or str(session["pid"])
        return {"agent": "claude", "id": str(name).splitlines()[0], "target": str(name)}

    thread = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
    if thread:
        try:
            thread = str(uuid.UUID(thread))
        except ValueError:
            return None
        result = {"agent": "codex", "id": thread, "target": f"codex:{thread}"}
        configured_home = os.environ.get("CODEX_HOME")
        if configured_home:
            result["codexHome"] = str(Path(configured_home).expanduser().resolve())
        return result
    return agy_sender()


def configured_reply_host(explicit_host: str | None) -> str | None:
    return explicit_host or (
        os.environ.get("SESSION_PEER_REPLY_HOST") or os.environ.get("CC_PEER_REPLY_HOST")
    )


def sender_identity(explicit_host: str | None) -> dict | None:
    """Agent-qualified identity and reachable address for this session.

    Both the From: header and the Reply: line are built from this, so they
    can't drift apart. None outside a session, where there is no name to give.
    """
    identity = sender_agent()
    if identity is None:
        return None
    configured_host = configured_reply_host(explicit_host)
    host = resolve_ssh_destination(configured_host) if configured_host else detect_reply_host()
    if host and "@" not in host:
        host = f"{getpass.getuser()}@{host}"
    return {**identity, "host": host}


def _from_identity(identity: dict | None) -> str | None:
    """Format who is speaking from one already-detected identity."""
    if identity is None:
        return None
    agent, identifier, host = identity["agent"], identity["id"], identity["host"]
    # Fall back to the local hostname so this line survives even when no
    # tailnet address turns up; it is for reading, not for connecting.
    where = host or f"{getpass.getuser()}@{socket.gethostname()}"
    return f"From: {agent}:{identifier} @ {where}"


def from_header(explicit_host: str | None) -> str | None:
    """Detect and format who is speaking.

    Claude Code records an arriving peer message with `from: "unknown"` when
    it was posted to the socket directly, so without this the receiver has no
    idea who is asking — and it is told to treat the message as a teammate's
    request. Separate from the reply address on purpose: knowing the sender
    stays useful when answering isn't possible.
    """
    return _from_identity(sender_identity(explicit_host))


def wrap_message(
    text: str, explicit_host: str | None, with_from: bool, with_reply: bool,
    local_reply: bool = False, identity: dict | None | object = _IDENTITY_UNSET,
) -> str:
    """Put the body in an envelope: who sent it, and how to answer.

    Deliberately minimal. Claude Code already prefaces an arriving peer
    message and appends its own guidance about what a peer may and may not
    ask for — repeating any of that here would duplicate it in every message
    and compound with each hop. The two facts it *doesn't* have are the
    sender's identity and a working return address.
    """
    if identity is _IDENTITY_UNSET:
        identity = sender_identity(explicit_host) if with_from or with_reply else None
    header = _from_identity(identity) if with_from else None
    footer = _reply_from_identity(identity, local=local_reply) if with_reply else None
    address = reply_address(identity, local=local_reply) if with_reply else None
    body = text.strip("\n")
    parts = ([header, ""] if header else []) + [body]
    if address or footer:
        parts += ["", "---"]
        if address:
            parts.append(f"Reply-To: {address}")
        if footer:
            parts.append(footer)
    return "\n".join(parts)


def _safe_reply_value(value: str, field: str) -> str:
    if not value or len(value) > MAX_REPLY_ADDRESS_CHARS:
        raise CcPeerError(f"Reply-To {field} is empty or too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CcPeerError(f"Reply-To {field} contains a control character")
    return value


def reply_address(identity: dict | None, local: bool = False) -> str | None:
    """Return a versioned, inert address that can be passed back to --to."""
    if identity is None:
        return None
    agent = identity["agent"]
    AGENTS.get(agent)
    identifier = _safe_reply_value(str(identity["id"]), "session")
    host = identity.get("host")
    if not local and not host:
        return None
    fields = [
        ("agent", agent),
        ("session", identifier),
        ("transport", "local" if local else "ssh"),
    ]
    if not local:
        fields.append(("host", _safe_reply_value(str(host), "host")))
    codex_root = identity.get("codexHome")
    if agent == "codex" and codex_root:
        fields.append(("codexHome", _safe_reply_value(str(codex_root), "codexHome")))
    uri = urllib.parse.urlunsplit((
        REPLY_ADDRESS_SCHEME,
        REPLY_ADDRESS_VERSION,
        "/reply",
        urllib.parse.urlencode(fields),
        "",
    ))
    if len(uri) > MAX_REPLY_ADDRESS_CHARS:
        raise CcPeerError("Reply-To address is too long")
    return uri


def parse_reply_address(value: str) -> dict | None:
    """Parse a Reply-To URI as data. No field is ever evaluated as a command."""
    if not value.startswith(f"{REPLY_ADDRESS_SCHEME}:"):
        return None
    if len(value) > MAX_REPLY_ADDRESS_CHARS:
        raise CcPeerError("Reply-To address is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CcPeerError("Reply-To address contains a control character")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != REPLY_ADDRESS_SCHEME
        or parsed.netloc != REPLY_ADDRESS_VERSION
        or parsed.path != "/reply"
        or parsed.fragment
    ):
        raise CcPeerError("Reply-To must use session-peer://v1/reply without a fragment")
    if re.search(r"%(?![0-9a-fA-F]{2})", parsed.query):
        raise CcPeerError("Malformed percent escape in Reply-To query")
    try:
        pairs = urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True,
        )
    except ValueError as exc:
        raise CcPeerError(f"Malformed Reply-To query: {exc}") from exc
    allowed = {"agent", "session", "transport", "host", "codexHome"}
    fields: dict[str, str] = {}
    for key, item in pairs:
        if key not in allowed:
            raise CcPeerError(f"Unknown Reply-To field: {key}")
        if key in fields:
            raise CcPeerError(f"Duplicate Reply-To field: {key}")
        fields[key] = _safe_reply_value(item, key)
    missing = {"agent", "session", "transport"} - fields.keys()
    if missing:
        raise CcPeerError("Reply-To is missing: " + ", ".join(sorted(missing)))
    adapter = AGENTS.get(fields["agent"])
    if fields["transport"] not in ("local", "ssh"):
        raise CcPeerError("Reply-To transport must be local or ssh")
    if fields["transport"] == "ssh":
        if "host" not in fields:
            raise CcPeerError("SSH Reply-To is missing host")
        if any(character.isspace() for character in fields["host"]):
            raise CcPeerError("Reply-To host must not contain whitespace")
        check_ssh_argument(fields["host"], "--host")
    elif "host" in fields:
        raise CcPeerError("Local Reply-To must not include host")
    target = adapter.target(fields["session"])
    adapter.identity(target, ExecutionContext(fields.get("host", "local"),
                     argparse.Namespace(codex_home=fields.get("codexHome"))))
    if fields["agent"] != "codex" and "codexHome" in fields:
        raise CcPeerError("Claude Reply-To must not include codexHome")
    if "codexHome" in fields and not (
        PurePosixPath(fields["codexHome"]).is_absolute()
        or PureWindowsPath(fields["codexHome"]).is_absolute()
    ):
        raise CcPeerError("Reply-To codexHome must be an absolute path")
    return {**fields, "target": target, "uri": value}


def reply_route(identity: dict | None, local: bool) -> dict | None:
    """Describe the generated reply route without parsing untrusted body text."""
    uri = reply_address(identity, local=local)
    if uri is None:
        return None
    status = "verified" if local else "unverified"
    return {
        "uri": uri, "transport": "local" if local else "ssh", "status": status,
        "reason": "same_machine_route" if local else "reverse_ssh_not_checked",
    }


def apply_reply_target(args: argparse.Namespace) -> dict | None:
    """Resolve a structured --to address into ordinary, validated CLI fields."""
    address = parse_reply_address(args.to)
    if address is None:
        return None
    if args.host:
        raise CcPeerError("Do not combine a Reply-To URI with --host")
    uri_home = address.get("codexHome")
    configured_home = getattr(args, "codex_home", None)
    if uri_home and configured_home and configured_home != uri_home:
        raise CcPeerError("Reply-To codexHome conflicts with --codex-home")
    if uri_home:
        args.codex_home = uri_home
    transport = address["transport"]
    if transport == "ssh":
        host = address["host"]
        if is_self_ssh_destination(host):
            address = {**address, "transport": "local", "normalizedFrom": "ssh_self"}
        else:
            args.host = [host]
    args.to = address["target"]
    return address


def _reply_from_identity(identity: dict | None, local: bool = False) -> str | None:
    """Format a reply command from one already-detected identity."""
    if identity is None:
        return None
    target, host = identity["target"], identity["host"]
    if not host and not local:
        return None
    script = Path(__file__).resolve()
    script_str = (
        shlex.quote(str(script))
        if script.is_file()
        else '~/.local/share/session-peer/session_peer.py'
    )
    route = "" if local else f"--host {shlex.quote(host)} "
    return (f"Reply: python3 {script_str} send {route}"
            f"--to {shlex.quote(target)} --no-reply-to")


def reply_line(explicit_host: str | None) -> str | None:
    """Detect how to answer and return a command that runs verbatim.

    Three things the first version left out, each of which broke it in
    practice:

    * the **user**, because the receiver otherwise connects as its own local
      account — a worker running as `ubuntu` cannot reach a laptop's `abruptly`
    * an **absolute script path**, because a non-interactive SSH session never
      sources the profile that puts ~/.local/bin on PATH, so a bare `session-peer`
      is not found
    * `--no-reply-to`, so answering an answer doesn't ping-pong

    The username is the sender's; there's no guarantee the far side knows it,
    but it is right whenever accounts match and strictly better than nothing.
    """
    return _reply_from_identity(sender_identity(explicit_host))
