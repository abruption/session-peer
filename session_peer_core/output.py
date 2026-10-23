# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def human_text(value):
    """Escape terminal controls in display-only values, retaining Unicode.

    Copy containers so rendering cannot alter JSON results or message bodies.
    Apply this before assembling lines (and measuring table widths): newlines
    in external fields are escaped, while renderer-owned newlines stay intact.
    Escaping is idempotent because printable backslashes are left unchanged.
    """
    if isinstance(value, str):
        return "".join(
            f"\\x{ord(char):02x}" if ord(char) < 0x20 or 0x7f <= ord(char) <= 0x9f else char
            for char in value
        )
    if isinstance(value, dict):
        return {key: human_text(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(human_text(item) for item in value)
    return value


def render_sessions(sessions: list[dict], where: str) -> str:
    sessions, where = human_text(sessions), human_text(where)
    if not sessions:
        return f"No reachable Claude Code sessions on {where}."

    rows = [("NAME", "PID", "STATUS", "CWD")]
    for s in sessions:
        name = s["name"] or "(unnamed)"
        if not s["reachable"]:
            name += " [no inbox]" if s["alive"] else " [stale record]"
        rows.append((name, str(s["pid"]), s["status"] or "-", s["cwd"] or "-"))

    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = [
        f"{r[0]:<{widths[0]}}  {r[1]:<{widths[1]}}  {r[2]:<{widths[2]}}  {r[3]}"
        for r in rows
    ]
    return f"Sessions on {where}:\n" + "\n".join(lines)


def delivery_explanation_has_submission(result: dict) -> bool:
    """Recognize reported submission evidence without changing native results."""
    return (result.get("submitted") is True or result.get("dryRun") is False
            or result.get("status") in ("queued", "posted", "submitted"))


def render_delivery_explanation(args: argparse.Namespace, result: dict, *,
                                host: str | None = None, failed: bool = False,
                                mode: str = "readiness") -> str:
    """Describe only existing dry-run facts; never inspect or execute a target.

    This display-only allowlist deliberately excludes message bodies, native
    errors, credentials, routing URIs and receipt authority. Missing remote
    facts stay unknown rather than being filled from the sender's environment.
    """
    facts = build_delivery_explanation(args, result, mode=mode, failed=failed)
    if mode != "readiness":
        lines = render_delivery_fact_lines(facts)
        if host:
            lines.insert(1, "Destination host: " + explanation_text(host))
        return "\n".join(lines)
    requested = str(getattr(args, "to", ""))
    unresolved_uri = requested.lower().startswith("session-peer:")
    if unresolved_uri:
        requested = "Reply-To URI (resolution unavailable)"
    agent = facts["agent"]
    if facts["paired"]:
        requested = facts["target"] or "paired target (not reported by receiver)"
    where = host or (("device:" + str(args.device)) if facts["paired"] else
                     (", ".join(getattr(args, "host", None) or []) or "this machine"))
    lines = ["Delivery preview",
             "Requested destination: " + explanation_text(requested) + " on " + explanation_text(where)]
    if facts["paired"]:
        lines.append("Selected paired route: " + (facts["selectedRoute"] + " (reported)" if facts["selectedRoute"] else "unknown (not reported)"))
    target = None if facts["paired"] else result.get("target")
    if isinstance(target, dict):
        if agent == "claude" and type(target.get("pid")) is int:
            resolved = "Claude PID " + str(target["pid"])
            if isinstance(target.get("name"), str):
                resolved += " (" + explanation_text(target["name"]) + ")"
            lines.append("Resolved target: " + resolved)
        elif agent == "codex" and isinstance(target.get("id"), str):
            lines.append("Resolved target: codex:" + explanation_text(target["id"]))
    if agent in ("codex", "antigravity"):
        home = facts["home"]
        lines.append(("Codex home: " if agent == "codex" else "Antigravity home: ")
                     + (explanation_text(home) if isinstance(home, str) else "unknown (not reported)"))
    started = getattr(args, "_delivery_explanation_started", True)
    unknown = result.get("status") == "unknown" or result.get("reason") in (
        "outcome_unknown", "ssh_identity_evidence_unavailable") or (
        "submitted" in result and result["submitted"] is None)
    unexpected = delivery_explanation_has_submission(result)
    dry_run_reported = result.get("dryRun") is True or result.get("status") in ("dry_run", "validated")
    if not started:
        lines.append("Destination checks: not run (command failed before destination checks)")
        lines.append("Validation: not confirmed")
    else:
        lines.append("Validation: " + ("unexpected submission evidence; dry-run not confirmed" if unexpected else
                                       "result unknown" if unknown else
                                       "not confirmed" if failed else
                                       "passed for this dry run" if dry_run_reported else
                                       "not confirmed (dry-run evidence not reported)"))
    if unexpected:
        for key, label in (("dryRun", "dry-run"), ("submitted", "submitted")):
            if type(result.get(key)) is bool:
                lines.append("Reported " + label + ": " + str(result[key]).lower())
        if result.get("status") in ("queued", "posted", "submitted", "unknown"):
            lines.append("Reported native status: " + result["status"])
    method = {"claude": "Claude Code inbox", "codex": "native Codex queue",
              "antigravity": "registered Antigravity bridge"}.get(agent)
    lines.append("Delivery method: " + (method + " (planned)" if method else "unknown (not resolved)"))
    if not getattr(args, "wake", False):
        wake = "not requested; eligibility not checked"
    else:
        fact = result.get("wake")
        wake = ("preflight passed for this dry run; no turn started"
                if not unknown and not unexpected and isinstance(fact, dict) and fact.get("status") == "validated" else
                "requested; preflight not confirmed")
    lines.extend(["Wake: " + wake,
                  ("Receipt ACK: unknown (receiver support not reported)" if facts["paired"]
                   and facts["capabilities"] is None else "Receipt ACK: unavailable for ordinary sends"),
                  "Consumption / completion: not observed",
                  "A later send repeats validation.",
                  "Do not automatically resend after an unknown outcome."])
    if failed or unexpected:
        lines.append("Next step: inspect the target and existing evidence before deciding what to do."
                     if unknown or unexpected else "Next step: resolve the validation failure before attempting a send.")
    lines.extend(render_delivery_fact_lines(facts))
    if facts["paired"] and agent is None:
        lines.append("Selected agent / home: unknown (receiver context not reported)")
    generation = getattr(args, "target_generation", None)
    if generation is not None:
        lines.append("Target generation: requested; existing validation result applies")
    else:
        lines.append("Target generation: not requested" if agent == "claude" and not facts["paired"]
                     else "Target generation: unsupported for this route")
    return "\n".join(lines)


def emit_delivery_explanation(args: argparse.Namespace, result: dict, *,
                              host: str | None = None, failed: bool = False,
                              stream=None, mode: str = "readiness") -> None:
    explanation = render_delivery_explanation(args, result, host=host, failed=failed, mode=mode)
    try:
        generated = int(time.time() * 1000)
        if 0 <= generated <= 9007199254740991:
            explanation += "\nExplanation generated at (UTC milliseconds): " + str(generated) + "; not a delivery observation."
    except Exception:
        pass
    print(explanation,
          file=stream or (sys.stderr if failed or delivery_explanation_has_submission(result) else sys.stdout))


JSON_RESPONSE_SCHEMA_VERSION = 1


def local_host() -> str:
    """Stable, network-independent identity for results produced locally."""
    return socket.gethostname()


def json_result(command: str, payload: dict | None = None, *,
                host: str | None = None, ok: bool | None = None) -> dict:
    """Build one command result with the common machine-readable envelope."""
    detail = dict(payload or {})
    payload_ok = detail.pop("ok", True)
    payload_host = detail.pop("host", None)
    for reserved in ("schemaVersion", "command"):
        detail.pop(reserved, None)
    return {
        "schemaVersion": JSON_RESPONSE_SCHEMA_VERSION,
        "ok": bool(payload_ok if ok is None else ok),
        "host": host or payload_host or local_host(),
        "command": command,
        **detail,
    }


def one_or_many(results: list[dict]) -> dict | list[dict]:
    """Keep one destination flat; use an array only for repeated --host."""
    return results[0] if len(results) == 1 else results


def with_client_update(payload: dict | list[dict]) -> dict | list[dict]:
    """Attach the invoking client's cached update fact to each result object."""
    if _CLIENT_UPDATE_NOTICE is None and not _SKILL_UPDATE_NOTICES:
        return payload
    notices = ({"clientUpdate": dict(_CLIENT_UPDATE_NOTICE)} if _CLIENT_UPDATE_NOTICE else {})
    if _SKILL_UPDATE_NOTICES:
        notices["skillUpdates"] = [dict(item) for item in _SKILL_UPDATE_NOTICES]
    if isinstance(payload, list):
        return [
            {**item, **notices}
            if isinstance(item, dict) else item
            for item in payload
        ]
    return {**payload, **notices}


def emit(as_json: bool, payload: dict, human: str, *, command: str,
         host: str | None = None, ok: bool | None = None) -> None:
    result = json_result(command, payload, host=host, ok=ok)
    print(json.dumps(with_client_update(result), ensure_ascii=False) if as_json else human)


def emit_json_results(results: list[dict]) -> None:
    print(json.dumps(with_client_update(one_or_many(results)), ensure_ascii=False))


def emit_human_update_notice() -> None:
    if _CLIENT_UPDATE_NOTICE is not None:
        notice = human_text(_CLIENT_UPDATE_NOTICE)
        print(
            f"Update available: {notice['current']} → "
            f"{notice['latest']}. "
            f"Run: {notice['command']}",
            file=sys.stderr,
        )
    for notice in human_text(_SKILL_UPDATE_NOTICES):
        command = notice.get("command") or "check the skill's installation manager"
        print(f"Skill update available ({notice['location']}): "
              f"{notice['current']} → {notice['latest']}. Run: {command}", file=sys.stderr)


def host_metadata(ssh_host: str, canonical_host: str) -> dict:
    metadata = {"host": canonical_host}
    if ssh_host != canonical_host:
        metadata["sshHost"] = ssh_host
    return metadata


def display_host(ssh_host: str, canonical_host: str) -> str:
    ssh_host, canonical_host = human_text(ssh_host), human_text(canonical_host)
    if ssh_host == canonical_host:
        return canonical_host
    return f"{canonical_host} (via SSH {ssh_host})"


def tailscale_ssh_options(ssh_host: str, canonical_host: str) -> list[str]:
    """Route an SSH alias to its verified MagicDNS name without losing config.

    Keeping ssh_host as the command destination preserves matching `Host` and
    `User` settings. HostKeyAlias preserves an existing known_hosts entry keyed
    by the caller's original IP or hostname.
    """
    if ssh_host == canonical_host:
        return []
    _, _, original_name = ssh_host.rpartition("@")
    _, _, magicdns_name = canonical_host.rpartition("@")
    original_name = (original_name or ssh_host).strip("[]")
    magicdns_name = (magicdns_name or canonical_host).strip("[]")
    return [
        "-o", f"HostName={magicdns_name}",
        "-o", f"HostKeyAlias={original_name}",
    ]
