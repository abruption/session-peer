def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session-peer",
        description="Message Claude Code and Codex sessions locally or over SSH.",
    )
    parser.add_argument("--version", action="version", version=f"session-peer {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--host", action="append", default=[], metavar="DEST",
            help="SSH [USER@]HOST, repeatable; otherwise User comes from SSH config/default",
        )
        sub.add_argument(
            "--ssh-opt",
            action="append",
            default=[],
            metavar="OPT",
            help="extra ssh argument, repeatable (e.g. --ssh-opt -p --ssh-opt 2222)",
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
    home_help = ("select one Codex home on the destination (default: CODEX_HOME or ~/.codex); "
                 "set explicitly for Orca/multiple homes")
    listing.add_argument("--codex-home", help="list only this destination home (default: known default, CODEX_HOME, Orca and configured homes)")
    listing.add_argument("--codex-bin", help="Codex executable on the destination (used by send)")
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
    sending.add_argument(
        "--to", required=True, metavar="TARGET|REPLY-URI",
        help="session name, PID, codex:UUID, antigravity:UUID, or session-peer://v1/reply address",
    )
    sending.add_argument("--codex-home", help=home_help)
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
    sending.add_argument("--b64", help=argparse.SUPPRESS)  # used for remote dispatch
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
    sending.add_argument("--wake-timeout", type=int, choices=range(1, 61), default=30, metavar="SECONDS",
                         help="wake deadline, 1..60 seconds (default: 30)")
    sending.add_argument("--dry-run", action="store_true", help="resolve the target, send nothing")
    sending.set_defaults(func=cmd_send)

    updating = subparsers.add_parser("update", help="update this installation")
    add_common(updating)
    updating.add_argument(
        "--check", action="store_true", help="report the available version, change nothing"
    )
    updating.set_defaults(func=cmd_update)

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


def main(argv: list[str] | None = None) -> int:
    global _CLIENT_UPDATE_NOTICE
    cli_invocation = argv is None
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv == [UPDATE_REFRESH_ARG]:
        return refresh_update_cache_background()

    if IS_WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(raw_argv)
    output_format = getattr(args, "output_format", None)
    if args.json and output_format == "text":
        parser.error("--json conflicts with --output-format text")
    args.json = args.json or output_format == "json"
    try:
        _CLIENT_UPDATE_NOTICE = prepare_client_update(args) if cli_invocation else None
    except Exception:
        # Update discovery is advisory. Even an unexpected cache or launcher
        # failure must not change the requested command's result or exit code.
        _CLIENT_UPDATE_NOTICE = None
    show_human_notice = True
    try:
        exit_code = args.func(args)
    except CcPeerError as exc:
        message = str(exc)
        if args.json:
            payload = json_error_result(args, {"error": message, **exc.details})
            print(json.dumps(with_client_update(payload), ensure_ascii=False))
        else:
            print(f"session-peer: {message}", file=sys.stderr)
        exit_code = (
            EXIT_NO_TARGET
            if isinstance(exc, NoTargetError) or "no reachable session" in message
            else EXIT_ERROR
        )
    except KeyboardInterrupt:
        show_human_notice = False
        exit_code = 130
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if getattr(args, "json", False):
            payload = json_error_result(args, {"error": message})
            print(json.dumps(with_client_update(payload), ensure_ascii=False))
        else:
            print(f"session-peer: {message}", file=sys.stderr)
        exit_code = EXIT_ERROR
    if show_human_notice and not args.json:
        emit_human_update_notice()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
