"""Metadata-only address selection; observation hashes are never native epochs."""


def address_refused(reason):
    return CcPeerError("Address selection refused: " + reason,
                       {"reason": reason, "status": "refused", "submitted": False,
                        "retryAllowed": False})


def address_writer_revision_argument(value):
    if not isinstance(value, str) or re.fullmatch(r"aw1:[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("expected an address writer observation revision")
    return value


def address_codex_writer_revision(root, thread_id, resolution):
    """Hash existing bounded live-writer observations, without new probes."""
    if not isinstance(resolution, dict) or resolution.get("selected") != str(root):
        raise address_refused("address_writer_unavailable")
    candidates = resolution.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 256:
        raise address_refused("address_writer_unavailable")
    selected = [row for row in candidates if isinstance(row, dict) and row.get("codexHome") == str(root)]
    if len(selected) != 1:
        raise address_refused("address_writer_unavailable")
    row = selected[0]
    pid, birth = row.get("ownerPid"), row.get("ownerStartTime")
    valid_birth = (type(birth) is int and birth > 0) or (
        isinstance(birth, str) and 0 < len(birth) <= 128
        and all(32 <= ord(c) < 127 for c in birth))
    if (row.get("activity") != "live_writer" or row.get("writerLock") != "held"
            or row.get("ownerStable") is not True or type(pid) is not int or pid <= 1
            or not valid_birth):
        raise address_refused("address_writer_unavailable")
    raw = json.dumps([str(root), thread_id, pid, birth], separators=(",", ":"), ensure_ascii=True)
    return "aw1:" + hashlib.sha256(raw.encode("ascii")).hexdigest()


def require_address_writer(args, root, thread_id, resolution):
    expected = getattr(args, "_address_expected_writer", None)
    if expected is None:
        return
    if not isinstance(expected, str) or re.fullmatch(r"aw1:[0-9a-f]{64}", expected) is None:
        raise address_refused("address_invalid_writer_revision")
    if address_codex_writer_revision(root, thread_id, resolution) != expected:
        raise address_refused("address_writer_changed")


def address_inspect_selection(args):
    address_platform()
    agent, targets = args.agent, args.to
    if (agent not in ("claude", "codex") or not isinstance(targets, list)
            or not 1 <= len(targets) <= 16
            or any(not isinstance(t, str) or not t or len(t) > 256 for t in targets)
            or len(set(targets)) != len(targets)):
        raise address_refused("address_invalid_selection")
    if agent == "codex" and not getattr(args, "codex_home", None):
        raise address_refused("address_explicit_home_required")
    if any(AGENTS.for_target(target).name != agent for target in targets):
        raise address_refused("address_agent_conflict")
    rows = discover(include_unreachable=True) if agent == "claude" else None
    results = []
    for target in targets:
        try:
            if agent == "claude":
                selector = target.removeprefix("claude:")
                if re.fullmatch(r"[0-9]+", selector) is None and getattr(rows, "errors", []):
                    raise address_refused("address_selection_unavailable")
                session = resolve_target(rows, selector)
                generation = claude_generation(session)
                if generation is None:
                    raise address_refused("address_generation_unavailable")
                recipient = {"agent": agent, "target": "claude:" + str(session["pid"]), "home": None}
                selection = {"generationStatus": "available", "targetGeneration": generation,
                             "writerRevision": None, "observationRevision": None}
            else:
                thread = codex_thread(target)
                root, resolution = resolve_codex_home(args, codex_home(args), thread)
                recipient = {"agent": agent, "target": "codex:" + thread, "home": str(root)}
                selection = {"generationStatus": "unsupported", "targetGeneration": None,
                             "writerRevision": address_codex_writer_revision(root, thread, resolution),
                             "observationRevision": None}
            results.append({"requestedTarget": target, "ok": True, "recipient": recipient,
                            "selection": selection})
        except (CcPeerError, OSError):
            # Do not reflect arbitrary native diagnostics or another recipient.
            results.append({"requestedTarget": target, "ok": False,
                            "reason": "address_selection_unavailable"})
    return {"selectionSchemaVersion": 1, "selections": results,
            "homeSelector": getattr(args, "codex_home", None) if agent == "codex" else None,
            "ok": all(row["ok"] for row in results)}


def cmd_address_inspect(args):
    payload = address_inspect_selection(args)
    emit(True, payload, "", command="address")
    return 0 if payload["ok"] else EXIT_ERROR


def _address_validate_probe(value, route, targets):
    if (not isinstance(value, dict) or type(value.get("selectionSchemaVersion")) is not int
            or value["selectionSchemaVersion"] != 1 or type(value.get("ok")) is not bool
            or not isinstance(value.get("selections"), list)
            or len(value["selections"]) != len(targets)
            or "homeSelector" not in value or value["homeSelector"] != route.get("codexHome")):
        raise address_refused("address_invalid_inspection")
    for row, requested in zip(value["selections"], targets):
        if (not isinstance(row, dict) or row.get("requestedTarget") != requested
                or type(row.get("ok")) is not bool):
            raise address_refused("address_invalid_inspection")
        if not row["ok"]:
            if set(row) != {"requestedTarget", "ok", "reason"} or row["reason"] != "address_selection_unavailable":
                raise address_refused("address_invalid_inspection")
            continue
        if set(row) != {"requestedTarget", "ok", "recipient", "selection"}:
            raise address_refused("address_invalid_inspection")
        recipient, selection = row["recipient"], row["selection"]
        if (not isinstance(recipient, dict) or set(recipient) != {"agent", "target", "home"}
                or recipient["agent"] != route["agent"] or not isinstance(selection, dict)
                or set(selection) != {"generationStatus", "targetGeneration", "writerRevision", "observationRevision"}
                or selection["observationRevision"] is not None):
            raise address_refused("address_invalid_inspection")
        target = recipient["target"]
        if route["agent"] == "claude":
            valid = (isinstance(target, str) and re.fullmatch(r"claude:[1-9][0-9]{0,9}", target)
                     and int(target.partition(":")[2]) > 1 and recipient["home"] is None
                     and selection["generationStatus"] == "available"
                     and isinstance(selection["targetGeneration"], str)
                     and re.fullmatch(r"tg1:[0-9a-f]{64}", selection["targetGeneration"])
                     and selection["writerRevision"] is None)
            literal_pid = requested.removeprefix("claude:")
            if re.fullmatch(r"[0-9]+", literal_pid):
                valid = valid and target == "claude:" + str(int(literal_pid))
        else:
            home = recipient["home"]
            valid_home = (isinstance(home, str) and 0 < len(home) <= 4096
                and PurePosixPath(home).is_absolute() and not home.startswith("//")
                and "\\" not in home and ".." not in PurePosixPath(home).parts
                and str(PurePosixPath(home)) == home
                and all(not (ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF) for c in home))
            valid = (isinstance(target, str) and target == "codex:" + codex_thread(target)
                     and target == "codex:" + codex_thread(requested) and valid_home
                     and selection["generationStatus"] == "unsupported"
                     and selection["targetGeneration"] is None
                     and isinstance(selection["writerRevision"], str)
                     and re.fullmatch(r"aw1:[0-9a-f]{64}", selection["writerRevision"]))
        if not valid:
            raise address_refused("address_invalid_inspection")
    if value["ok"] != all(row["ok"] for row in value["selections"]):
        raise address_refused("address_invalid_inspection")
    return value["selections"]


def address_probe_route(route, targets, expected_ssh_key=None):
    route = preset_validate_entry(route)
    address_platform()
    if (not isinstance(targets, list) or not 1 <= len(targets) <= 16
            or any(not isinstance(t, str) or not t or len(t) > 256 for t in targets)
            or len(set(targets)) != len(targets)):
        raise address_refused("address_invalid_selection")
    if any(AGENTS.for_target(target).name != route["agent"] for target in targets):
        raise address_refused("address_agent_conflict")
    options = argparse.Namespace(agent=route["agent"], to=targets, codex_home=route.get("codexHome"),
        allow_inactive_codex_home=False, wake=False, ssh_opt=[], ssh_identity=True,
        require_ssh_host_key=expected_ssh_key)
    fingerprint = None
    if route["transport"] == "local":
        if expected_ssh_key is not None:
            raise address_refused("address_invalid_ssh_identity")
        try:
            result = address_inspect_selection(options)
        except (CcPeerError, OSError):
            raise address_refused("address_selection_unavailable") from None
    else:
        argv = ["address", "_inspect", "--agent", route["agent"], "--json"]
        for target in targets:
            argv.append("--to=" + target)
        if "codexHome" in route:
            argv.extend(["--codex-home", route["codexHome"]])
        try:
            transport = SshTransport(route["host"], options, tailscale_status() or {})
            result = transport.execute(argv)
        except (CcPeerError, OSError):
            raise address_refused("address_selection_unavailable") from None
        proof = result.get("sshIdentity", {})
        fingerprint = proof.get("fingerprint")
        if (proof.get("status") != "verified" or not isinstance(fingerprint, str)
                or re.fullmatch(SSH_FINGERPRINT_PATTERN, fingerprint) is None
                or (expected_ssh_key is not None and fingerprint != expected_ssh_key)):
            raise address_refused("address_ssh_identity_unverified")
    return {"selections": _address_validate_probe(result, route, targets), "sshHostKey": fingerprint}
