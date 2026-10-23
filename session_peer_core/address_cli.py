"""Explicit address lifecycle and immutable per-invocation recipient selection."""


def _address_current_route(entry):
    try:
        route, revision = preset_lookup(entry["preset"])
    except CcPeerError as error:
        if error.details.get("reason") == "preset_not_found":
            raise address_refused("address_preset_changed") from None
        raise
    if route != entry["route"] or revision != entry["presetRevision"]:
        raise address_refused("address_preset_changed")
    return route, revision


def _address_selection(preset, revision, route, target, expected_key=None):
    probe = address_probe_route(route, [target], expected_key)
    row = probe["selections"][0]
    if not row["ok"]:
        raise address_refused("address_selection_unavailable")
    recipient, selection = dict(row["recipient"]), dict(row["selection"])
    selection["observationRevision"] = address_selection_revision(
        preset, revision, route, recipient, selection, probe["sshHostKey"])
    return recipient, selection, probe["sshHostKey"]


def _address_render(name, entry, revision):
    clean = human_text({"name": name, "entry": entry, "revision": revision})
    item, recipient = clean["entry"], clean["entry"]["recipient"]
    route = item["route"]
    where = route.get("host", "this machine")
    return (f"Address {clean['name']}: {item['label']}\n"
            f"{route['transport']} / {where} / {recipient['target']}"
            + (f" / home {recipient['home']}" if recipient["home"] else "")
            + f"\nRevision: {clean['revision']}\n"
            + f"Generation: {item['selection']['generationStatus']}; label is user-supplied, not authenticated identity.")


def _address_discover(args):
    names = args.address
    if (not isinstance(names, list) or not 1 <= len(names) <= 16
            or len(set(names)) != len(names)):
        raise address_refused("address_invalid_selection")
    groups, records = {}, []
    for name in names:
        try:
            entry, revision = address_lookup(name)
            route, _ = _address_current_route(entry)
            key = json.dumps([route, entry["sshHostKey"]], sort_keys=True, separators=(",", ":"))
            group = groups.setdefault(key, {"route": route, "key": entry["sshHostKey"], "targets": [], "records": []})
            target = entry["recipient"]["target"]
            if target not in group["targets"]:
                group["targets"].append(target)
            record = {"name": name, "label": entry["label"], "revision": revision,
                      "route": route, "recipient": entry["recipient"], "generationStatus": entry["selection"]["generationStatus"]}
            records.append(record)
            group["records"].append((record, entry))
        except (CcPeerError, OSError) as error:
            reason = error.details.get("reason") if isinstance(error, CcPeerError) else None
            records.append({"name": name, "status": "stale" if reason == "address_preset_changed" else "unverified",
                            "reason": reason if reason == "address_preset_changed" else "address_unavailable"})
    for group in groups.values():
        try:
            probe = address_probe_route(group["route"], group["targets"], group["key"])
            by_target = {row["requestedTarget"]: row for row in probe["selections"]}
            for record, entry in group["records"]:
                row = by_target[entry["recipient"]["target"]]
                if not row["ok"]:
                    record.update(status="unverified", reason="address_selection_unavailable")
                    continue
                current = address_selection_revision(entry["preset"], entry["presetRevision"],
                    entry["route"], row["recipient"], row["selection"], probe["sshHostKey"])
                record["status"] = "matched" if current == entry["selection"]["observationRevision"] else "stale"
                if record["status"] == "stale":
                    record["reason"] = "address_selection_changed"
        except (CcPeerError, OSError):
            for record, _ in group["records"]:
                record.update(status="unverified", reason="address_discovery_failed")
    payload = {"addresses": records, "ok": all(row["status"] == "matched" for row in records)}
    human = "\n\n".join(human_text(
        f"{row['name']} / {row.get('label', '')}: {row['status']}"
        + (" / " + json.dumps(row["route"], ensure_ascii=False, sort_keys=True) if "route" in row else "")
        + (" / " + row["recipient"]["target"] if "recipient" in row else "")) for row in records)
    emit(args.json, payload, human, command="address")
    return 0 if payload["ok"] else EXIT_ERROR


def cmd_address(args):
    address_platform()
    action = args.address_action
    if action in ("add", "show", "reselect", "remove"):
        _address_name(args.name)
    if action in ("add", "reselect") and re.fullmatch(r"as1:[0-9a-f]{64}", args.expect_selection) is None:
        raise address_refused("address_invalid_selection_revision")
    if action in ("reselect", "remove") and re.fullmatch(r"ab1:[0-9a-f]{64}", args.expect_revision) is None:
        raise address_refused("address_invalid_revision")
    if action == "add":
        args.label = address_validate_label(unicodedata.normalize("NFC", args.label if args.label is not None else args.name))
    if action == "discover":
        return _address_discover(args)
    if action == "list":
        entries = address_read()
        items = [{"name": name, "entry": entry, "revision": address_revision(name, entry)}
                 for name, entry in sorted(entries.items())]
        payload = {"addresses": items}
        human = "\n\n".join(_address_render(item["name"], item["entry"], item["revision"]) for item in items) or "No addresses."
    elif action == "show":
        entry, revision = address_lookup(args.name)
        payload = {"name": args.name, "entry": entry, "revision": revision}
        human = _address_render(args.name, entry, revision)
    elif action == "remove":
        payload = address_mutate("remove", args.name, None, args.expect_revision)
        human = "Removed address " + human_text(args.name)
    else:
        previous = None
        if action == "reselect":
            previous, previous_revision = address_lookup(args.name)
            if previous_revision != args.expect_revision:
                raise address_refused("address_revision_mismatch")
            preset = previous["preset"]
        else:
            preset = args.preset
        route, revision = preset_lookup(preset)
        recipient, selection, key = _address_selection(preset, revision, route, args.to)
        payload = {"preset": preset, "presetRevision": revision, "route": route,
                   "recipient": recipient, "selection": selection, "sshHostKey": key}
        if action == "resolve":
            human = human_text(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if args.expect_selection != selection["observationRevision"]:
                raise address_refused("address_selection_changed")
            # A preset edit during network discovery must not create a stale binding.
            current_route, current_revision = preset_lookup(preset)
            if current_route != route or current_revision != revision:
                raise address_refused("address_preset_changed")
            label = getattr(args, "label", None)
            if label is None:
                label = previous["label"] if previous else args.name
            payload["label"] = unicodedata.normalize("NFC", label)
            payload = address_mutate(action, args.name, payload, getattr(args, "expect_revision", None))
            human = _address_render(payload["name"], payload["entry"], payload["revision"])
    emit(args.json, payload, human, command="address")
    return 0


def prepare_address_route(parser, args, raw_argv):
    name = getattr(args, "address", None)
    revision = getattr(args, "address_revision", None)
    confirmation = getattr(args, "confirm_target", None)
    if name is None:
        if revision is not None or confirmation is not None:
            parser.error("--address-revision and --confirm-target require --address")
        return
    _address_name(name)
    if revision is not None and re.fullmatch(r"ab1:[0-9a-f]{64}", revision) is None:
        parser.error("--address-revision requires a complete address revision")
    conflicting = ("--preset", "--preset-revision", "--to", "--host", "--agent", "--codex-home",
        "--codex-bin", "--ssh-opt", "--ssh-config", "--trust-ssh-config", "--ssh-identity", "--require-ssh-host-key", "--device",
        "--device-state", "--device-route", "--relay-admission-file", "--relay-login",
        "--antigravity-home", "--antigravity-generation", "--target-generation", "--request-id",
        "--wake", "--wake-max-depth", "--wake-timeout", "--allow-inactive-codex-home", "--b64",
        "--correlation-id", "--request-ack", "--observe-delivery", "--wait-for", "--wait-timeout",
        "--_address-writer-revision", "--_handoff-native-context", "--_handoff-native-cutoff-ms",
        "--_handoff-native-total-ms", "--_wake-depth", "--_wake-origin", "--_wake-limit")
    explicit = preset_explicit_options(parser)
    for flag in conflicting:
        if flag in explicit:
            parser.error("--address conflicts with " + flag)
    if not args.dry_run and (revision is None or confirmation is None):
        parser.error("actual --address sends require --address-revision and --confirm-target")
    address_platform()
    entry, current = address_lookup(name)
    if revision is not None and revision != current:
        raise address_refused("address_revision_mismatch")
    if confirmation is not None and confirmation != entry["recipient"]["target"]:
        raise address_refused("address_confirmation_mismatch")
    route, preset_revision_value = _address_current_route(entry)
    recipient, selection, key = _address_selection(entry["preset"], preset_revision_value,
        route, entry["recipient"]["target"], entry["sshHostKey"])
    if (recipient != entry["recipient"] or selection != entry["selection"] or key != entry["sshHostKey"]):
        raise address_refused("address_selection_changed")
    # Recheck local records after discovery, then freeze this invocation's values.
    latest, latest_revision = address_lookup(name)
    _address_current_route(latest)
    if latest_revision != current or latest != entry:
        raise address_refused("address_revision_mismatch")
    args.to = recipient["target"].removeprefix("claude:") if recipient["agent"] == "claude" else recipient["target"]
    args.host = [route["host"]] if route["transport"] == "ssh" else []
    args.codex_home = recipient["home"]
    args.target_generation = selection["targetGeneration"]
    args._address_expected_writer = selection["writerRevision"]
    args.require_ssh_host_key = key
    args.ssh_identity = key is not None
    if not args.json:
        print(_address_render(name, entry, current), file=sys.stderr)
