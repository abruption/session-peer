"""Private source-streamed native snapshots, not a receipt/collector route."""
HANDOFF_SENDER_PREFLIGHT_ARG = "--_handoff-sender-preflight"


def handoff_sender_preflight_child(cutoff):
    """Metadata only, in an owned child bounded by the ORIGINAL sender budget.

    Legacy sender discovery/Tailscale/user probes cannot renew the parent's
    deadline. Body data travels over private stdin/stdout, never argv, and no
    ledger/receipt/native effect is created by this helper.
    """
    raw = read_handoff_stdin(sys.stdin, cutoff, handoff_now).encode("utf-8")
    frame = handoff_json(raw, 1048576)
    keys = {"to", "host", "codexHome", "replyTo", "noFrom", "noReplyTo", "body", "encodedInput"}
    if type(frame) is not dict or set(frame) != keys or any(type(frame[k]) is not bool for k in ("noFrom", "noReplyTo", "encodedInput")):
        raise handoff_error("sender_preflight_invalid")
    if type(frame["host"]) is not list or len(frame["host"]) > 1 or type(frame["body"]) is not str:
        raise handoff_error("sender_preflight_invalid")
    for value in [frame["to"]] + frame["host"]:
        handoff_identifier(value, 4096)
    for value in (frame["codexHome"], frame["replyTo"]):
        if value is not None:
            handoff_identifier(value, 4096)
    args = argparse.Namespace(to=frame["to"], host=frame["host"], codex_home=frame["codexHome"])
    address = apply_reply_target(args)
    identity, routing, local_reply = None, {}, False
    body = frame["body"]
    if not frame["encodedInput"] and (not frame["noFrom"] or not frame["noReplyTo"]):
        identity = sender_identity(frame["replyTo"])
        configured = configured_reply_host(frame["replyTo"])
        local_reply = not args.host and (configured is None or bool(identity and identity.get("host") and is_self_ssh_destination(str(identity["host"]))))
        body = wrap_message(body, explicit_host=frame["replyTo"], with_from=not frame["noFrom"],
                            with_reply=not frame["noReplyTo"], local_reply=local_reply, identity=identity)
        if not frame["noReplyTo"]:
            route = reply_route(identity, local_reply)
            if route:
                routing["replyRoute"] = route
    if address:
        routing["addressResolution"] = {key: address[key] for key in ("uri", "transport", "normalizedFrom") if key in address}
    status = tailscale_status() or {} if args.host else {}
    if handoff_now() >= cutoff:
        raise handoff_error("deadline_before_effect")
    result = {"to": args.to, "host": args.host, "codexHome": args.codex_home,
              "body": body, "tailnet": status, "address": address, "routing": routing}
    raw = HandoffLedger.encode(result)
    if len(raw) > 1048576:
        raise handoff_error("sender_preflight_capacity")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()
    return 0


def handoff_sender_preflight(args, text, cutoff, total):
    frame = {"to": args.to, "host": args.host, "codexHome": args.codex_home,
             "replyTo": args.reply_to, "noFrom": args.no_from, "noReplyTo": args.no_reply_to,
             "body": text, "encodedInput": args.b64 is not None}
    for path in (Path(sys.executable).resolve(), Path(__file__).resolve()):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in (0, os.getuid()):
            raise handoff_error("sender_preflight_unavailable")
    done = handoff_stream_child([sys.executable, "-I", str(Path(__file__).resolve()),
                        HANDOFF_SENDER_PREFLIGHT_ARG, str(cutoff)], HandoffLedger.encode(frame), cutoff, total, handoff_now)
    if done.interrupted:
        raise KeyboardInterrupt
    if done.returncode not in (0, -signal.SIGKILL) or done.reason or done.stdout_overflow or done.cleanup_failed:
        raise handoff_error("sender_preflight_unavailable")
    try:
        result = handoff_json(done.stdout, 1048576)
        if type(result) is not dict or set(result) != {"to", "host", "codexHome", "body", "tailnet", "address", "routing"}:
            raise ValueError()
        handoff_identifier(result["to"], 4096)
        if type(result["host"]) is not list or len(result["host"]) > 1 or any(type(host) is not str for host in result["host"]):
            raise ValueError()
        for host in result["host"]:
            check_ssh_argument(host, "--host")
        if result["codexHome"] is not None:
            handoff_identifier(result["codexHome"], 4096)
        if type(result["body"]) is not str or type(result["tailnet"]) is not dict or result["address"] is not None and type(result["address"]) is not dict:
            raise ValueError()
        check_message(result["body"], remote=bool(result["host"]))
        handoff_routing_metadata(result["routing"])
        address = parse_reply_address(args.to)
        expected_target = address["target"] if address else args.to
        expected_home = address.get("codexHome", args.codex_home) if address else args.codex_home
        expected_hosts = [address["host"]] if address and address["transport"] == "ssh" else args.host
        if result["to"] != expected_target or result["codexHome"] != expected_home:
            raise ValueError()
        if result["host"] != expected_hosts:
            # Only the actual normalizer's explicitly identified SSH-self
            # result may remove a URI host. Never silently rewrite aliases.
            proof = result["address"]
            if not (address and not result["host"] and type(proof) is dict and
                    proof.get("normalizedFrom") == "ssh_self" and proof.get("transport") == "local"
                    and proof.get("uri") == address["uri"]):
                raise ValueError()
        if handoff_now() >= cutoff:
            raise ValueError()
        return result
    except (CcPeerError, KeyError, ValueError, TypeError, UnicodeError) as exc:
        raise handoff_error("sender_preflight_unavailable") from exc


def handoff_routing_metadata(value):
    if type(value) is not dict or not set(value) <= {"replyRoute", "addressResolution"} or len(HandoffLedger.encode(value)) > 16384:
        raise handoff_error("invalid_routing_metadata")
    for key, record in value.items():
        required = {"uri", "transport", "status", "reason"} if key == "replyRoute" else {"uri", "transport"}
        allowed = required if key == "replyRoute" else required | {"normalizedFrom"}
        if type(record) is not dict or not required <= set(record) <= allowed:
            raise handoff_error("invalid_routing_metadata")
        address = parse_reply_address(record["uri"])
        if address is None or address["transport"] != record["transport"]:
            # A normalized SSH-self URI still names the original ssh transport;
            # the explicit normalization marker is the only local exception.
            if not (key == "addressResolution" and address is not None and address["transport"] == "ssh"
                    and record["transport"] == "local" and record.get("normalizedFrom") == "ssh_self"):
                raise handoff_error("invalid_routing_metadata")
        if key == "replyRoute" and (record["status"], record["reason"]) != (("verified", "same_machine_route") if record["transport"] == "local" else ("unverified", "reverse_ssh_not_checked")):
            raise handoff_error("invalid_routing_metadata")
        if "normalizedFrom" in record and record["normalizedFrom"] != "ssh_self":
            raise handoff_error("invalid_routing_metadata")
    return value


def handoff_ssh_metadata(response):
    result = {}
    if "sshUser" in response:
        if response["sshUser"] is not None:
            handoff_identifier(response["sshUser"], 1024)
        if response.get("sshUserSource") not in ("explicit", "ssh_config_or_local_default", "unknown"):
            raise handoff_error("invalid_ssh_metadata")
        result.update(sshUser=response["sshUser"], sshUserSource=response["sshUserSource"])
    if "sshIdentity" in response:
        identity = response["sshIdentity"]
        required = {"schemaVersion", "status", "destination", "port", "keyLookupName"}
        allowed = required | {"algorithm", "fingerprint"}
        if (type(identity) is not dict or not required <= set(identity) <= allowed
                or type(identity["schemaVersion"]) is not int or identity["schemaVersion"] != 1
                or identity["status"] not in ("verified", "unsupported", "unknown", "observed", "refused")
                or type(identity["port"]) is not int or not 1 <= identity["port"] <= 65535):
            raise handoff_error("invalid_ssh_metadata")
        for key in ("destination", "keyLookupName", "algorithm", "fingerprint"):
            if key in identity:
                handoff_identifier(identity[key], 1024)
        if "fingerprint" in identity and re.fullmatch(SSH_FINGERPRINT_PATTERN, identity["fingerprint"]) is None:
            raise handoff_error("invalid_ssh_metadata")
        result["sshIdentity"] = identity
    return result


def handoff_remote_argv(args, context, text, cutoff=None, total=None):
    encoded = base64.b64encode(HandoffLedger.encode(context)).decode("ascii")
    argv = ["send", "--_handoff-native-context=" + encoded,
            "--to=" + ("codex:" + codex_thread(context["target"]) if context["agent"] == "codex" else context["target"]),
            "--b64=" + base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "--no-update-notice", "--no-from", "--no-reply-to"]
    if context["home"] is not None:
        argv.append("--codex-home=" + context["home"])
    if context["agent"] == "codex":
        if args.codex_bin is not None:
            argv.append("--codex-bin=" + args.codex_bin)
        if args.allow_inactive_codex_home:
            argv.append("--allow-inactive-codex-home")
    if context["phase"] == "probe":
        now = handoff_now()
        remaining_cutoff = int(max(0, cutoff - now) * 1000)
        remaining_total = int(max(0, total - now) * 1000)
        if remaining_cutoff < 1 or remaining_total > 60000:
            raise handoff_error("deadline_before_effect")
        argv += ["--_handoff-native-cutoff-ms=" + str(remaining_cutoff), "--_handoff-native-total-ms=" + str(remaining_total)]
    handoff_validate_remote_argv(argv, context)
    remote = " ".join(shlex.quote(value) for value in ["python3", "-", *argv, "--json"])
    if len(remote.encode("utf-8")) > MAX_SSH_COMMAND_BYTES:
        raise handoff_error("ssh_command_too_large")
    return argv


def handoff_remote_evidence(response, context, expected_chars, prepared):
    """Revalidate known facts, including those retained by identity errors."""
    proof = response["handoffNative"]
    envelope = {"schemaVersion": 1, "ok": proof["native"]["ok"], "command": "send",
                "host": response["host"], "handoffNative": proof}
    validated = handoff_validate_remote_response(envelope, context)
    native = dict(validated["handoffNative"]["native"])
    if native["ok"]:
        handoff_validate_native(native, prepared)
        if native["chars"] != expected_chars:
            raise handoff_error("invalid_remote_native_profile")
    return native


def cmd_handoff_remote_send(args, cutoff, total):
    """One sender-owned fenced SSH submission, not a remote ACK/observer.

    Metadata probes are harmless and bounded by the original destination
    budget. A durable intent is committed before the ONLY effect command;
    neither a missing response nor reconciliation can authorize another send.
    """
    import copy
    import hashlib
    if len(args.host) > 1 or IS_WINDOWS or getattr(args, "device", None) or args.wake:
        raise handoff_error("handoff_route_unsupported")
    if args.dry_run and (args.request_ack or args.observe_delivery or args.wait_for):
        raise NoTargetError("--dry-run cannot request observation, ACK or waiting")
    message = args.message_option if args.message_option is not None else args.message
    try:
        text = read_handoff_stdin(sys.stdin, cutoff, handoff_now) if args.b64 is None and args.message_file is None and (message is None or message == "-") else read_message(args)
    except HandoffStdinError as exc:
        emit(args.json, {"ok": False, **exc.details}, "Handoff input refused before submission.", command="send")
        return exc.exit_code
    # A structured SSH-self URI can normalize to the local transport.  Do not
    # impose the SSH argv limit until its bounded normalizer confirms SSH.
    check_message(text, remote=bool(args.host))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ledger = HandoffLedger()
    original = None
    if args.correlation_id is not None:
        # No new metadata/SSH connection for consumed, missing or corrupted
        # history. A retained prepared intent still must match after probing.
        _, original = ledger.record(args.correlation_id, total)
        if original["phase"] != "prepared":
            raise handoff_error("handoff_already_attempted")
        if original["binding"]["payloadDigest"] != digest:
            raise handoff_error("handoff_binding_conflict")
    address = parse_reply_address(args.to)
    plain = copy.copy(args)
    if address is not None:
        if args.host:
            raise NoTargetError("Do not combine a Reply-To URI with --host")
        plain.to, plain.host = address["target"], [address["host"]]
        if address.get("codexHome") is not None:
            if args.codex_home is not None and args.codex_home != address["codexHome"]:
                raise NoTargetError("Reply-To codexHome conflicts with --codex-home")
            plain.codex_home = address["codexHome"]
    adapter = AGENTS.for_target(plain.to)
    validate_target_generation(plain.target_generation)
    if adapter.name != "claude" and plain.target_generation is not None:
        raise generation_refused("unsupported_target_generation", "This native route has no generation evidence")
    validate_agent_send(adapter, plain, text)
    for host in plain.host:
        check_ssh_argument(host, "--host")
    check_ssh_options(plain.ssh_opt)
    metadata = None
    if address is not None:
        # Resolve SSH-self using bounded normal metadata before deciding that
        # the evidence channel is remote/unsupported. A retained consumed ID
        # was already refused above without any further metadata connection.
        try:
            metadata = handoff_sender_preflight(args, text, cutoff, total)
        except KeyboardInterrupt:
            emit(args.json, {"ok": False, "reason": "sender_preflight_stopped", "retryAllowed": False}, "Handoff stopped before submission.", command="send")
            return 130
        plain.to, plain.host, plain.codex_home = metadata["to"], metadata["host"], metadata["codexHome"]
        if not plain.host:
            plain._handoff_fixed_total = total
            plain._handoff_wrapped_body = metadata["body"]
            plain._handoff_routing_metadata = handoff_routing_metadata(metadata.get("routing", {}))
            # Preserve the ORIGINAL raw payload for the durable intent digest;
            # reuse the prebuilt envelope only immediately before framing.
            plain.message_option, plain.message, plain.message_file, plain.b64 = text, None, None, None
            return cmd_handoff_send(plain)
    check_message(text, remote=True)
    if original is not None and original["binding"]["destination"] != plain.host:
        raise handoff_error("handoff_binding_conflict")
    if args.wait_for or args.wait_timeout <= 5 or handoff_now() >= cutoff:
        target = codex_thread(plain.to) if adapter.name == "codex" else plain.to
        binding = {"agent": adapter.name, "destination": plain.host, "target": target,
                   "home": plain.codex_home if adapter.name == "codex" else None, "payloadDigest": digest}
        epoch, record = ledger.prepare(binding, None, args.correlation_id, total)
        reason = "evidence_unsupported" if args.wait_for else "insufficient_budget" if args.wait_timeout <= 5 else "deadline_before_effect"
        return handoff_refuse_send(ledger, record["id"], plain, reason, total)
    try:
        metadata = metadata if metadata is not None else handoff_sender_preflight(args, text, cutoff, total)
    except KeyboardInterrupt:
        emit(args.json, {"ok": False, "reason": "sender_preflight_stopped", "retryAllowed": False}, "Handoff stopped before submission.", command="send")
        return 130
    plain.to, plain.host, plain.codex_home = metadata["to"], metadata["host"], metadata["codexHome"]
    if not plain.host:
        # A verified normalizer may identify a self URI. Reuse the original
        # budget and already constructed envelope; never reset a new 30 s.
        plain._handoff_fixed_total = total
        plain._handoff_wrapped_body = metadata["body"]
        plain._handoff_routing_metadata = handoff_routing_metadata(metadata.get("routing", {}))
        plain.message_option, plain.message, plain.message_file, plain.b64 = text, None, None, None
        return cmd_handoff_send(plain)
    adapter = AGENTS.for_target(plain.to)
    if adapter.name not in ("claude", "codex"):
        raise handoff_error("handoff_route_unsupported")
    wrapped = metadata["body"]
    routing = handoff_routing_metadata(metadata.get("routing", {}))
    check_message(wrapped, remote=True)
    expected_chars = len(peer_delivery_message(wrapped, adapter.name, None))
    transport = SshTransport(plain.host[0], plain, metadata["tailnet"])
    context = {"schemaVersion": 1, "phase": "probe", "requestId": str(uuid.uuid4()),
               "agent": adapter.name, "target": codex_thread(plain.to) if adapter.name == "codex" else plain.to,
               "home": plain.codex_home if adapter.name == "codex" else None,
               "generation": plain.target_generation if adapter.name == "claude" else None,
               "nativeContext": None, "anchor": None, "remainingCutoffMs": None, "remainingTotalMs": None}
    probe_argv = handoff_remote_argv(plain, context, wrapped, cutoff, total)
    try:
        response = transport.execute(probe_argv, handoff_budget=(cutoff, total), handoff_context=context)
    except CcPeerError as exc:
        if exc.details.get("interrupted"):
            emit(args.json, {"ok": False, "reason": "sender_preflight_stopped", "retryAllowed": False}, "Handoff stopped before submission.", command="send")
            return 130
        raise handoff_error("remote_preflight_unavailable") from exc
    proof = response["handoffNative"]
    native = proof["native"]
    if not native["ok"] or native["chars"] != expected_chars:
        raise handoff_error("remote_preflight_unavailable")
    binding = {"agent": adapter.name, "destination": plain.host,
               "target": str(native["target"]["pid"]) if adapter.name == "claude" else native["target"]["id"].lower(),
               "home": native.get("codexHome"), "payloadDigest": digest}
    context = {**context, "phase": "effect", "target": binding["target"], "home": binding["home"],
               "generation": proof["generation"], "nativeContext": proof["nativeContext"], "anchor": proof["anchor"]}
    now = handoff_now()  # ONE original sender sample, both durations floored.
    context["remainingCutoffMs"] = int(max(0, cutoff - now) * 1000)
    context["remainingTotalMs"] = int(max(0, total - now) * 1000)
    argv = handoff_remote_argv(plain, context, wrapped)
    epoch, prepared = ledger.prepare(binding, context["generation"], args.correlation_id, cutoff,
                                     native_context=context["nativeContext"])
    correlation = prepared["id"]
    if args.dry_run:
        native = {key: value for key, value in native.items() if key != "targetGeneration"}
        native.update(handoff=handoff_public(epoch, prepared))
        emit(args.json, native, "Handoff validated; nothing submitted.", command="send")
        return 0
    with ledger.transaction(cutoff) as state:
        record = state["records"][correlation]
        if record["phase"] != "prepared":
            raise handoff_error("handoff_already_attempted")
        if handoff_now() >= cutoff:
            raise handoff_error("deadline_before_effect")
        record.update(phase="attempted", submission="unknown", observe=args.observe_delivery, ackRequested=args.request_ack)
    interrupted, extra, response = False, {}, None
    try:
        try:
            response = transport.execute(argv, handoff_budget=(cutoff, total), handoff_context=context)
        except CcPeerError as exc:
            # #183 may lack connection-key evidence AFTER independently valid
            # native submission. Retain only an already strictly validated
            # private proof, not arbitrary error fields or raw diagnostics.
            if type(exc.details.get("handoffNative")) is not dict:
                raise
            response = dict(exc.details)
            extra = {"reason": "ssh_identity_evidence_unavailable", "retryAllowed": False}
        native = handoff_remote_evidence(response, context, expected_chars, prepared)
        try:
            extra.update(handoff_ssh_metadata(response))
        except (CcPeerError, ValueError, KeyError, TypeError, UnicodeError):
            extra.update(reason="ssh_metadata_unavailable", retryAllowed=False)
        if native["ok"]:
            submission = "submitted"
        else:
            submission = "refused" if native["reason"] == "native_submission_refused" else "unknown"
    except CcPeerError as exc:
        interrupted = bool(exc.details.get("interrupted"))
        submission = "refused" if exc.details.get("spawned") is False or exc.details.get("status") == "refused" else "unknown"
        native = {"ok": False, "reason": "native_submission_refused" if submission == "refused" else "native_outcome_unknown", "retryAllowed": False}
    except (KeyError, ValueError, TypeError, UnicodeError):
        submission = "unknown"
        native = {"ok": False, "reason": "native_outcome_unknown", "retryAllowed": False}
    except KeyboardInterrupt:
        interrupted, submission = True, "unknown"
        retained = None
        if response is not None:
            try:
                candidate = handoff_remote_evidence(response, context, expected_chars, prepared)
                if candidate["ok"]:
                    retained = candidate
            except (CcPeerError, KeyError, ValueError, TypeError, UnicodeError, KeyboardInterrupt):
                pass
        if retained is not None:
            native, submission = retained, "submitted"
        else:
            native = {"ok": False, "reason": "native_outcome_unknown", "retryAllowed": False}
    code = 0 if submission == "submitted" else 130 if interrupted else 1
    try:
        with ledger.transaction(total) as state:
            record = state["records"][correlation]
            record.update(phase="terminal", submission=submission, native=native)
        epoch, record = ledger.record(correlation, total)
    except (CcPeerError, OSError, ValueError, KeyError, TypeError):
        result = {**native, **extra, **routing, "ok": code == 0, "reason": "handoff_history_unavailable", "retryAllowed": False}
    else:
        result = {**native, **extra, **routing, "ok": code == 0, "handoff": handoff_public(epoch, record)}
    # No private context/clock/source/capability/diagnostic output is reflected.
    emit(args.json, result, "SSH handoff submission is not consumption; do not resend.", command="send", host=plain.host[0])
    return code


def handoff_private_ms(value):
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]{0,4}", value, flags=re.ASCII) is None or int(value) > 60000:
        raise argparse.ArgumentTypeError("expected an ASCII integer 1..60000")
    return int(value)


def handoff_remote_decode(value):
    try:
        if type(value) is not str or len(value) > 12000:
            raise ValueError()
        raw = base64.b64decode(value, validate=True)
        context = handoff_json(raw, 8192)
        ssh_handoff_request((0, 0), context, require_context=True)
        return context
    except (CcPeerError, ValueError, UnicodeError, TypeError) as exc:
        raise handoff_error("invalid_remote_native_request") from exc


def handoff_remote_request_semantics(context):
    """Agent/effect semantics before sender config or receiver native calls."""
    if context["phase"] == "probe" and context["nativeContext"] is not None:
        raise handoff_error("invalid_remote_native_request")
    if context["agent"] == "claude":
        if context["home"] is not None or context["nativeContext"] is not None:
            raise handoff_error("invalid_remote_native_request")
        if context["generation"] is not None:
            validate_target_generation(context["generation"])
        if context["phase"] == "effect" and (context["generation"] is None or not context["target"].isdigit() or int(context["target"]) <= 1):
            raise handoff_error("invalid_remote_native_request")
    elif context["generation"] is not None:
        raise handoff_error("invalid_remote_native_request")
    else:
        codex_thread(context["target"])
        if context["phase"] == "effect":
            value = context["nativeContext"]
            if type(value) is not dict or value.get("root") != context["home"] or not Path(value["root"]).is_absolute():
                raise handoff_error("invalid_remote_native_request")
            handoff_codex_resolution(value["resolution"], value["root"])
    if context["phase"] == "effect" and context["remainingTotalMs"] - context["remainingCutoffMs"] != 5000:
        raise handoff_error("invalid_remote_native_request")


def handoff_validate_remote_argv(argv, context):
    """Bind the actual command to the private handler BEFORE an SSH child.

    Hidden flags are not authentication or frame authority. The handler still
    quotes every body line and validates its original native target itself.
    """
    try:
        handoff_remote_request_semantics(context)
    except (CcPeerError, KeyError, ValueError, TypeError, UnicodeError) as exc:
        raise handoff_error("invalid_remote_native_request") from exc
    flags = {"--no-update-notice", "--no-from", "--no-reply-to", "--allow-inactive-codex-home"}
    values = {"--_handoff-native-context", "--to", "--b64", "--codex-home", "--codex-bin",
              "--_handoff-native-cutoff-ms", "--_handoff-native-total-ms"}
    if type(argv) is not list or not argv or argv[0] != "send":
        raise handoff_error("invalid_remote_native_request")
    parsed, seen = {}, set()
    for arg in argv[1:]:
        if type(arg) is not str:
            raise handoff_error("invalid_remote_native_request")
        key, separator, value = arg.partition("=")
        if key in seen or (key not in flags and key not in values) or (key in values) != bool(separator):
            raise handoff_error("invalid_remote_native_request")
        seen.add(key)
        if key in values:
            parsed[key] = value
    if not {"--_handoff-native-context", "--to", "--b64", "--no-update-notice", "--no-from", "--no-reply-to"} <= seen:
        raise handoff_error("invalid_remote_native_request")
    if handoff_remote_decode(parsed["--_handoff-native-context"]) != context:
        raise handoff_error("invalid_remote_native_request")
    expected = "codex:" + codex_thread(context["target"]) if context["agent"] == "codex" else context["target"]
    if (parsed["--to"] != expected or AGENTS.for_target(parsed["--to"]).name != context["agent"]
            or parsed.get("--codex-home") != context["home"]):
        raise handoff_error("invalid_remote_native_request")
    if context["agent"] != "codex" and seen & {"--codex-home", "--codex-bin", "--allow-inactive-codex-home"}:
        raise handoff_error("invalid_remote_native_request")
    probe_fields = {"--_handoff-native-cutoff-ms", "--_handoff-native-total-ms"}
    if context["phase"] == "probe":
        if not probe_fields <= seen:
            raise handoff_error("invalid_remote_native_request")
        if handoff_private_ms(parsed["--_handoff-native-total-ms"]) - handoff_private_ms(parsed["--_handoff-native-cutoff-ms"]) != 5000:
            raise handoff_error("invalid_remote_native_request")
    elif seen & probe_fields:
        raise handoff_error("invalid_remote_native_request")
    if context["phase"] == "effect" and context["remainingTotalMs"] - context["remainingCutoffMs"] != 5000:
        raise handoff_error("invalid_remote_native_request")
    try:
        if len(parsed["--b64"]) > 4 * MAX_REMOTE_MESSAGE_CHARS:
            raise ValueError()
        text = base64.b64decode(parsed["--b64"], validate=True).decode("utf-8", errors="strict")
    except (ValueError, UnicodeError) as exc:
        raise handoff_error("invalid_remote_native_request") from exc
    check_message(text, remote=True)
    check_message(peer_delivery_message(text, context["agent"], None), remote=True)
    if context["agent"] == "codex":
        check_codex_message(peer_delivery_message(text, "codex", None))


def handoff_remote_anchor():
    boot = handoff_boot_clock()
    if boot is None:
        raise handoff_error("remote_clock_unsupported")
    value = handoff_now_ns() // 1000000
    if not 0 <= value <= 9007199254740991:
        raise handoff_error("remote_clock_unsupported")
    return {"boot": boot, "monotonicMs": value}


def handoff_remote_deadlines(context):
    """An OLD remote anchor plus sender remaining time never renews a budget.

    The sender computes remaining time only after validating the probe reply.
    Millisecond flooring debits rather than adds time. No cross-host monotonic
    origins or UTC clocks are compared, and SSH shutdown is not cancellation of
    a remotely started native operation.
    """
    now = handoff_remote_anchor()
    anchor = context["anchor"]
    if anchor is None or anchor["boot"] != now["boot"] or anchor["monotonicMs"] > now["monotonicMs"]:
        raise handoff_error("remote_clock_unsupported")
    cutoff_ms = anchor["monotonicMs"] + context["remainingCutoffMs"]
    total_ms = anchor["monotonicMs"] + context["remainingTotalMs"]
    if total_ms > 9007199254740991 or now["monotonicMs"] >= cutoff_ms:
        raise handoff_error("deadline_before_effect")
    return cutoff_ms / 1000, total_ms / 1000


def handoff_remote_context_native(context, native, native_context, generation):
    """Request-aware native profile check, with no receipt/ACK promotion."""
    if context["agent"] == "codex":
        if generation is not None or type(native_context) is not dict or set(native_context) != {"root", "resolution"}:
            raise handoff_error("invalid_remote_native_profile")
        home = native_context["root"]
        handoff_identifier(home, 4096)
        if not Path(home).is_absolute():
            raise handoff_error("invalid_remote_native_profile")
        handoff_codex_resolution(native_context["resolution"], home)
        if context["phase"] == "probe" and context["home"] is not None and native_context["resolution"]["status"] != "explicit":
            raise handoff_error("invalid_remote_native_profile")
        if len(HandoffLedger.encode(native_context)) > 4096:
            raise handoff_error("invalid_remote_native_profile")
        target = codex_thread(context["target"])
        if context["phase"] == "effect" and (home != context["home"] or native_context != context["nativeContext"]):
            raise handoff_error("invalid_remote_native_profile")
    else:
        if native_context is not None or generation is None:
            raise handoff_error("invalid_remote_native_profile")
        validate_target_generation(generation)
        if type(native.get("target")) is not dict or type(native["target"].get("pid")) is not int:
            raise handoff_error("invalid_remote_native_profile")
        target, home = str(native["target"]["pid"]), None
        requested = context["target"]
        if (requested.isdigit() and int(requested) != int(target) or
                not requested.isdigit() and (native["target"].get("name") or "").casefold() != requested.casefold()):
            raise handoff_error("invalid_remote_native_profile")
        if context["generation"] is not None and generation != context["generation"]:
            raise handoff_error("invalid_remote_native_profile")
    reference = {"binding": {"agent": context["agent"], "target": target, "home": home, "destination": ["local"]},
                 "generation": generation, "nativeContext": native_context}
    if context["phase"] == "probe":
        handoff_validate_dry_run(native, reference)
    else:
        handoff_validate_native(native, reference)


def handoff_validate_remote_response(result, context):
    """Validate the sole private response before adopting any native facts.

    The backend has already applied strict one-object UTF-8/duplicate-key
    framing. This closes native/operation context; merely returning a handoff
    field, turn state or an ACK never creates authority.
    """
    if (type(result) is not dict or set(result) != {"schemaVersion", "ok", "host", "command", "handoffNative"}
            or type(result["schemaVersion"]) is not int or result["schemaVersion"] != 1
            or type(result["ok"]) is not bool or result["command"] != "send"):
        raise handoff_error("invalid_remote_native_profile")
    handoff_identifier(result["host"], 1024)
    proof = result["handoffNative"]
    keys = {"schemaVersion", "phase", "requestId", "generation", "nativeContext", "anchor", "native", "homeSelection"}
    if (type(proof) is not dict or set(proof) != keys or type(proof["schemaVersion"]) is not int
            or proof["schemaVersion"] != 1 or proof["phase"] != context["phase"]
            or proof["requestId"] != context["requestId"] or len(HandoffLedger.encode(proof)) > 16384):
        raise handoff_error("invalid_remote_native_profile")
    anchor = proof["anchor"]
    if (type(anchor) is not dict or set(anchor) != {"boot", "monotonicMs"}
            or type(anchor["monotonicMs"]) is not int or not 0 <= anchor["monotonicMs"] <= 9007199254740991):
        raise handoff_error("invalid_remote_native_profile")
    handoff_identifier(anchor["boot"], 128)
    mapping = proof["homeSelection"]
    if type(mapping) is not dict or set(mapping) != {"requested", "canonical"} or mapping["requested"] != context["home"]:
        raise handoff_error("invalid_remote_native_profile")
    expected_home = proof["nativeContext"].get("root") if type(proof["nativeContext"]) is dict else None
    if mapping["canonical"] != expected_home:
        raise handoff_error("invalid_remote_native_profile")
    if context["agent"] == "claude" and mapping != {"requested": None, "canonical": None}:
        raise handoff_error("invalid_remote_native_profile")
    if context["phase"] == "effect" and (anchor != context["anchor"] or proof["generation"] != context["generation"]):
        raise handoff_error("invalid_remote_native_profile")
    native = proof["native"]
    if type(native) is not dict or native.get("ok") is not result["ok"]:
        raise handoff_error("invalid_remote_native_profile")
    if native["ok"] is True:
        handoff_remote_context_native(context, native, proof["nativeContext"], proof["generation"])
    elif (set(native) != {"ok", "reason", "retryAllowed"} or native["retryAllowed"] is not False
          or native["reason"] not in ("native_submission_refused", "native_outcome_unknown")):
        raise handoff_error("invalid_remote_native_profile")
    else:
        # Even a refusal has a closed private envelope. It supplies no positive
        # native facts, and arbitrary values must not escape via diagnostics.
        if context["agent"] == "claude":
            if proof["nativeContext"] is not None:
                raise handoff_error("invalid_remote_native_profile")
            if proof["generation"] is not None:
                validate_target_generation(proof["generation"])
        elif proof["generation"] is not None:
            raise handoff_error("invalid_remote_native_profile")
        elif proof["nativeContext"] is not None:
            value = proof["nativeContext"]
            if type(value) is not dict or set(value) != {"root", "resolution"}:
                raise handoff_error("invalid_remote_native_profile")
            handoff_identifier(value["root"], 4096)
            handoff_codex_resolution(value["resolution"], value["root"])
            if context["phase"] == "probe" and context["home"] is not None and value["resolution"]["status"] != "explicit":
                raise handoff_error("invalid_remote_native_profile")
        if context["phase"] == "effect" and proof["nativeContext"] != context["nativeContext"]:
            raise handoff_error("invalid_remote_native_profile")
    # Preserve the validated private proof so identity-wrapper exceptions can
    # retain known native evidence; the public sender strips it before output.
    return {"schemaVersion": 1, "command": "send", "host": result["host"], **native,
            "handoffNative": proof}


def cmd_handoff_remote_native(args):
    """One private native operation; NO remote ledger/collector/receipt route."""
    context = handoff_remote_decode(args._handoff_native_context)
    if (IS_WINDOWS or args.host or getattr(args, "device", None) or getattr(args, "wake", False)
            or handoff_requested(args) or args.b64 is None or args.message is not None
            or args.message_option is not None or args.message_file is not None
            or not args.no_from or not args.no_reply_to or args.reply_to is not None
            or args.target_generation is not None or args.dry_run or not args.no_update_notice):
        raise NoTargetError("Invalid private native operation")
    argv = ["send", "--_handoff-native-context=" + args._handoff_native_context,
            "--to=" + args.to, "--b64=" + args.b64, "--no-update-notice", "--no-from", "--no-reply-to"]
    for field, flag in (("codex_home", "--codex-home"), ("codex_bin", "--codex-bin"),
                        ("_handoff_native_cutoff_ms", "--_handoff-native-cutoff-ms"),
                        ("_handoff_native_total_ms", "--_handoff-native-total-ms")):
        value = getattr(args, field, None)
        if value is not None:
            argv.append(flag + "=" + str(value))
    if args.allow_inactive_codex_home:
        argv.append("--allow-inactive-codex-home")
    handoff_validate_remote_argv(argv, context)
    anchor = context["anchor"]
    generation, native_context = context["generation"], context["nativeContext"]
    mapping = {"requested": context["home"], "canonical": native_context["root"] if native_context else None}
    effect_started = False
    code = 1
    native = {"ok": False, "reason": "native_submission_refused", "retryAllowed": False}
    try:
        if context["phase"] == "probe":
            anchor = handoff_remote_anchor()
            started = handoff_now()
            cutoff = started + args._handoff_native_cutoff_ms / 1000
            total = started + args._handoff_native_total_ms / 1000
        else:
            cutoff, total = handoff_remote_deadlines(context)
        text = read_message(args)
        framed = peer_delivery_message(text, context["agent"], None)
        check_message(framed, remote=False)
        if context["agent"] == "claude":
            if context["phase"] == "effect" and generation is None:
                raise handoff_error("remote_generation_unsupported")
            session = resolve_target(discover(include_unreachable=True), context["target"])
            actual = claude_generation(session)
            if actual is None or generation is not None and actual != generation:
                raise handoff_error("remote_generation_unsupported")
            generation = actual
            require_claude_generation(session, generation)
            if handoff_now() >= cutoff:
                raise handoff_error("deadline_before_effect")
            if context["phase"] == "probe":
                native = {"ok": True, "target": {"pid": session["pid"], "name": session["name"]},
                          "chars": len(framed), "dryRun": True, "targetGeneration": generation}
            else:
                # Translate only remaining duration; sampling order is native
                # first/shared second, so adapter time never renews the budget.
                native_now, shared_now = time.monotonic(), handoff_now()
                effect_started = True
                post_to_socket(session["socket"], framed, pid=session["pid"], generation_session=session,
                    expected_generation=generation, effect_deadline=native_now + cutoff - shared_now,
                    total_deadline=native_now + total - shared_now)
                native = {"ok": True, "target": {"pid": session["pid"], "name": session["name"]},
                          "chars": len(framed), "dryRun": False}
        else:
            check_codex_message(framed)
            binding, _, _ = handoff_binding(args, text)
            # This is the trusted handler's filesystem normalization, not an
            # independently verified sender inode/incarnation/storage proof.
            if args.codex_home is not None and str(Path(args.codex_home).expanduser().resolve()) != binding["home"]:
                raise handoff_error("remote_native_context_changed")
            mapping["canonical"] = binding["home"]
            if context["phase"] == "effect":
                if (binding["home"] != context["home"] or type(native_context) is not dict
                        or native_context.get("root") != context["home"]):
                    raise handoff_error("remote_native_context_changed")
                root = Path(context["home"])
                handoff_codex_resolution(native_context["resolution"], str(root))
                revalidate_codex_home(root, binding["target"], native_context["resolution"])
                args._handoff_codex_selection = (root, native_context["resolution"])
            else:
                native_context = handoff_native_context(args)
            selected = handoff_codex_context(args, binding, cutoff, total)
            if context["phase"] == "probe":
                native = {"ok": True, "target": {"agent": "codex", "id": binding["target"]},
                          "chars": len(framed), "dryRun": True, "codexHome": binding["home"],
                          "submitted": False, "consumptionConfirmed": False, "status": "validated",
                          "codexHomeResolution": native_context["resolution"]}
            else:
                effect_started = True
                native = handoff_codex_submit(args, framed, binding, selected, cutoff, total)
        handoff_remote_context_native(context, native, native_context, generation)
        code = 0
    except KeyboardInterrupt:
        # This mode has no pending explicit wait. A fully returned, strictly
        # revalidated native submission already satisfies its submission goal;
        # interruption during pure final validation must not erase that fact.
        retained = False
        if effect_started and native.get("ok") is True:
            try:
                handoff_remote_context_native(context, native, native_context, generation)
                retained = True
            except (CcPeerError, KeyError, ValueError, TypeError, UnicodeError, KeyboardInterrupt):
                pass
        if retained:
            code = 0
        else:
            native = {"ok": False, "reason": "native_outcome_unknown" if effect_started else "native_submission_refused", "retryAllowed": False}
            code = 130
    except (CcPeerError, OSError, UnicodeError, KeyError, ValueError, TypeError) as exc:
        refused = not effect_started or isinstance(exc, CcPeerError) and exc.details.get("status") == "refused"
        native = {"ok": False, "reason": "native_submission_refused" if refused else "native_outcome_unknown", "retryAllowed": False}
    proof = {"schemaVersion": 1, "phase": context["phase"], "requestId": context["requestId"],
             "generation": generation, "nativeContext": native_context, "anchor": anchor, "native": native,
             "homeSelection": mapping}
    emit(args.json, {"ok": native["ok"], "handoffNative": proof}, "Private native operation completed.", command="send")
    return code
