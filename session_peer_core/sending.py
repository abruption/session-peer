def cmd_send(args: argparse.Namespace) -> int:
    if getattr(args, "device", None):
        return optional_relay().invoke_core(args)
    resolved_address = apply_reply_target(args)
    text = read_message(args)
    adapter = AGENTS.for_target(args.to)
    if resolved_address and resolved_address["agent"] != adapter.name:
        raise AdapterError(adapter.name, "invalid_target", "Reply URI agent conflicts with target")
    validate_agent_send(adapter, args)

    # Check the body the user actually wrote. Doing this after the reply line
    # is appended would let an empty message through on the strength of the
    # line alone — which still starts a turn on the other machine.
    check_message(text, remote=bool(args.host))

    # Built here, before dispatch: detection has to run on the sender's machine.
    # Doing it on the far side would advertise the receiver's own address back
    # at it. The --b64 path is this script re-running remotely, where the
    # envelope is already part of the payload.
    advertised_route = None
    if args.b64 is None:
        identity = (
            sender_identity(args.reply_to)
            if not args.no_from or not args.no_reply_to else None
        )
        configured_host = configured_reply_host(args.reply_to)
        local_reply = not args.host and (
            configured_host is None
            or bool(
                identity
                and identity.get("host")
                and is_self_ssh_destination(str(identity["host"]))
            )
        )
        text = wrap_message(
            text,
            explicit_host=args.reply_to,
            with_from=not args.no_from,
            with_reply=not args.no_reply_to,
            local_reply=local_reply,
            identity=identity,
        )
        if not args.no_reply_to:
            advertised_route = reply_route(identity, local_reply)
        if (
            not args.no_reply_to
            and (args.reply_to or (os.environ.get("SESSION_PEER_REPLY_HOST") or os.environ.get("CC_PEER_REPLY_HOST")))
            and identity is None
            and not args.json
        ):
            # A reply address names a session, and outside one there is no name
            # to give. Say so rather than dropping the flag without a word.
            print(
                "session-peer: no reply address sent — a reply needs a session to name, "
                "and this isn't running inside one",
                file=sys.stderr,
            )

    routing_metadata = {}
    if advertised_route:
        routing_metadata["replyRoute"] = advertised_route
    if resolved_address:
        routing_metadata["addressResolution"] = {
            "uri": resolved_address["uri"],
            "transport": resolved_address["transport"],
            **({"normalizedFrom": resolved_address["normalizedFrom"]}
               if "normalizedFrom" in resolved_address else {}),
        }

    validate_agent_send(adapter, args, text)

    if not args.host:
        result = LocalTransport().execute("send", adapter, args, text)
        result.update(routing_metadata)
        emit(args.json, result, adapter.submission_text(result, "this machine"), command="send")
        if advertised_route and advertised_route["status"] == "unverified" and not args.json:
            print(
                "session-peer: reverse SSH reply route was not checked; "
                "run doctor --check-return-route to test it", file=sys.stderr)
        return 0 if result.get("ok", True) else EXIT_ERROR

    exit_code = 0
    all_results = []
    tailnet_status = tailscale_status() or {}
    for requested_host in args.host:
        host = requested_host
        try:
            transport = SshTransport(requested_host, args, tailnet_status)
            host, ssh_opts = transport.host, transport.ssh_opts
            shown_host = display_host(requested_host, host)
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            remote_argv = ["send", "--no-update-notice", "--to", args.to, "--b64", encoded]
            remote_argv += adapter.remote_options(args)
            if args.dry_run:
                remote_argv.append("--dry-run")
            result = transport.execute(remote_argv)
            payload = adapter.remote_submission(result, args, text)
            payload.update(host_metadata(requested_host, host))
            payload.update(routing_metadata)
            all_results.append(json_result("send", payload))
            if payload.get("ok") is False:
                exit_code = EXIT_ERROR
            if not args.json:
                print(adapter.submission_text(payload, shown_host))
        except CcPeerError as exc:
            exit_code = EXIT_ERROR
            all_results.append(json_result(
                "send",
                {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                ok=False,
            ))
            if not args.json:
                print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)

    if args.json:
        emit_json_results(all_results)
    elif (
        advertised_route and advertised_route["status"] == "unverified"
        and any(result.get("ok") for result in all_results)
    ):
        print(
            "session-peer: reverse SSH reply route was not checked; "
            "run doctor --check-return-route to test it",
            file=sys.stderr,
        )
    return exit_code
