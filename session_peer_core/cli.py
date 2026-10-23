class MessageArgumentParser(argparse.ArgumentParser):
    def _get_values(self, action, arg_strings):
        # Python 3.9 strips '--' even from an already recognized option value.
        # Preserve only this declared single message value; option recognition
        # still rejects the ambiguous separated form '--message --'.
        if (action.dest == "message_option" and "--message" in action.option_strings
                and action.nargs is None and arg_strings == ["--"]):
            value = self._get_value(action, arg_strings[0])
            self._check_value(action, value)
            return value
        return super()._get_values(action, arg_strings)


class HumanArgumentParser(MessageArgumentParser):
    def parse_known_args(self, args=None, namespace=None):
        values = list(sys.argv[1:] if args is None else args)
        # Reject accidental credential argv before argparse can quote values in
        # unknown-option, missing-argument or invalid-choice diagnostics.
        if (self.prog in ('session-peer', 'session-peer device', 'session-peer setup')
                and any('session-peer://pair/' in value.lower() for value in values)
                and (self.prog != 'session-peer' or (values and values[0] in ('device', 'setup')))):
            self.error('pairing_link_argv_forbidden; use --link without a value')
        return super().parse_known_args(values, namespace)

    def _get_values(self, action, arg_strings):
        if action.option_strings:
            explicit = getattr(self, "_explicit_option_strings", None)
            if explicit is None:
                explicit = self._explicit_option_strings = set()
            explicit.update(action.option_strings)
        return super()._get_values(action, arg_strings)

    def error(self, message):
        # Preserve both the message-value and display-only escaping contracts.
        if 'session-peer://pair/' in message.lower():
            message = 'pairing_link_argv_forbidden; use --link without a value'
        super().error(human_text(message))


class SshConfigArgument(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) not in (None, False):
            parser.error(self.option_strings[0] + " may be specified only once")
        setattr(namespace, self.dest, self.const if self.nargs == 0 else values)


def prepare_trusted_ssh_config(parser, args):
    path = getattr(args, "ssh_config", None)
    trust = getattr(args, "trust_ssh_config", False)
    if path is None and not trust:
        return
    if path is None or not trust:
        parser.error("--ssh-config and --trust-ssh-config must be supplied together")
    if args.command not in ("list", "send", "doctor", "update") or not getattr(args, "host", None):
        parser.error("--ssh-config requires list/send/doctor/update with explicit --host")
    if getattr(args, "device", None) or getattr(args, "preset", None) is not None:
        parser.error("--ssh-config cannot be combined with paired devices or route presets")
    if str(getattr(args, "to", "")).lower().startswith("session-peer:"):
        parser.error("--ssh-config cannot be selected through a Reply-To invocation")
    for host in args.host:
        check_ssh_argument(host, "--host")
    check_ssh_options(getattr(args, "ssh_opt", []))
    if IS_WINDOWS:
        raise _ssh_config_error("ssh_config_platform_unsupported")
    if args.command == "send" and handoff_requested(args):
        # Configuration setup belongs to the ORIGINAL handoff budget; no
        # metadata/effect child receives a renewed deadline or this local path.
        args._handoff_fixed_total = handoff_now() + args.wait_timeout
    SSH_CONFIG_SELECTION.set(select_trusted_ssh_config(path))


def build_parser() -> argparse.ArgumentParser:
    parser = HumanArgumentParser(
        prog="session-peer",
        description="Message Claude Code and Codex sessions locally or over SSH.",
    )
    parser.add_argument("--version", action="version", version=f"session-peer {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--ssh-identity", action="store_true", help="report connection-verified SSH host-key identity (POSIX opt-in)")
        sub.add_argument("--require-ssh-host-key", metavar="SHA256:KEY", help="require this host key on the actual SSH connection (POSIX opt-in)")
        sub.add_argument(
            "--host", action="append", default=[], metavar="DEST",
            help="SSH [USER@]HOST, repeatable; otherwise User comes from SSH config/default",
        )
        sub.add_argument(
            "--ssh-opt",
            action="append",
            default=[],
            metavar="OPT",
            help="allowlisted SSH connection option, repeatable (e.g. --ssh-opt=-p --ssh-opt=2222; see CLI reference)",
        )
        sub.add_argument("--output-format", choices=("text", "json"),
                         help="command result format (default: text); does not change message input")
        sub.add_argument("--json", action="store_true", help="alias for --output-format json (command results only)")
        sub.add_argument(
            "--no-update-notice", action="store_true",
            help="disable automatic cached update notices and refreshes",
        )

    listing = subparsers.add_parser("list", help="list sessions that can be messaged")
    add_common(listing)
    listing.add_argument("--agent", choices=AGENTS.names(), default=None,
                         help="filter by agent (default: all registered adapters)")
    listing.add_argument("--preset", action=PresetSingleUseAction, metavar="NAME", help="use one saved local or SSH route, not a saved receiver")
    home_help = ("select one Codex home on the destination (default: CODEX_HOME or ~/.codex); "
                 "set explicitly for Orca/multiple homes")
    listing.add_argument("--codex-home", help="list only this destination home (default: known default, CODEX_HOME, Orca and configured homes)")
    listing.add_argument("--codex-bin", help="Codex executable on the destination (used by send)")
    listing.add_argument("--with-target-generation", action="store_true",
                         help="report optional inbox generation preconditions (not ACK or consumption)")
    listing.add_argument(
        "--all", action="store_true", help="include stale records and sessions with no inbox"
    )
    listing.set_defaults(func=cmd_list)

    doctor = subparsers.add_parser(
        "doctor", help="diagnose agent homes, inboxes, tools, and optional return routes",
    )
    add_common(doctor)
    doctor.add_argument("--codex-home", help=home_help)
    doctor.add_argument("--codex-bin", help="Codex executable on the destination machine")
    doctor.add_argument(
        "--check-return-route", action="store_true",
        help="from the diagnosed host, test a non-interactive SSH route back here",
    )
    doctor.add_argument(
        "--reply-to", metavar="HOST",
        help="return host to test (default: this machine's detected tailnet address)",
    )
    doctor.add_argument("--_return-host", dest="_return_host", help=argparse.SUPPRESS)
    doctor.set_defaults(func=cmd_doctor)

    sending = subparsers.add_parser("send", help="send one message to a session")
    add_common(sending)
    sending.add_argument("--preset", action=PresetSingleUseAction, metavar="NAME", help="use one saved local or SSH route, not a saved receiver")
    sending.add_argument("--preset-revision", action=PresetSingleUseAction, metavar="REV", help="require the route revision from preset show or text dry-run stderr (required for actual preset sends)")
    sending.add_argument(
        "--to", metavar="TARGET|REPLY-URI",
        help="session name, PID, codex:UUID, antigravity:UUID, or session-peer://v1/reply address",
    )
    sending.add_argument("--codex-home", help=home_help)
    sending.add_argument("--target-generation", metavar="TOKEN",
                         help="require a previously discovered inbox generation; fail closed if unsupported")
    sending.add_argument("--address", action=PresetSingleUseAction, help="explicit local saved-recipient reference")
    sending.add_argument("--address-revision", action=PresetSingleUseAction, help="current address revision required for actual submission")
    sending.add_argument("--confirm-target", action=PresetSingleUseAction, help="confirm the current canonical recipient, not an override")
    sending.add_argument("--_address-writer-revision", dest="_address_expected_writer", type=address_writer_revision_argument,
                         help=argparse.SUPPRESS)
    sending.add_argument(
        "--allow-inactive-codex-home", action="store_true",
        help="with --codex-home, intentionally queue an inactive thread for a future resume",
    )
    sending.epilog = ("All matching known homes are checked even with --codex-home. A unique "
                      "stable live writer is required unless --codex-home and "
                      "--allow-inactive-codex-home explicitly select an all-inactive copy. "
                      "Known homes: selected/default, macOS "
                      "Orca account homes, and destination SESSION_PEER_CODEX_HOMES (JSON array "
                      "of paths). Queued/submitted never confirms consumption.")
    sending.add_argument("--codex-bin", help="Codex executable on the destination machine")
    sending.add_argument("message", nargs="?", help="message text (legacy positional form); omit or use - to read stdin")
    sending.add_argument("--message", "-m", dest="message_option", metavar="TEXT",
                         help="message body; use - for stdin; cannot combine with a positional message")
    sending.add_argument("--message-file", metavar="PRIVATE_FILE", help="read a private owner-only UTF-8 message file")
    sending.add_argument("--correlation-id", type=handoff_cli_uuid, help="use a previously prepared Handoff v1 intent")
    sending.add_argument("--request-ack", action="store_true", help="opt in to receipt-only delegated ACK authority")
    sending.add_argument("--observe-delivery", action="store_true", help="report injection evidence when supported (not consumption)")
    sending.add_argument("--wait-for", choices=("delivered", "acknowledged"), help="require evidence with a bounded total budget")
    sending.add_argument("--wait-timeout", type=handoff_timeout, default=30, metavar="SECONDS", help="Handoff total budget, ASCII integer 1..60 (default: 30)")
    sending.add_argument("--b64", help=argparse.SUPPRESS)  # used for remote dispatch
    sending.add_argument("--_handoff-native-context", help=argparse.SUPPRESS)
    sending.add_argument("--_handoff-native-cutoff-ms", type=handoff_private_ms, help=argparse.SUPPRESS)
    sending.add_argument("--_handoff-native-total-ms", type=handoff_private_ms, help=argparse.SUPPRESS)
    sending.add_argument(
        "--reply-to",
        metavar="HOST",
        help="reply address to advertise (default: this machine's tailnet address)",
    )
    sending.add_argument(
        "--no-reply-to", action="store_true", help="send without a reply address"
    )
    sending.add_argument(
        "--no-from", action="store_true", help="send without the From: header"
    )
    sending.add_argument("--wake", action="store_true", help="explicitly resume a Codex thread; may use models and modify history")
    sending.add_argument("--wake-max-depth", type=int, choices=range(0, 17), metavar="HOPS",
                         help="explicit wake chain limit, 0..16 (default: 3; 0 disables wakes)")
    for flag in ("--_wake-depth", "--_wake-origin", "--_wake-limit"):
        sending.add_argument(flag, help=argparse.SUPPRESS)
    sending.add_argument("--wake-timeout", type=int, choices=range(1, 61), default=30, metavar="SECONDS",
                         help="wake deadline, 1..60 seconds (default: 30)")
    sending.add_argument("--dry-run", action="store_true", help="resolve the target, send nothing")
    sending.add_argument("--explain", action="store_true", help="explain existing dry-run evidence in text")
    doctor.add_argument("--explain", action="store_true", help="explain existing diagnostic capabilities in text")
    sending.set_defaults(func=cmd_send)

    preset = subparsers.add_parser("preset", help="manage private local route presets without contacting destinations")
    preset_sub = preset.add_subparsers(dest="preset_action", required=True)
    for action in ("add", "list", "show", "replace", "remove"):
        sub = preset_sub.add_parser(action)
        sub.add_argument("--json", action="store_true")
        sub.add_argument("--output-format", choices=("text", "json"))
        sub.set_defaults(func=cmd_preset, no_update_notice=True)
        if action != "list":
            sub.add_argument("name")
        if action in ("add", "replace"):
            sub.add_argument("--host", action=PresetSingleUseAction)
            sub.add_argument("--agent", action=PresetSingleUseAction, choices=("claude", "codex"), required=True)
            sub.add_argument("--codex-home", action=PresetSingleUseAction)
        if action in ("replace", "remove"):
            sub.add_argument("--expect-revision", action=PresetSingleUseAction, required=True, metavar="REV")

    handoff = subparsers.add_parser("handoff", help="manage private correlated intents without submitting native messages")
    handoff_sub = handoff.add_subparsers(dest="handoff_action", required=True)
    for action in ("init", "prepare", "status", "watch", "wait", "confirm"):
        sub = handoff_sub.add_parser(action)
        sub.add_argument("--json", action="store_true")
        sub.set_defaults(func=cmd_handoff_watch if action == "watch" else cmd_handoff, no_update_notice=True)
        if action in ("status", "watch", "wait"):
            sub.add_argument("--correlation-id", required=True, type=handoff_cli_uuid)
        if action == "watch":
            sub.add_argument("--watch-timeout", type=handoff_watch_timeout, default=30,
                             metavar="SECONDS", help="finite local watch budget, 1..60 seconds (default: 30)")
            sub.add_argument("--interval-ms", type=handoff_watch_interval, default=1000,
                             metavar="MILLISECONDS", help="sample every 1000..5000 ms (default: 1000)")
        if action == "status":
            sub.add_argument("--explain", action="store_true", help="explain the existing read-only intent snapshot")
        if action == "wait":
            sub.add_argument("--wait-for", choices=("delivered", "acknowledged"), required=True)
            sub.add_argument("--wait-timeout", type=handoff_timeout, default=30)
        if action == "prepare":
            sub.add_argument("--to", required=True)
            sub.add_argument("--message-file", required=True)
            sub.add_argument("--codex-home")
            sub.set_defaults(message=None, message_option=None, b64=None, host=[], device=None, target_generation=None)
        if action == "confirm":
            sub.add_argument("--receipt", choices=("-",), required=True)
    ack = subparsers.add_parser("ack", help="submit a receipt over private local IPC, never a native message")
    ack.add_argument("--receipt", choices=("-",), required=True)
    ack.add_argument("--json", action="store_true")
    ack.set_defaults(func=cmd_ack, no_update_notice=True)

    updating = subparsers.add_parser("update", help="update this installation")
    add_common(updating)
    update_action = updating.add_mutually_exclusive_group()
    update_action.add_argument(
        "--check", action="store_true", help="report the available version, change nothing"
    )
    update_action.add_argument("--dismiss-runtime-notice", type=runtime_notice_cli_version,
                              metavar="VERSION", help="dismiss only this runtime release's ambient notice; no installation")
    update_action.add_argument("--clear-runtime-notice-dismissal", action="store_true",
                              help="clear the local runtime notice dismissal; no installation")
    updating.set_defaults(func=cmd_update)

    # Deliberately not add_common: setup must not gain executable config input.
    for sub in (listing, sending, doctor, updating):
        sub.add_argument("--ssh-config", action=SshConfigArgument, metavar="ABS_PATH",
                         help="operator-trusted local executable SSH configuration; requires --trust-ssh-config")
        sub.add_argument("--trust-ssh-config", action=SshConfigArgument, nargs=0, const=True, default=False,
                         help="authorize this configuration's local commands, including during ssh -G and dry-run")

    for sub in (listing, sending, doctor):
        sub.add_argument('--antigravity-home', help='filter registered Antigravity home on the destination')
    sending.add_argument('--antigravity-generation', help='require this registered bridge generation')
    sending.add_argument('--request-id', help='attempt UUID for paired-device journaling or generation-pinned Antigravity deduplication')
    bridge = subparsers.add_parser('antigravity-bridge', help='opt-in bridge; start inside the target agy TUI tool environment')
    bridge.add_argument('action', choices=('serve', 'stop'))
    bridge.add_argument('--thread', required=True, help='exact existing Antigravity conversation UUID')
    bridge.add_argument('--antigravity-home', help='target home (default: ~/.gemini/antigravity-cli)')
    bridge.add_argument('--ttl', type=int, choices=range(1, 86401), default=3600, metavar='SECONDS')
    bridge.add_argument('--max-requests', type=int, choices=range(1, 10001), default=1000, metavar='COUNT')
    bridge.set_defaults(func=cmd_agy_bridge, json=False, no_update_notice=True)

    for sub in (listing, sending):
        sub.add_argument('--device', help='paired receiver fingerprint; exclusive with --host')
        sub.add_argument('--device-state', help='local device state directory')
        sub.add_argument('--device-route', choices=('auto', 'direct', 'relay'), default='auto')
        sub.add_argument('--relay-admission-file', help='private client admission credential file')
        sub.add_argument('--relay-login', action='store_true', help='use an explicitly saved device login for relay admission')
    for name in ('device', 'relay'):
        sub = subparsers.add_parser(name, add_help=False, help='optional paired-device '+name+' management')
        sub.add_argument('--help', '-h', dest='relay_help', action='store_true')
        sub.add_argument('relay_args', nargs=argparse.REMAINDER)
        sub.set_defaults(func=cmd_optional_relay, json=True, no_update_notice=True)
    setup = subparsers.add_parser('setup', help='explicit connection choices and guided paired-device setup')
    add_common(setup)
    setup.add_argument('--mode', choices=('local', 'ssh', 'relay'))
    setup.add_argument('--interactive', action='store_true', help='ask before each setup mutation; EOF/Ctrl-C cancels')
    setup.add_argument('--action', choices=('plan', 'init', 'login', 'enroll', 'targets', 'policy', 'invite', 'offer', 'offer-status', 'offer-cancel', 'pair', 'ready', 'receiver', 'cancel'), default='plan')
    setup.add_argument('--apply', action='store_true', help='explicitly approve the selected setup action, never a message send')
    setup.add_argument('--state')
    setup.add_argument('--server')
    setup.add_argument('--name')
    setup.add_argument('--no-browser', action='store_true')
    setup.add_argument('--role', choices=('receiver', 'client'), default='receiver')
    setup.add_argument('--policy')
    setup.add_argument('--target', help='exact native target; Claude uses the selected PID, not an ambiguous name')
    setup.add_argument('--alias', default='main')
    setup.add_argument('--peer', help='explicit trusted paired-device principal (64 lowercase hexadecimal characters)')
    setup.add_argument('--capability', action='append', choices=('list', 'send'), default=[])
    setup.add_argument('--codex-home')
    setup.add_argument('--codex-bin')
    setup.add_argument('--antigravity-home')
    setup.add_argument('--direct')
    setup.add_argument('--relay', help='receiver WSS connect URL, not an account-login URL')
    source = setup.add_mutually_exclusive_group()
    source.add_argument('--invite', help='private existing invitation file for a client')
    source.add_argument('--link', action='store_true', help='read private pairing link from an echo-disabled terminal; no argument value')
    setup.add_argument('--peer-key', help='intended client current certificate fingerprint, confirmed independently')
    setup.add_argument('--show-link', action='store_true', help='explicitly display a private offer link on the owner terminal')
    setup.add_argument('--offer-id', help='public offer UUID for status/cancellation')
    setup.add_argument('--out', help='new private invitation file for a receiver')
    setup.add_argument('--route', choices=('auto', 'direct', 'relay'), default='auto')
    setup.add_argument('--seconds', type=int, choices=range(1, 86401), default=3600, metavar='SECONDS')
    setup.set_defaults(func=cmd_setup, json=False, no_update_notice=True, agent=None, all=False)
    addresses = subparsers.add_parser("address", help="explicit local recipient references; not person identity or permissions")
    address_sub = addresses.add_subparsers(dest="address_action", required=True)
    for action in ("resolve", "add", "list", "show", "discover", "reselect", "remove", "_inspect"):
        sub = address_sub.add_parser(action, help=argparse.SUPPRESS if action == "_inspect" else None)
        sub.add_argument("--json", action="store_true")
        sub.add_argument("--output-format", choices=("text", "json"))
        sub.add_argument("--no-update-notice", action="store_true", default=True)
        sub.set_defaults(func=cmd_address_inspect if action == "_inspect" else cmd_address,
                         no_update_notice=True, host=[], ssh_opt=[])
        if action in ("add", "show", "reselect", "remove"):
            sub.add_argument("name")
        if action in ("resolve", "add"):
            sub.add_argument("--preset", required=True, action=PresetSingleUseAction)
        if action in ("resolve", "add", "reselect"):
            sub.add_argument("--to", required=True, action=PresetSingleUseAction)
        if action in ("add", "reselect"):
            sub.add_argument("--expect-selection", required=True, action=PresetSingleUseAction)
        if action == "add":
            sub.add_argument("--label", action=PresetSingleUseAction)
        if action in ("reselect", "remove"):
            sub.add_argument("--expect-revision", required=True, action=PresetSingleUseAction)
        if action == "discover":
            sub.add_argument("--address", required=True, action="append")
        if action == "_inspect":
            sub.add_argument("--agent", required=True, choices=("claude", "codex"))
            sub.add_argument("--to", required=True, action="append")
            sub.add_argument("--codex-home")
    return parser


def json_error_result(args: argparse.Namespace, payload: dict) -> dict | list[dict]:
    """Attribute command-wide failures to every requested destination."""
    command = getattr(args, "command", None) or "unknown"
    hosts = list(getattr(args, "host", None) or [])
    if not hosts:
        return json_result(command, payload, ok=False)
    return one_or_many([
        json_result(command, payload, host=host, ok=False)
        for host in hosts
    ])


def address_operation_failed(args):
    message = "Address operation failed; inspect current state before deciding what to do"
    if args.json:
        print(json.dumps(json_error_result(args, {"error": message, "reason": "address_operation_failed"}), ensure_ascii=False))
    else:
        print("session-peer: " + message, file=sys.stderr)
    return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    # Invocation-local authority, never an environment setting, MCP default or
    # leaked state from a previous/reentrant call in the same interpreter.
    token = SSH_CONFIG_SELECTION.set(None)
    try:
        return _main(argv)
    finally:
        SSH_CONFIG_SELECTION.reset(token)


def _main(argv: list[str] | None = None) -> int:
    global _CLIENT_UPDATE_NOTICE, _SKILL_UPDATE_NOTICES
    cli_invocation = argv is None
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if len(raw_argv) == 2 and raw_argv[0] == HANDOFF_SENDER_PREFLIGHT_ARG:
        try:
            cutoff = float(raw_argv[1])
            if IS_WINDOWS or not __import__("math").isfinite(cutoff) or handoff_now() >= cutoff:
                raise ValueError()
            return handoff_sender_preflight_child(cutoff)
        except (CcPeerError, HandoffStdinError, OSError, ValueError, KeyError, TypeError):
            print('{"ok":false,"reason":"sender_preflight_unavailable"}')
            return 1
    if len(raw_argv) == 2 and raw_argv[0] == HANDOFF_PRODUCER_ARG:
        if IS_WINDOWS:
            return 1
        try:
            return cmd_ack(argparse.Namespace(json=True), root=Path(raw_argv[1]))
        except (CcPeerError, OSError, ValueError):
            print('{"ok":false,"reason":"receipt_operation_refused"}')
            return 1
    if len(raw_argv) == 2 and raw_argv[0] == HANDOFF_COLLECTOR_ARG:
        if IS_WINDOWS:
            return 1
        try:
            return handoff_collector(Path(raw_argv[1]))
        except (CcPeerError, OSError, ValueError):
            return 1
    if raw_argv == [UPDATE_REFRESH_ARG]:
        return refresh_update_cache_background()

    if IS_WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(raw_argv)
    if getattr(args, "preset", None) is not None:
        args._preset_explicit_options = sorted(preset_explicit_options(parser))
    output_format = getattr(args, "output_format", None)
    if args.json and output_format == "text":
        parser.error("--json conflicts with --output-format text")
    args.json = args.json or output_format == "json"
    if getattr(args, "explain", False):
        if args.json:
            parser.error("--explain requires text output")
        if args.command == "send":
            if not args.dry_run:
                parser.error("--explain requires --dry-run")
            if handoff_requested(args) or any(getattr(args, key, None) is not None for key in (
                    "_handoff_native_context", "_handoff_native_cutoff_ms", "_handoff_native_total_ms")):
                parser.error("--explain does not support experimental handoff sends")
        elif args.command == "handoff" and args.handoff_action != "status":
            parser.error("--explain requires handoff status")
        args._delivery_explanation_started = False
        args._delivery_explanation_host = None
    if runtime_notice_preference_requested(args):
        if runtime_notice_preference_routed(args):
            parser.error("Runtime notice preferences are local only; do not use host or SSH options")
        args.no_update_notice = True
    if args.command == "send":
        if not getattr(args, "address", None) and args.to is None:
            parser.error("the following arguments are required: --to")
        if getattr(args, "address", None) or getattr(args, "address_revision", None) or getattr(args, "confirm_target", None):
            args._address_explicit_options = sorted(preset_explicit_options(parser))
    # Route checks precede advisory background work, stdin and transport. An
    # opt-out invocation does not even read the presets configuration.
    _CLIENT_UPDATE_NOTICE, _SKILL_UPDATE_NOTICES = None, []
    try:
        if args.command == "send":
            prepare_address_route(parser, args, raw_argv)
        if args.command in ("list", "send"):
            prepare_preset_route(parser, args, raw_argv)
    except KeyboardInterrupt:
        return 130
    except CcPeerError as exc:
        if args.json:
            print(json.dumps(json_error_result(args, {"error": str(exc), **exc.details}), ensure_ascii=False))
        else:
            print(human_text(f"session-peer: {exc}"), file=sys.stderr)
        return EXIT_ERROR
    except Exception:
        return address_operation_failed(args) if getattr(args, "address", None) else preset_operation_failed(args)
    if args.command in ("preset", "address"):
        try:
            return args.func(args)
        except KeyboardInterrupt:
            return 130
        except CcPeerError as exc:
            if args.json:
                print(json.dumps(json_result(args.command, {"error": str(exc), **exc.details}, ok=False), ensure_ascii=False))
            else:
                print(human_text(f"session-peer: {exc}"), file=sys.stderr)
            return EXIT_ERROR
        except Exception:
            return address_operation_failed(args) if args.command == "address" else preset_operation_failed(args)
    try:
        prepare_trusted_ssh_config(parser, args)
    except CcPeerError as exc:
        if args.json:
            print(json.dumps(json_error_result(args, {"error": str(exc), **exc.details}), ensure_ascii=False))
        else:
            print(human_text(f"session-peer: {exc}"), file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130
    try:
        _CLIENT_UPDATE_NOTICE = prepare_client_update(args) if cli_invocation else None
    except Exception:
        # Update discovery is advisory. Even an unexpected cache or launcher
        # failure must not change the requested command's result or exit code.
        _CLIENT_UPDATE_NOTICE = None
    try:
        _SKILL_UPDATE_NOTICES = prepare_skill_updates(args) if cli_invocation else []
    except Exception:
        _SKILL_UPDATE_NOTICES = []
    show_human_notice = True
    try:
        validate_ssh_identity_options(args)
        exit_code = args.func(args)
    except CcPeerError as exc:
        message = redact_ssh_config_path(str(exc))
        if args.json:
            payload = json_error_result(args, {"error": message, **exc.details})
            print(json.dumps(with_client_update(payload), ensure_ascii=False))
        else:
            print(human_text(f"session-peer: {message}"), file=sys.stderr)
            if getattr(args, "explain", False):
                emit_delivery_explanation(args, exc.details, failed=True, stream=sys.stderr,
                                          mode="doctor" if args.command == "doctor" else "existing_intent" if args.command == "handoff" else "readiness",
                                          host=getattr(args, "_delivery_explanation_host", None))
        exit_code = (
            EXIT_NO_TARGET
            if isinstance(exc, NoTargetError) or "no reachable session" in message
            else EXIT_ERROR
        )
    except KeyboardInterrupt:
        show_human_notice = False
        exit_code = 130
    except Exception as exc:
        message = redact_ssh_config_path(f"{type(exc).__name__}: {exc}")
        if getattr(args, "json", False):
            payload = json_error_result(args, {"error": message})
            print(json.dumps(with_client_update(payload), ensure_ascii=False))
        else:
            print(human_text(f"session-peer: {message}"), file=sys.stderr)
            if getattr(args, "explain", False):
                explanation = ({"reason": "outcome_unknown"}
                               if getattr(args, "_delivery_explanation_started", False) else {})
                emit_delivery_explanation(args, explanation, failed=True, stream=sys.stderr,
                                          mode="doctor" if args.command == "doctor" else "existing_intent" if args.command == "handoff" else "readiness",
                                          host=getattr(args, "_delivery_explanation_host", None))
        exit_code = EXIT_ERROR
    if show_human_notice and not args.json:
        emit_human_update_notice()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
