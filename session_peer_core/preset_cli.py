class PresetSingleUseAction(argparse.Action):
    """A route selector never silently replaces an earlier explicit value."""
    def __call__(self, parser, namespace, values, option_string=None):
        seen = getattr(namespace, "_preset_single_use", [])
        if self.dest in seen:
            parser.error(self.option_strings[0] + " may be specified only once")
        namespace._preset_single_use = [*seen, self.dest]
        setattr(namespace, self.dest, values)


def preset_explicit_options(parser):
    """Collect only actual argparse actions, never scan message values."""
    explicit = set(getattr(parser, "_explicit_option_strings", ()))
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                explicit.update(preset_explicit_options(subparser))
    return explicit


def preset_operation_failed(args):
    """Unexpected private-store failures never reflect diagnostics or paths."""
    message = "Route preset operation failed"
    if args.json:
        print(json.dumps(json_result(args.command, {
            "error": message, "reason": "preset_operation_failed",
        }, ok=False), ensure_ascii=False))
    else:
        print("session-peer: " + message, file=sys.stderr)
    return EXIT_ERROR


def prepare_preset_route(parser, args, raw_argv):
    name = getattr(args, "preset", None)
    revision = getattr(args, "preset_revision", None)
    if revision is not None and name is None:
        parser.error("--preset-revision requires --preset")
    if name is None:
        return
    conflicting = (
        "--host", "--codex-home", "--agent", "--ssh-opt", "--codex-bin",
        "--device", "--device-state", "--device-route", "--relay-admission-file",
        "--relay-login", "--antigravity-home", "--antigravity-generation",
        "--request-id", "--wake", "--wake-max-depth", "--wake-timeout",
        "--allow-inactive-codex-home", "--correlation-id", "--request-ack",
        "--observe-delivery", "--wait-for", "--wait-timeout", "--b64",
        "--_handoff-native-context", "--_handoff-native-cutoff-ms",
        "--_handoff-native-total-ms", "--_wake-depth", "--_wake-origin", "--_wake-limit",
    )
    for flag in conflicting:
        if flag in args._preset_explicit_options:
            parser.error("--preset conflicts with " + flag)
    if str(getattr(args, "to", "")).lower().startswith("session-peer:"):
        parser.error("--preset conflicts with a Reply-To URI")
    if args.command == "send" and AGENTS.for_target(args.to).name not in ("claude", "codex"):
        parser.error("--preset supports only Claude Code and Codex targets")
    if args.command == "send" and not args.dry_run and revision is None:
        parser.error("actual --preset sends require --preset-revision from preset show or text dry-run stderr")
    if IS_WINDOWS:
        raise CcPeerError("Route presets are not supported on Windows", {"reason": "preset_platform_unsupported"})
    route, current = preset_lookup(name)
    if revision is not None and revision != current:
        raise CcPeerError("Route preset changed; review a new dry run", {"reason": "preset_revision_mismatch"})
    if args.command == "send":
        if AGENTS.for_target(args.to).name != route["agent"]:
            parser.error("--to agent conflicts with the selected preset")
    else:
        args.agent = route["agent"]
    args.host = [route["host"]] if route["transport"] == "ssh" else []
    args.codex_home = route.get("codexHome")
    if not args.json:
        print(render_preset_route(name, route, current), file=sys.stderr)


def render_preset_route(name, route, revision):
    name, route, revision = human_text(name), human_text(route), human_text(revision)
    where = route.get("host", "this machine")
    home = " / home " + route["codexHome"] if "codexHome" in route else ""
    return f"Preset {name}: {route['transport']} / {where} / {route['agent']}{home}\nRevision: {revision}\nRoute configuration only; receiver, host identity and delivery are checked separately."


def cmd_preset(args):
    if IS_WINDOWS:
        raise CcPeerError("Route presets are not supported on Windows", {"reason": "preset_platform_unsupported"})
    action = args.preset_action
    if action == "list":
        routes = preset_read()
        items = [{"name": name, "revision": preset_revision(name, route), "route": route}
                 for name, route in sorted(routes.items())]
        payload = {"presets": items}
        human = "\n\n".join(render_preset_route(item["name"], item["route"], item["revision"]) for item in items) or "No route presets."
    elif action == "show":
        route, revision = preset_lookup(args.name)
        payload = {"name": args.name, "revision": revision, "route": route}
        human = render_preset_route(args.name, route, revision)
    else:
        route = None
        if action in ("add", "replace"):
            route = {"transport": "ssh" if args.host is not None else "local", "agent": args.agent}
            if args.host is not None:
                route["host"] = args.host
            if args.codex_home is not None:
                route["codexHome"] = args.codex_home
        payload = preset_mutate(action, args.name, route, getattr(args, "expect_revision", None))
        human = ("Removed route preset " + human_text(args.name) if action == "remove"
                 else render_preset_route(payload["name"], payload["route"], payload["revision"]))
    emit(args.json, payload, human, command="preset")
    return 0
