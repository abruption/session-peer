def cmd_list(args: argparse.Namespace) -> int:
    if getattr(args, "device", None):
        return optional_relay().invoke_core(args)
    selected = getattr(args, "agent", None)
    if not args.host:
        result = collect_listing(args)
        emit(args.json, result, render_listing(result, "this machine", selected), command="list")
        return 0 if result["ok"] else EXIT_ERROR

    exit_code = 0
    all_results = []
    tailnet_status = tailscale_status() or {}
    for requested_host in args.host:
        host = requested_host
        try:
            transport = SshTransport(requested_host, args, tailnet_status)
            host, ssh_opts = transport.host, transport.ssh_opts
            argv = ["list", "--no-update-notice"] + (["--all"] if args.all else [])
            if selected:
                argv += ["--agent", selected]
            argv += agent_remote_options(args, selected)
            result = transport.execute(argv)
            sessions = result.get("sessions", [])
            ssh_info = ssh_metadata_from(result)
            remote_version = remote_installed_version(requested_host, ssh_opts, ssh_info)
            shown_host = display_host(requested_host, host)
            human = render_listing(result, shown_host, selected)
            if result.get("ok") is False:
                exit_code = EXIT_ERROR
            if remote_version and remote_version != __version__:
                human = (
                    f"{shown_host} runs session-peer {remote_version}; this machine has {__version__}."
                    f"\nUpdate it with:  session-peer update --host {requested_host}\n\n{human}"
                )
            host_result = json_result("list", {
                **host_metadata(requested_host, host),
                **ssh_info,
                **{key: result[key] for key in ("discovery", "error", "codexHome")
                   if key in result},
                "ok": result.get("ok", True),
                "sessions": sessions, "version": __version__,
                **({"remoteVersion": remote_version} if remote_version else {}),
            })
            all_results.append(host_result)
            if not args.json:
                if len(all_results) > 1:
                    print()
                print(human)
        except CcPeerError as exc:
            exit_code = EXIT_ERROR
            all_results.append(json_result(
                "list",
                {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                ok=False,
            ))
            if not args.json:
                print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)

    if args.json:
        emit_json_results(all_results)
    return exit_code


def _doctor_return_host(args: argparse.Namespace) -> str | None:
    host = configured_reply_host(getattr(args, "reply_to", None)) or detect_reply_host()
    if host and "@" not in host:
        host = f"{getpass.getuser()}@{host}"
    return host


def cmd_doctor(args: argparse.Namespace) -> int:
    if args.reply_to and not args.check_return_route:
        raise CcPeerError("--reply-to requires --check-return-route")

    if not args.host:
        if args.check_return_route and not args._return_host:
            args._return_host = _doctor_return_host(args)
        payload = doctor_payload(args)
        if args.check_return_route and not args._return_host:
            payload["returnRoute"] = {
                "status": "failed", "transport": "ssh", "host": None,
                "reason": "return_host_unavailable",
            }
        emit(
            args.json, payload, render_doctor(payload, "this machine"), command="doctor",
        )
        return 0

    exit_code = 0
    all_results = []
    tailnet_status = tailscale_status() or {}
    return_host = _doctor_return_host(args) if args.check_return_route else None
    for requested_host in args.host:
        host = requested_host
        try:
            transport = SshTransport(requested_host, args, tailnet_status)
            host, ssh_opts = transport.host, transport.ssh_opts
            remote_argv = ["doctor", "--no-update-notice"] + agent_remote_options(args)
            if return_host:
                remote_argv.extend(["--_return-host", return_host])
            result = transport.execute(remote_argv)
            payload = {
                key: value for key, value in result.items()
                if key not in {"schemaVersion", "ok", "host", "command", *SSH_METADATA_FIELDS}
            }
            if args.check_return_route and not return_host:
                payload["returnRoute"] = {
                    "status": "failed", "transport": "ssh", "host": None,
                    "reason": "return_host_unavailable",
                }
            host_result = json_result("doctor", {
                **host_metadata(requested_host, host), **ssh_metadata_from(result), **payload,
            })
            all_results.append(host_result)
            if not args.json:
                if len(all_results) > 1:
                    print()
                print(render_doctor(payload, display_host(requested_host, host)))
        except CcPeerError as exc:
            exit_code = EXIT_ERROR
            all_results.append(json_result(
                "doctor",
                {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                ok=False,
            ))
            if not args.json:
                print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)
    if args.json:
        emit_json_results(all_results)
    return exit_code
